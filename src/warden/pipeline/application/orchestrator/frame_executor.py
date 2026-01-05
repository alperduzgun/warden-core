"""
Frame executor for validation frames.

Handles frame execution strategies and validation orchestration.
"""

import time
import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable

from warden.pipeline.domain.pipeline_context import PipelineContext
from warden.pipeline.domain.models import (
    PipelineConfig,
    FrameResult,
    FrameRules,
    ValidationPipeline,
)
from warden.pipeline.domain.enums import ExecutionStrategy
from warden.rules.application.rule_validator import CustomRuleValidator
from warden.rules.domain.models import CustomRule, CustomRuleViolation
from warden.validation.domain.frame import CodeFile, ValidationFrame
from warden.shared.infrastructure.logging import get_logger

# Import helper modules
from .frame_matcher import FrameMatcher
from .result_aggregator import ResultAggregator
from warden.shared.infrastructure.ignore_matcher import IgnoreMatcher

logger = get_logger(__name__)


class FrameExecutor:
    """Executes validation frames with various strategies."""

    def __init__(
        self,
        frames: Optional[List[ValidationFrame]] = None,
        config: Optional[PipelineConfig] = None,
        progress_callback: Optional[Callable] = None,
        rule_validator: Optional[CustomRuleValidator] = None,
        llm_service: Optional[Any] = None,
        available_frames: Optional[List[ValidationFrame]] = None,
        semantic_search_service: Optional[Any] = None,
    ):
        """
        Initialize frame executor.

        Args:
            frames: List of validation frames
            config: Pipeline configuration
            progress_callback: Optional callback for progress updates
            rule_validator: Optional rule validator for PRE/POST rules
            llm_service: Optional LLM service for AI-powered validation
            available_frames: List of all available frames (for discovery)
            semantic_search_service: Optional semantic search service
        """
        self.frames = frames or []
        self.config = config or PipelineConfig()
        self.progress_callback = progress_callback
        self.rule_validator = rule_validator
        self.llm_service = llm_service
        self.available_frames = available_frames or self.frames
        self.semantic_search_service = semantic_search_service

        # Initialize helper components
        self.frame_matcher = FrameMatcher(frames, available_frames=self.available_frames)
        self.result_aggregator = ResultAggregator()
        self.ignore_matcher: Optional[IgnoreMatcher] = None

    async def execute_validation_with_strategy_async(
        self,
        context: PipelineContext,
        code_files: List[CodeFile],
        pipeline: ValidationPipeline,
    ) -> None:
        """Execute VALIDATION phase with execution strategies."""
        start_time = time.perf_counter()
        logger.info("executing_phase", phase="VALIDATION")

        if self.progress_callback:
            self.progress_callback("phase_started", {
                "phase": "VALIDATION",
                "phase_name": "VALIDATION"
            })

        try:
            # Filter files based on context if needed
            file_contexts = context.file_contexts or {}
            filtered_files = self._filter_files_by_context(code_files, file_contexts)

            logger.info(
                "validation_file_filtering",
                total_files=len(code_files),
                filtered_files=len(filtered_files),
                filtered_out=len(code_files) - len(filtered_files)
            )

            # Get frames to execute (with fallback logic)
            selected_frames = getattr(context, 'selected_frames', None)
            frames_to_execute = self.frame_matcher.get_frames_to_execute(selected_frames)

            if not frames_to_execute:
                logger.warning("no_frames_to_execute",
                              selected_frames=getattr(context, 'selected_frames', None),
                              configured_frames=len(self.frames))
                # Store empty results
                context.findings = []
                context.validated_issues = []
                context.add_phase_result("VALIDATION", {
                    "total_findings": 0,
                    "validated_issues": 0,
                    "frames_executed": 0,
                    "frames_passed": 0,
                    "frames_failed": 0,
                    "no_frames_reason": "no_frames_selected"
                })
                
                # Emit completion event even for early return
                if self.progress_callback:
                    self.progress_callback("phase_completed", {
                        "phase": "VALIDATION",
                        "phase_name": "VALIDATION",
                        "duration": time.perf_counter() - start_time
                    })
                return

            # Initialize results container safery for concurrency
            if not hasattr(context, 'frame_results') or context.frame_results is None:
                context.frame_results = {}

            # Execute frames based on strategy
            if self.config.strategy == ExecutionStrategy.SEQUENTIAL:
                await self._execute_frames_sequential(context, filtered_files, frames_to_execute, pipeline)
            elif self.config.strategy == ExecutionStrategy.PARALLEL:
                await self._execute_frames_parallel(context, filtered_files, frames_to_execute, pipeline)
            elif self.config.strategy == ExecutionStrategy.FAIL_FAST:
                await self._execute_frames_fail_fast(context, filtered_files, frames_to_execute, pipeline)
            else:
                # Default to sequential
                await self._execute_frames_sequential(context, filtered_files, frames_to_execute, pipeline)

            # Store results in context
            self.result_aggregator.store_validation_results(context, pipeline)

            logger.info(
                "phase_completed",
                phase="VALIDATION",
                findings=len(context.findings) if hasattr(context, 'findings') else 0,
            )

        except Exception as e:
            logger.error("phase_failed", phase="VALIDATION", error=str(e))
            context.errors.append(f"VALIDATION failed: {str(e)}")

        if self.progress_callback:
            duration = time.perf_counter() - start_time
            self.progress_callback("phase_completed", {
                "phase": "VALIDATION",
                "phase_name": "VALIDATION",
                "duration": duration,
                "llm_used": self.llm_service is not None
            })


    async def _execute_frames_sequential(
        self,
        context: PipelineContext,
        code_files: List[CodeFile],
        frames_to_execute: List[ValidationFrame],
        pipeline: ValidationPipeline,
    ) -> None:
        """Execute frames sequentially."""
        logger.info("executing_frames_sequential", count=len(frames_to_execute))

        for frame in frames_to_execute:
            if self.config.fail_fast and pipeline.frames_failed > 0:
                logger.info("skipping_frame_fail_fast", frame_id=frame.frame_id)
                continue

            await self._execute_frame_with_rules(context, frame, code_files, pipeline)

    async def _execute_frames_parallel(
        self,
        context: PipelineContext,
        code_files: List[CodeFile],
        frames_to_execute: List[ValidationFrame],
        pipeline: ValidationPipeline,
    ) -> None:
        """Execute frames in parallel with concurrency limit."""
        logger.info("executing_frames_parallel", count=len(frames_to_execute))

        semaphore = asyncio.Semaphore(self.config.parallel_limit or 3)

        async def execute_with_semaphore(frame):
            async with semaphore:
                await self._execute_frame_with_rules(context, frame, code_files, pipeline)

        tasks = [execute_with_semaphore(frame) for frame in frames_to_execute]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _execute_frames_fail_fast(
        self,
        context: PipelineContext,
        code_files: List[CodeFile],
        frames_to_execute: List[ValidationFrame],
        pipeline: ValidationPipeline,
    ) -> None:
        """Execute frames sequentially, stop on first blocker failure."""
        logger.info("executing_frames_fail_fast", count=len(frames_to_execute))

        for frame in frames_to_execute:
            result = await self._execute_frame_with_rules(context, frame, code_files, pipeline)

            # Check if frame has blocker issues
            if result and hasattr(result, 'has_blocker_issues') and result.has_blocker_issues:
                logger.info("stopping_on_blocker", frame_id=frame.frame_id)
                break

    async def _execute_frame_with_rules(
        self,
        context: PipelineContext,
        frame: ValidationFrame,
        code_files: List[CodeFile],
        pipeline: ValidationPipeline,
    ) -> Optional[FrameResult]:
        """Execute a frame with PRE/POST rules."""
        # Start timing frame execution
        frame_start_time = time.perf_counter()

        # Initialize IgnoreMatcher if not already done
        if self.ignore_matcher is None:
            # Use project_root from context if available, otherwise fallback to cwd
            project_root = getattr(context, 'project_root', None) or Path.cwd()
            use_gitignore = getattr(self.config, 'use_gitignore', True)
            self.ignore_matcher = IgnoreMatcher(project_root, use_gitignore=use_gitignore)

        # Filter files for this specific frame
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
        
        # Use filtered files for execution
        code_files = files_for_frame

        frame_rules = self.config.frame_rules.get(frame.frame_id) if self.config.frame_rules else None

        # Inject LLM service if available
        if self.llm_service:
            frame.llm_service = self.llm_service
        
        # Inject semantic search service if available
        if self.semantic_search_service:
            frame.semantic_search_service = self.semantic_search_service
        
        # Inject project context for context-aware checks (e.g., service abstraction detection)
        if hasattr(frame, 'set_project_context'):
            # Extract ProjectContext from PipelineContext
            # PipelineContext.project_type might hold the ProjectContext object
            project_context = getattr(context, 'project_type', None)
            
            # Verify it's the actual context object (has service_abstractions)
            if project_context and hasattr(project_context, 'service_abstractions'):
                frame.set_project_context(project_context)

        # Execute PRE rules
        pre_violations = []
        if frame_rules and frame_rules.pre_rules:
            logger.info("executing_pre_rules", frame_id=frame.frame_id, rule_count=len(frame_rules.pre_rules))
            pre_violations = await self._execute_rules(frame_rules.pre_rules, code_files)

            if pre_violations and self._has_blocker_violations(pre_violations):
                if frame_rules.on_fail == "stop":
                    logger.error("pre_rules_failed_stopping", frame_id=frame.frame_id)
                    
                    # Create blocking failure result
                    failure_result = FrameResult(
                        frame_id=frame.frame_id,
                        frame_name=frame.name,
                        status="failed",
                        duration=time.perf_counter() - frame_start_time,
                        issues_found=len(pre_violations),
                        is_blocker=True,
                        findings=[],
                        metadata={"failure_reason": "pre_rules_blocker_violation"}
                    )
                    
                    # Register failure
                    pipeline.frames_executed += 1
                    pipeline.frames_failed += 1
                    
                    # Store result context
                    context.frame_results[frame.frame_id] = {
                        'result': failure_result,
                        'pre_violations': pre_violations,
                        'post_violations': []
                    }
                    
                    return failure_result

        # Execute frame
        if self.progress_callback:
            self.progress_callback("frame_started", {
                "frame_id": frame.frame_id,
                "frame_name": frame.name,
            })

        try:
            frame_findings = []
            files_scanned = 0
            execution_errors = 0
            
            # Helper to execute single file
            async def execute_single_file(c_file: CodeFile) -> Optional[FrameResult]:
                # Check for caching
                file_context = context.file_contexts.get(c_file.path)
                if file_context and getattr(file_context, 'is_unchanged', False):
                    # Smart Caching: Skip execution for unchanged files
                    # In a full implementation, we would re-hydrate previous findings here.
                    # For now, we skip and log.
                    logger.debug("skipping_unchanged_file", file=c_file.path, frame=frame.frame_id)
                    return None
                    
                try:
                    # frames usually return FrameResult
                    return await frame.execute(c_file)
                except Exception as ex:
                    logger.error("frame_file_execution_error", 
                                frame=frame.frame_id, 
                                file=c_file.path, 
                                error=str(ex))
                    return None

            if code_files:
                logger.info(
                    "frame_batch_execution_start",
                    frame_id=frame.frame_id,
                    files_to_scan=len(code_files)
                )

                # Use batch execution if available (default impl iterates anyway)
                # But optimized frames (like OrphanFrame) will use smart batching
                
                # Filter out unchanged files for batch execution
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
                     logger.info("smart_caching_active", skipped=cached_files, remaining=len(files_to_scan), frame=frame.frame_id)
                
                if not files_to_scan:
                     logger.info("all_files_cached_skipping_batch", frame=frame.frame_id)
                     # Return empty list or simulation of results
                     f_results = []
                else:
                    try:
                        f_results = await asyncio.wait_for(
                            frame.execute_batch(files_to_scan),
                            timeout=self.config.frame_timeout or 300.0  # Increased timeout for batch
                        )
                        
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

            
            # Determine overall status based on aggregated findings
            # Re-use logic from frame if possible, or simple aggregation
            status = "passed"
            if any(f.severity == 'critical' for f in frame_findings):
                status = "failed"
            elif any(f.severity == 'high' for f in frame_findings):
                status = "warning"

            # Calculate frame execution duration
            frame_duration = time.perf_counter() - frame_start_time

            # Build metadata - include batch_summary if frame has it
            coverage = self._calculate_coverage(code_files, frame_findings)
            
            result_metadata = {
                "files_scanned": files_scanned,
                "execution_errors": execution_errors,
                "coverage": coverage,
                "findings_found": len(frame_findings),
                "findings_fixed": 0,
                "trend": 0,
            }

            # Check for batch_summary (OrphanFrame provides LLM filter reasoning)
            if hasattr(frame, 'batch_summary') and frame.batch_summary:
                result_metadata["llm_filter_summary"] = frame.batch_summary

            frame_result = FrameResult(
                frame_id=frame.frame_id,
                frame_name=frame.name,
                status=status,
                duration=frame_duration,  # Use measured duration
                issues_found=len(frame_findings),
                is_blocker=frame.is_blocker and status == "failed",
                findings=frame_findings,
                metadata=result_metadata
            )

            pipeline.frames_executed += 1
            if status == "failed": # simplified check
                pipeline.frames_failed += 1
            else:
                pipeline.frames_passed += 1

            logger.info("frame_executed_successfully",
                       frame_id=frame.frame_id,
                       files_scanned=files_scanned,
                       findings=len(frame_result.findings))

        except asyncio.TimeoutError:
            # This outer timeout technically catches only if we wrapped the whole loop in timeout
            # which we didn't. But keeping for safety if structure changes.
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

        # Execute POST rules
        post_violations = []
        if frame_rules and frame_rules.post_rules:
            post_violations = await self._execute_rules(frame_rules.post_rules, code_files)

            if post_violations and self._has_blocker_violations(post_violations):
                if frame_rules.on_fail == "stop":
                    logger.error("post_rules_failed_stopping", frame_id=frame.frame_id)

        # Store frame result with violations
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

    def _filter_files_by_context(
        self,
        code_files: List[CodeFile],
        file_contexts: Dict[str, Any],
    ) -> List[CodeFile]:
        """Filter files based on PRE-ANALYSIS context."""
        filtered = []
        for code_file in code_files:
            file_context_info = file_contexts.get(code_file.path)

            # If no context info, assume PRODUCTION
            if not file_context_info:
                filtered.append(code_file)
                continue

            # Get context type from FileContextInfo object
            if hasattr(file_context_info, 'context'):
                context_type = file_context_info.context.value if hasattr(file_context_info.context, 'value') else str(file_context_info.context)
            else:
                context_type = "PRODUCTION"

            # Skip test/example files if configured
            if context_type in ["TEST", "EXAMPLE", "DOCUMENTATION"]:
                if not getattr(self.config, 'include_test_files', False):
                    logger.info("skipping_non_production_file",
                               file=code_file.path,
                               context=context_type)
                    continue

            filtered.append(code_file)

        return filtered

    async def _execute_rules(
        self,
        rules: List[CustomRule],
        code_files: List[CodeFile],
    ) -> List[CustomRuleViolation]:
        """Execute custom rules on code files."""
        if not self.rule_validator:
            return []

        violations = []
        for code_file in code_files:
            file_violations = await self.rule_validator.validate_file_async(
                code_file,
                rules,
            )
            violations.extend(file_violations)

        return violations

    def _has_blocker_violations(
        self,
        violations: List[CustomRuleViolation],
    ) -> bool:
        """Check if any violations are blockers."""
        return any(v.is_blocker for v in violations)

    def _calculate_coverage(self, code_files: List[CodeFile], findings: List[Any]) -> float:
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
                # Try to get file path from finding
                if hasattr(f, 'file_path') and f.file_path:
                    affected_files.add(f.file_path)
                elif hasattr(f, 'location') and f.location:
                    path = f.location.split(':')[0]
                    affected_files.add(path)

        clean_files = total_files - len(affected_files)
        return (clean_files / total_files) * 100


