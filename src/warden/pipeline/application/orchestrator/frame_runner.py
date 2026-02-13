"""
Frame runner for executing validation frames.

Handles the execution of individual frames with rules and dependencies.
"""

import asyncio
import time
from pathlib import Path
from typing import Any, Callable, List, Optional

from warden.pipeline.domain.models import FrameResult, PipelineConfig, ValidationPipeline
from warden.pipeline.domain.pipeline_context import PipelineContext
from warden.shared.infrastructure.error_handler import async_error_handler
from warden.shared.infrastructure.ignore_matcher import IgnoreMatcher
from warden.shared.infrastructure.logging import get_logger
from warden.validation.domain.frame import CodeFile, ValidationFrame
from warden.validation.domain.mixins import BatchExecutable, Cleanable, ProjectContextAware

from .dependency_checker import DependencyChecker
from .file_filter import FileFilter
from .rule_executor import RuleExecutor
from .suppression_filter import SuppressionFilter

logger = get_logger(__name__)


class FrameRunner:
    """Executes individual validation frames with rules and dependencies."""

    def __init__(
        self,
        config: PipelineConfig | None = None,
        progress_callback: Callable | None = None,
        rule_executor: RuleExecutor | None = None,
        llm_service: Any | None = None,
        semantic_search_service: Any | None = None,
    ):
        self.config = config or PipelineConfig()
        self.progress_callback = progress_callback
        self.rule_executor = rule_executor or RuleExecutor()
        self.llm_service = llm_service
        self.semantic_search_service = semantic_search_service
        self.ignore_matcher: IgnoreMatcher | None = None

    @async_error_handler(
        fallback_value=None,
        log_level="error",
        context_keys=["frame_id"],
        reraise=False
    )
    async def execute_frame_with_rules_async(
        self,
        context: PipelineContext,
        frame: ValidationFrame,
        code_files: list[CodeFile],
        pipeline: ValidationPipeline,
    ) -> FrameResult | None:
        """
        Execute a frame with PRE/POST rules.

        Uses centralized error handler to ensure frame failures are logged
        and don't crash the entire pipeline.
        """
        skip_result = DependencyChecker.check_frame_dependencies(context, frame)
        if skip_result:
            logger.info(
                "frame_skipped_dependencies",
                frame_id=frame.frame_id,
                reason=skip_result.metadata.get("skip_reason") if skip_result.metadata else "unknown"
            )
            context.frame_results[frame.frame_id] = {
                'result': skip_result,
                'pre_violations': [],
                'post_violations': [],
            }
            if self.progress_callback:
                self.progress_callback("frame_completed", {
                    "frame_id": frame.frame_id,
                    "frame_name": frame.name,
                    "status": "skipped",
                    "findings": 0,
                    "duration": 0.0,
                    "skip_reason": skip_result.metadata.get("skip_reason") if skip_result.metadata else None
                })
            return skip_result

        frame_start_time = time.perf_counter()

        if self.ignore_matcher is None:
            project_root = getattr(context, 'project_root', None) or Path.cwd()
            use_gitignore = getattr(self.config, 'use_gitignore', True)
            self.ignore_matcher = IgnoreMatcher(project_root, use_gitignore=use_gitignore)

        frame_id = frame.frame_id
        original_count = len(code_files)
        files_for_frame = [
            cf for cf in code_files
            if not self.ignore_matcher.should_ignore_for_frame(Path(cf.path), frame_id)
        ]

        if len(files_for_frame) < original_count:
            logger.info(
                "frame_specific_ignore",
                frame=frame_id,
                ignored=original_count - len(files_for_frame),
                remaining=len(files_for_frame)
            )

        files_for_frame = FileFilter.apply_triage_routing(context, frame, files_for_frame)
        code_files = files_for_frame

        frame_rules = self.config.frame_rules.get(frame.frame_id) if self.config.frame_rules else None

        if self.llm_service:
            frame.llm_service = self.llm_service

        if self.semantic_search_service:
            frame.semantic_search_service = self.semantic_search_service

        if isinstance(frame, ProjectContextAware):
            project_context = getattr(context, 'project_type', None)
            if project_context and hasattr(project_context, 'service_abstractions'):
                frame.set_project_context(project_context)

        pre_violations = []
        if frame_rules and frame_rules.pre_rules:
            logger.info("executing_pre_rules", frame_id=frame.frame_id, rule_count=len(frame_rules.pre_rules))
            pre_violations = await self.rule_executor.execute_rules_async(frame_rules.pre_rules, code_files)

            if pre_violations and RuleExecutor.has_blocker_violations(pre_violations):
                if frame_rules.on_fail == "stop":
                    logger.error("pre_rules_failed_stopping", frame_id=frame.frame_id)

                    failure_result = FrameResult(
                        frame_id=frame.frame_id,
                        frame_name=frame.name,
                        status="failed",
                        duration=time.perf_counter() - frame_start_time,
                        issues_found=len(pre_violations),
                        is_blocker=True,
                        findings=[RuleExecutor.convert_to_finding(v) for v in pre_violations],
                        metadata={"failure_reason": "pre_rules_blocker_violation"}
                    )

                    pipeline.frames_executed += 1
                    pipeline.frames_failed += 1

                    context.frame_results[frame.frame_id] = {
                        'result': failure_result,
                        'pre_violations': pre_violations,
                        'post_violations': []
                    }

                    return failure_result

        if self.progress_callback:
            self.progress_callback("frame_started", {
                "frame_id": frame.frame_id,
                "frame_name": frame.name,
            })

        # Inject cached AST parse results into code file metadata
        if context.ast_cache:
            for cf in code_files:
                if cf.path in context.ast_cache:
                    if cf.metadata is None:
                        cf.metadata = {}
                    cf.metadata["_cached_parse_result"] = context.ast_cache[cf.path]

        # Get metrics collector for per-frame cost attribution
        from warden.llm.metrics import get_global_metrics_collector
        metrics_collector = get_global_metrics_collector()

        # Wrap the entire frame execution in frame_scope for automatic LLM attribution
        with metrics_collector.frame_scope(frame.frame_id):
            try:
                frame_findings = []
                files_scanned = 0
                execution_errors = 0

                async def execute_single_file_async(c_file: CodeFile) -> FrameResult | None:
                    file_context = context.file_contexts.get(c_file.path)
                    if file_context and getattr(file_context, 'is_unchanged', False):
                        logger.debug("skipping_unchanged_file", file=c_file.path, frame=frame.frame_id)
                        return None

                    try:
                        result = await frame.execute_async(c_file)

                        if self.progress_callback:
                            self.progress_callback("progress_update", {
                                "increment": 1,
                                "frame_id": frame.frame_id,
                                "file": c_file.path
                            })
                        return result
                    except Exception as ex:
                        logger.error("frame_file_execution_error",
                                    frame=frame.frame_id,
                                    file=c_file.path,
                                    error=str(ex))
                        if self.progress_callback:
                            self.progress_callback("progress_update", {
                                "increment": 1,
                                "error": True
                            })
                        return None

                if code_files:
                    if len(code_files) > 1:
                        logger.debug(
                            "frame_batch_execution_start",
                            frame_id=frame.frame_id,
                            files_to_scan=len(code_files)
                        )

                    files_to_scan = []
                    cached_files = 0

                    for cf in code_files:
                        ctx = context.file_contexts.get(cf.path)
                        if ctx and getattr(ctx, 'is_unchanged', False):
                            cached_files += 1
                            logger.debug("skipping_unchanged_file_batch", file=cf.path, frame=frame.frame_id)
                        else:
                            files_to_scan.append(cf)

                    if cached_files > 0:
                         log_func = logger.info if len(files_to_scan) > 0 else logger.debug
                         log_func("smart_caching_active", skipped=cached_files, remaining=len(files_to_scan), frame=frame.frame_id)

                         if self.progress_callback:
                             self.progress_callback("progress_update", {
                                 "increment": cached_files,
                                 "frame_id": frame.frame_id,
                                 "details": f"Skipped {cached_files} cached files"
                             })

                    if not files_to_scan:
                         logger.debug("all_files_cached_skipping_batch", frame=frame.frame_id)
                         f_results = []
                    else:
                        try:
                            if isinstance(frame, BatchExecutable):
                                f_results = []
                                total_files_to_scan = len(files_to_scan)
                                CHUNK_SIZE = 5

                                for i in range(0, total_files_to_scan, CHUNK_SIZE):
                                    chunk = files_to_scan[i:i+CHUNK_SIZE]
                                    chunk_results = await asyncio.wait_for(
                                        frame.execute_batch_async(chunk),
                                        timeout=getattr(self.config, 'frame_timeout', 300.0)
                                    )
                                    if chunk_results:
                                        f_results.extend(chunk_results)
                                        if self.progress_callback:
                                            self.progress_callback("progress_update", {
                                                "increment": len(chunk_results),
                                                "frame_id": frame.frame_id,
                                                "phase": f"Validating {frame.name}"
                                            })
                            else:
                                f_results = []
                                for cf in files_to_scan:
                                    result = await execute_single_file_async(cf)
                                    if result:
                                        f_results.append(result)

                            if isinstance(frame, Cleanable):
                                await frame.cleanup()

                            if f_results:
                                files_scanned = len(f_results)
                                total_findings_from_batch = sum(len(res.findings) if res and res.findings else 0 for res in f_results)

                                logger.info(
                                    "frame_batch_execution_complete",
                                    frame_id=frame.frame_id,
                                    results_count=files_scanned,
                                    total_findings=total_findings_from_batch
                                )

                                for res in f_results:
                                    if res and res.findings:
                                        frame_findings.extend(res.findings)

                        except asyncio.TimeoutError:
                            logger.warning("frame_batch_execution_timeout", frame=frame.frame_id)
                            execution_errors += 1
                        except Exception as ex:
                            logger.error("frame_batch_execution_error", frame=frame.frame_id, error=str(ex))
                            execution_errors += 1

                status = "passed"
                if any(f.severity == 'critical' for f in frame_findings):
                    status = "failed"
                elif any(f.severity == 'high' for f in frame_findings):
                    status = "warning"

                frame_duration = time.perf_counter() - frame_start_time

                coverage = self._calculate_coverage(code_files, frame_findings)

                result_metadata = {
                    "files_scanned": files_scanned,
                    "execution_errors": execution_errors,
                    "coverage": coverage,
                    "findings_found": len(frame_findings),
                    "findings_fixed": 0,
                    "trend": 0,
                }

                if hasattr(frame, 'batch_summary') and frame.batch_summary:
                    result_metadata["llm_filter_summary"] = frame.batch_summary

                if hasattr(frame, 'config') and frame.config and 'suppressions' in frame.config:
                    suppressions = frame.config['suppressions']
                    if suppressions and frame_findings:
                         findings_before = len(frame_findings)
                         frame_findings = SuppressionFilter.apply_config_suppressions(frame_findings, suppressions)
                         findings_after = len(frame_findings)

                         if findings_before != findings_after:
                             logger.info("suppression_applied",
                                   frame_id=frame.frame_id,
                                   suppressed=findings_before - findings_after)

                frame_result = FrameResult(
                    frame_id=frame.frame_id,
                    frame_name=frame.name,
                    status=status,
                    duration=frame_duration,
                    issues_found=len(frame_findings),
                    is_blocker=frame.is_blocker and status == "failed",
                    findings=frame_findings,
                    metadata=result_metadata
                )

                pipeline.frames_executed += 1
                if status == "failed":
                    pipeline.frames_failed += 1
                else:
                    pipeline.frames_passed += 1

                if files_scanned > 0 or len(frame_result.findings) > 0:
                    logger.info("frame_executed_successfully",
                               frame_id=frame.frame_id,
                               files_scanned=files_scanned,
                               findings=len(frame_result.findings))
                else:
                    logger.debug("frame_executed_successfully",
                               frame_id=frame.frame_id,
                               files_scanned=files_scanned,
                               findings=0)

            except asyncio.TimeoutError:
                logger.error("frame_timeout", frame_id=frame.frame_id)
                frame_result = FrameResult(
                    frame_id=frame.frame_id,
                    frame_name=frame.name,
                    status="timeout",
                    findings=[],
                )
                pipeline.frames_failed += 1
            except Exception as e:
                logger.error("frame_execution_error",
                            frame_id=frame.frame_id,
                            error=str(e),
                            error_type=type(e).__name__)
                frame_result = FrameResult(
                    frame_id=frame.frame_id,
                    frame_name=frame.name,
                    status="error",
                    findings=[],
                )
                pipeline.frames_failed += 1

        post_violations = []
        if frame_rules and frame_rules.post_rules:
            post_violations = await self.rule_executor.execute_rules_async(frame_rules.post_rules, code_files)

            if post_violations and RuleExecutor.has_blocker_violations(post_violations):
                if frame_rules.on_fail == "stop":
                    logger.error("post_rules_failed_stopping", frame_id=frame.frame_id)

        frame_result.pre_rule_violations = pre_violations if pre_violations else None
        frame_result.post_rule_violations = post_violations if post_violations else None

        if pre_violations:
             frame_result.findings.extend([RuleExecutor.convert_to_finding(v) for v in pre_violations])
        if post_violations:
             frame_result.findings.extend([RuleExecutor.convert_to_finding(v) for v in post_violations])

        context.frame_results[frame.frame_id] = {
            'result': frame_result,
            'pre_violations': pre_violations,
            'post_violations': post_violations,
        }

        if self.progress_callback:
            self.progress_callback("frame_completed", {
                "frame_id": frame.frame_id,
                "frame_name": frame.name,
                "status": frame_result.status,
                "findings": len(frame_result.findings) if hasattr(frame_result, 'findings') else 0,
                "duration": getattr(frame_result, 'duration', 0.0)
            })

        return frame_result

    def _calculate_coverage(self, code_files: list[CodeFile], findings: list[Any]) -> float:
        """
        Calculate frame coverage percentage based on quality.
        Coverage = (Files without critical/high issues / Total files) * 100
        """
        if not code_files:
            return 0.0

        total_files = len(code_files)
        affected_files = set()

        for f in findings:
            severity = getattr(f, 'severity', '').lower()
            if severity in ['critical', 'high']:
                if hasattr(f, 'file_path') and f.file_path:
                    affected_files.add(f.file_path)
                elif hasattr(f, 'location') and f.location:
                    path = f.location.split(':')[0]
                    affected_files.add(path)

        clean_files = total_files - len(affected_files)
        return (clean_files / total_files) * 100
