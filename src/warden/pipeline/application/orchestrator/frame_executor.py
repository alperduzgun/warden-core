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
import fnmatch
from warden.validation.application.rust_validation_engine import RustValidationEngine

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

            # Initialize results container safery for concurrency
            if not hasattr(context, 'frame_results') or context.frame_results is None:
                context.frame_results = {}

            # Phase 1: Global Rust-based Pre-filtering
            await self._run_rust_pre_filtering_async(context, filtered_files)

            # Execute frames based on strategy
            if frames_to_execute:
                if self.config.strategy == ExecutionStrategy.SEQUENTIAL:
                    await self._execute_frames_sequential_async(context, filtered_files, frames_to_execute, pipeline)
                elif self.config.strategy == ExecutionStrategy.PARALLEL:
                    await self._execute_frames_parallel_async(context, filtered_files, frames_to_execute, pipeline)
                elif self.config.strategy == ExecutionStrategy.FAIL_FAST:
                    await self._execute_frames_fail_fast_async(context, filtered_files, frames_to_execute, pipeline)
                else:
                    await self._execute_frames_sequential_async(context, filtered_files, frames_to_execute, pipeline)
            

            # Execute Global Rules (Standard Python Rules - Fallback/Legacy)
            if self.rule_validator and self.rule_validator.rules:
                logger.info("executing_global_rules", rule_count=len(self.rule_validator.rules))
                global_violations = []
                for code_file in filtered_files:
                    file_violations = await self.rule_validator.validate_file_async(code_file.path)
                    global_violations.extend(file_violations)
                
                if global_violations:
                    logger.info("global_rules_found_violations", count=len(global_violations))
                    
                    # Virtual Frame Attribution for ghost issues
                    frame_id = "global_script_rules"
                    frame_result = FrameResult(
                        frame_id=frame_id,
                        frame_name="Global Script Rules",
                        status="failed",
                        duration=0.5,
                        issues_found=len(global_violations),
                        is_blocker=any(v.is_blocker for v in global_violations),
                        findings=global_violations,
                        metadata={"engine": "python_rules"}
                    )
                    
                    if not hasattr(context, 'frame_results') or context.frame_results is None:
                        context.frame_results = {}
                    
                    context.frame_results[frame_id] = {
                        'result': frame_result,
                        'pre_violations': [],
                        'post_violations': []
                    }
                    
                    # Add to context findings
                    context.findings.extend(global_violations)

            # Store results in context
            logger.info("debug_frame_results_before_aggregation", frames=list(context.frame_results.keys()))
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


    async def _run_rust_pre_filtering_async(
        self,
        context: PipelineContext,
        code_files: List[CodeFile],
    ) -> None:
        """Run global high-performance pre-filtering using Rust engine."""
        project_root = getattr(context, 'project_root', Path.cwd())
        # Prepare engine
        engine = RustValidationEngine(project_root)
        
        # 1. Load default global rules (System Rules)
        import warden
        package_root = Path(warden.__file__).parent
        rule_paths = [
            package_root / "rules/defaults/python/security.yaml",
            package_root / "rules/defaults/javascript/security.yaml",
        ]
        
        logger.info("debug_rule_paths", package_root=str(package_root))
        for path in rule_paths:
            exists = path.exists()
            logger.info("debug_rule_path_check", path=str(path), exists=exists)
            if exists:
                await engine.load_rules_from_yaml_async(path)
        
        # 2. Add custom rules from validator (Project Rules)
        if self.rule_validator and self.rule_validator.rules:
            # Only add rules that have regex patterns and are not already handled or are appropriate for Rust
            regex_rules = [r for r in self.rule_validator.rules if r.pattern and r.type != 'ai']
            if regex_rules:
                engine.add_custom_rules(regex_rules)
        
        if not engine.rust_rules:
            logger.debug("no_global_rust_rules_and_no_custom_regex_rules_skipping_scan")
            return

        # Prepare file paths
        file_paths = [Path(cf.path) for cf in code_files]
        
        # Execute scan
        try:
            findings = await engine.scan_project_async(file_paths)
            if findings:
                total_hits = len(findings)
                logger.info("rust_scan_raw_hits", count=total_hits)
                
                # Alpha Judgment: Global high-speed filtering
                from warden.validation.application.alpha_judgment import AlphaJudgment
                alpha = AlphaJudgment(config=self.config.dict() if hasattr(self.config, 'dict') else {})
                
                filtered_findings = alpha.evaluate(findings, code_files)
                
                if filtered_findings:
                    logger.info("rust_pre_filtering_found_issues", 
                              raw=total_hits, 
                              filtered=len(filtered_findings))
                    
                    # Virtual Frame Attribution for ghost issues
                    frame_id = "system_security_rules"
                    frame_result = FrameResult(
                        frame_id=frame_id,
                        frame_name="System Security Rules (Rust)",
                        status="failed",
                        duration=0.1, # Rust is fast
                        issues_found=len(filtered_findings),
                        is_blocker=any(f.severity == 'critical' for f in filtered_findings),
                        findings=filtered_findings,
                        metadata={
                            "engine": "rust",
                            "raw_hits": total_hits,
                            "filtered_hits": len(filtered_findings)
                        }
                    )
                    
                    if not hasattr(context, 'frame_results') or context.frame_results is None:
                        context.frame_results = {}
                    
                    context.frame_results[frame_id] = {
                        'result': frame_result,
                        'pre_violations': [],
                        'post_violations': []
                    }
                    
                    # Also keep in global findings for compatibility
                    context.findings.extend(filtered_findings)
                else:
                    logger.info("alpha_judgment_filtered_all_hits", raw=total_hits)

        except Exception as e:
            logger.error("rust_pre_filtering_failed", error=str(e), error_type=type(e).__name__)

    async def _execute_frames_sequential_async(
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

            await self._execute_frame_with_rules_async(context, frame, code_files, pipeline)

    async def _execute_frames_parallel_async(
        self,
        context: PipelineContext,
        code_files: List[CodeFile],
        frames_to_execute: List[ValidationFrame],
        pipeline: ValidationPipeline,
    ) -> None:
        """Execute frames in parallel with concurrency limit."""
        logger.info("executing_frames_parallel", count=len(frames_to_execute))

        semaphore = asyncio.Semaphore(self.config.parallel_limit or 3)

        async def execute_with_semaphore_async(frame):
            async with semaphore:
                await self._execute_frame_with_rules_async(context, frame, code_files, pipeline)

        tasks = [execute_with_semaphore_async(frame) for frame in frames_to_execute]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _execute_frames_fail_fast_async(
        self,
        context: PipelineContext,
        code_files: List[CodeFile],
        frames_to_execute: List[ValidationFrame],
        pipeline: ValidationPipeline,
    ) -> None:
        """Execute frames sequentially, stop on first blocker failure."""
        logger.info("executing_frames_fail_fast", count=len(frames_to_execute))

        for frame in frames_to_execute:
            result = await self._execute_frame_with_rules_async(context, frame, code_files, pipeline)

            # Check if frame has blocker issues
            if result and hasattr(result, 'has_blocker_issues') and result.has_blocker_issues:
                logger.info("stopping_on_blocker", frame_id=frame.frame_id)
                break

    async def _execute_frame_with_rules_async(
        self,
        context: PipelineContext,
        frame: ValidationFrame,
        code_files: List[CodeFile],
        pipeline: ValidationPipeline,
    ) -> Optional[FrameResult]:
        """Execute a frame with PRE/POST rules."""
        # Check frame dependencies before execution
        skip_result = self._check_frame_dependencies(context, frame)
        if skip_result:
            logger.info(
                "frame_skipped_dependencies",
                frame_id=frame.frame_id,
                reason=skip_result.metadata.get("skip_reason") if skip_result.metadata else "unknown"
            )
            # Store skip result and emit callback
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
        

        
        # Apply Triage Routing (Adaptive Hybrid Triage)
        files_for_frame = self._apply_triage_routing(context, frame, files_for_frame)

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
            pre_violations = await self._execute_rules_async(frame_rules.pre_rules, code_files)

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
            async def execute_single_file_async(c_file: CodeFile) -> Optional[FrameResult]:
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
                # Optimized logging for batch start
                if len(code_files) > 1:
                    logger.debug(
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
                     log_func = logger.info if len(files_to_scan) > 0 else logger.debug
                     log_func("smart_caching_active", skipped=cached_files, remaining=len(files_to_scan), frame=frame.frame_id)
                     
                     # Update progress for cached files
                     if self.progress_callback:
                         self.progress_callback("progress_update", {
                             "increment": cached_files,
                             "frame_id": frame.frame_id,
                             "details": f"Skipped {cached_files} cached files"
                         })
                
                if not files_to_scan:
                     logger.debug("all_files_cached_skipping_batch", frame=frame.frame_id)
                     # Return empty list or simulation of results
                     f_results = []
                else:
                    try:
                        # Revert to per-file execution if batch is not explicitly handled or for better granularity
                        # Note: Most frames use batching for performance, but we need to report per-file for UX
                        f_results = []
                        total_files_to_scan = len(files_to_scan)
                        
                        # If frame handles batch natively and efficiently, we call it in smaller chunks
                        # to maintain both performance and progress visibility
                        CHUNK_SIZE = 5 # Small chunk for better responsiveness
                        
                        for i in range(0, total_files_to_scan, CHUNK_SIZE):
                            chunk = files_to_scan[i:i+CHUNK_SIZE]
                            chunk_results = await asyncio.wait_for(
                                frame.execute_batch_async(chunk),
                                timeout=getattr(self.config, 'frame_timeout', 300.0)
                            )
                            if chunk_results:
                                f_results.extend(chunk_results)
                                # Update progress per group
                                if self.progress_callback:
                                    self.progress_callback("progress_update", {
                                        "increment": len(chunk_results),
                                        "frame_id": frame.frame_id,
                                        "phase": f"Validating {frame.name}"
                                    })
                        
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

            # Apply Config-Based Suppressions (Internal Findings)
            if hasattr(frame, 'config') and frame.config and 'suppressions' in frame.config:
                suppressions = frame.config['suppressions']
                if suppressions and frame_findings:
                     # Filter findings
                     findings_before = len(frame_findings)
                     frame_findings = self._apply_config_suppressions(frame_findings, suppressions)
                     findings_after = len(frame_findings)
                     
                     if findings_before != findings_after:
                         logger.info("suppression_applied", 
                               frame_id=frame.frame_id, 
                               suppressed=findings_before - findings_after)

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

            # Only log successful completion at info level if there was actual work or findings
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
            post_violations = await self._execute_rules_async(frame_rules.post_rules, code_files)

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

    async def _execute_rules_async(
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

    def _check_frame_dependencies(
        self,
        context: PipelineContext,
        frame: ValidationFrame,
    ) -> Optional[FrameResult]:
        """
        Check if frame dependencies are satisfied.

        Returns FrameResult with status='skipped' if dependencies not met,
        otherwise returns None to continue execution.

        Checks:
        1. requires_frames: Required frames must have executed
        2. requires_config: Required config paths must be set
        3. requires_context: Required context attributes must exist
        """
        # 1. Check required frames
        required_frames = getattr(frame, 'requires_frames', [])
        for req_frame_id in required_frames:
            if req_frame_id not in context.frame_results:
                return FrameResult(
                    frame_id=frame.frame_id,
                    frame_name=frame.name,
                    status="skipped",
                    duration=0.0,
                    issues_found=0,
                    is_blocker=False,
                    findings=[],
                    metadata={
                        "skip_reason": f"Required frame '{req_frame_id}' has not been executed",
                        "dependency_type": "frame",
                        "missing_dependency": req_frame_id,
                    }
                )

        # 2. Check required config paths
        required_configs = getattr(frame, 'requires_config', [])
        for config_path in required_configs:
            if not self._config_path_exists(frame.config, config_path):
                return FrameResult(
                    frame_id=frame.frame_id,
                    frame_name=frame.name,
                    status="skipped",
                    duration=0.0,
                    issues_found=0,
                    is_blocker=False,
                    findings=[],
                    metadata={
                        "skip_reason": f"Required config '{config_path}' is not set",
                        "dependency_type": "config",
                        "missing_dependency": config_path,
                        "help": f"Add '{config_path}' to .warden/config.yaml",
                    }
                )

        # 3. Check required context attributes
        required_context = getattr(frame, 'requires_context', [])
        for ctx_attr in required_context:
            if not self._context_attr_exists(context, ctx_attr):
                return FrameResult(
                    frame_id=frame.frame_id,
                    frame_name=frame.name,
                    status="skipped",
                    duration=0.0,
                    issues_found=0,
                    is_blocker=False,
                    findings=[],
                    metadata={
                        "skip_reason": f"Required context '{ctx_attr}' is not available",
                        "dependency_type": "context",
                        "missing_dependency": ctx_attr,
                        "help": "Ensure prerequisite phases/frames have run",
                    }
                )

        # All dependencies satisfied
        return None

    def _apply_triage_routing(
        self,
        context: PipelineContext,
        frame: ValidationFrame,
        code_files: List[CodeFile]
    ) -> List[CodeFile]:
        """
        Filter files based on Triage Lane and Frame cost.
        
        Logic:
        - Fast Lane: Skip expensive/LLM frames
        - Middle/Deep Lane: Execute everything
        """
        if not hasattr(context, 'triage_decisions') or not context.triage_decisions:
            return code_files
            
        # Determine if frame is expensive/LLM-based
        is_expensive = False
        
        # Check config first
        if hasattr(frame, 'config') and frame.config.get('use_llm') is True:
            is_expensive = True
        else:
            # Fallback heuristic
            expensive_keywords = ['security', 'complex', 'architecture', 'design', 'refactor', 'llm', 'deep']
            if any(k in frame.frame_id.lower() for k in expensive_keywords):
                is_expensive = True
            
        if not is_expensive:
            return code_files # Run cheap frames on everything
            
        filtered = []
        skipped_count = 0
        
        for cf in code_files:
            decision_data = context.triage_decisions.get(cf.path)
            if not decision_data:
                filtered.append(cf) # Default to run if no decision
                continue
                
            lane = decision_data.get('lane')
            
            # Inject Metadata for Frames to use (e.g. for Tier selection)
            if cf.metadata is None:
                cf.metadata = {}
            cf.metadata['triage_lane'] = lane
            
            # ROUTING LOGIC:
            # Fast Lane -> Skip Expensive Frames
            if lane == 'fast_lane':
                skipped_count += 1
                continue
                
            # Middle/Deep -> Run Expensive Frames
            filtered.append(cf)
            
        if skipped_count > 0:
             logger.info(
                 "triage_routing_applied", 
                 frame=frame.frame_id, 
                 skipped=skipped_count, 
                 remaining=len(filtered)
             )
             
        return filtered

    def _config_path_exists(self, config: Optional[Dict[str, Any]], path: str) -> bool:
        """
        Check if a config path exists and has a value.

        Args:
            config: Frame configuration dictionary
            path: Dot-separated path (e.g., "spec.platforms")

        Returns:
            True if path exists and has a non-empty value
        """
        if not config:
            return False

        parts = path.split(".")
        current = config

        for part in parts:
            if not isinstance(current, dict) or part not in current:
                return False
            current = current[part]

        # Check if value is non-empty
        if current is None:
            return False
        if isinstance(current, (list, dict, str)) and len(current) == 0:
            return False

        return True

    def _context_attr_exists(self, context: PipelineContext, attr: str) -> bool:
        """
        Check if a context attribute exists and has a value.

        Args:
            context: Pipeline context
            attr: Attribute name (e.g., "project_context", "service_abstractions")

        Returns:
            True if attribute exists and is not None/empty
        """
        # Handle nested attributes (e.g., "project_type.service_abstractions")
        parts = attr.split(".")
        current: Any = context

        for part in parts:
            if hasattr(current, part):
                current = getattr(current, part)
            elif isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return False

        # Check if value is non-empty
        if current is None:
            return False
        if isinstance(current, (list, dict)) and len(current) == 0:
            return False

        return True


    def _apply_config_suppressions(self, findings: List[Any], suppressions: List[Dict[str, Any]]) -> List[Any]:
        """
        Apply configuration-based suppression rules.
        
        Args:
           findings: List of finding objects
           suppressions: List of suppression dicts (from config.yaml)
           
        Returns:
           Filtered list of findings
        """
        if not findings or not suppressions:
            return findings

        filtered_findings = []
        
        for finding in findings:
            is_suppressed = False
            
            # Finding attributes
            f_id = getattr(finding, 'id', getattr(finding, 'rule', ''))
            
            # Extract file path
            f_path = ""
            if hasattr(finding, 'file_path'):
                f_path = finding.file_path
            elif hasattr(finding, 'location'):
                f_path = finding.location.split(':')[0]
            
            for rule_cfg in suppressions:
                rule_pattern = rule_cfg.get('rule')
                file_patterns = rule_cfg.get('files', [])
                if isinstance(file_patterns, str):
                    file_patterns = [file_patterns]
                
                # Check Finding ID Match (Logic: if rule is '*', match all)
                if rule_pattern != '*' and rule_pattern != f_id:
                    continue
                    
                # Check File Pattern Match
                matched_file = False
                if not file_patterns: 
                    # If no files specified, global suppression for this rule? 
                    # Let's assume explicit file listing is safer, but empty list = none
                    continue
                    
                if f_path:
                    for pattern in file_patterns:
                        if fnmatch.fnmatch(f_path, pattern):
                            matched_file = True
                            break
                            
                if not matched_file:
                    continue
                        
                # If we get here, matched
                logger.debug("suppressing_finding_by_config", 
                            finding=f_id, 
                            file=f_path)
                is_suppressed = True
                break
            
            if not is_suppressed:
                filtered_findings.append(finding)
                
        return filtered_findings
