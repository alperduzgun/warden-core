"""
Frame executor for validation frames.

Handles frame matching, execution strategies, and fallback mechanisms.
"""

import asyncio
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

logger = get_logger(__name__)


class FrameExecutor:
    """Executes validation frames with various strategies."""

    def __init__(
        self,
        frames: Optional[List[ValidationFrame]] = None,
        config: Optional[PipelineConfig] = None,
        progress_callback: Optional[Callable] = None,
        rule_validator: Optional[CustomRuleValidator] = None,
    ):
        """
        Initialize frame executor.

        Args:
            frames: List of validation frames
            config: Pipeline configuration
            progress_callback: Optional callback for progress updates
            rule_validator: Optional rule validator for PRE/POST rules
        """
        self.frames = frames or []
        self.config = config or PipelineConfig()
        self.progress_callback = progress_callback
        self.rule_validator = rule_validator

    async def execute_validation_with_strategy_async(
        self,
        context: PipelineContext,
        code_files: List[CodeFile],
        pipeline: ValidationPipeline,
    ) -> None:
        """Execute VALIDATION phase with execution strategies."""
        logger.info("executing_phase", phase="VALIDATION")

        if self.progress_callback:
            self.progress_callback("phase_started", {"phase": "VALIDATION"})

        try:
            # Filter files based on context if needed
            file_contexts = context.file_contexts or {}
            filtered_files = self._filter_files_by_context(code_files, file_contexts)

            # Get frames to execute (with fallback logic)
            frames_to_execute = self._get_frames_to_execute(context)

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
                return

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
            self._store_validation_results(context, pipeline)

            logger.info(
                "phase_completed",
                phase="VALIDATION",
                findings=len(context.findings) if hasattr(context, 'findings') else 0,
            )

        except Exception as e:
            logger.error("phase_failed", phase="VALIDATION", error=str(e))
            context.errors.append(f"VALIDATION failed: {str(e)}")

        if self.progress_callback:
            self.progress_callback("phase_completed", {"phase": "VALIDATION"})

    def _get_frames_to_execute(self, context: PipelineContext) -> List[ValidationFrame]:
        """
        Get frames to execute with improved matching and fallback logic.

        Args:
            context: Pipeline context with classification results

        Returns:
            List of frames to execute
        """
        # Check if Classification phase selected frames
        if hasattr(context, 'selected_frames') and context.selected_frames:
            logger.info("using_classification_selected_frames",
                       selected=context.selected_frames)

            # Improved frame matching logic
            frames_to_execute = []
            for selected_name in context.selected_frames:
                frame = self._find_frame_by_name(selected_name)
                if frame:
                    frames_to_execute.append(frame)
                    logger.debug(f"Matched frame: {selected_name} -> {frame.frame_id}")
                else:
                    logger.warning(f"Could not match frame: {selected_name}")

            # If we matched at least one frame, use them
            if frames_to_execute:
                logger.info(f"Executing {len(frames_to_execute)} frames from Classification")
                return frames_to_execute

            # If no frames matched, fall back to all frames
            logger.warning("classification_frames_not_matched_using_all_frames",
                          selected=context.selected_frames,
                          available=[f.frame_id for f in self.frames])
        else:
            logger.info("no_classification_results_using_all_frames")

        # Fallback: Use all configured frames
        logger.info(f"Using all {len(self.frames)} configured frames")
        return self.frames

    def _find_frame_by_name(self, name: str) -> Optional[ValidationFrame]:
        """
        Find a frame by various name formats.

        Handles formats like:
        - "security" -> SecurityFrame
        - "Security" -> SecurityFrame
        - "security-frame" -> SecurityFrame
        - "security_frame" -> SecurityFrame
        - "Security Analysis" -> SecurityFrame (by frame.name)
        """
        # Normalize the search name
        search_normalized = name.lower().replace('frame', '').replace('-', '').replace('_', '').strip()

        for frame in self.frames:
            # Try matching by frame_id
            frame_id_normalized = frame.frame_id.lower().replace('frame', '').replace('-', '').replace('_', '').strip()
            if frame_id_normalized == search_normalized:
                return frame

            # Try matching by frame name
            if hasattr(frame, 'name'):
                frame_name_normalized = frame.name.lower().replace(' ', '').replace('-', '').replace('_', '').replace('frame', '').replace('analysis', '').strip()
                if frame_name_normalized == search_normalized:
                    return frame

            # Try partial matching
            if search_normalized in frame_id_normalized or frame_id_normalized in search_normalized:
                return frame

        return None

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
        frame_rules = self.config.frame_rules.get(frame.frame_id) if self.config.frame_rules else None

        # Execute PRE rules
        pre_violations = []
        if frame_rules and frame_rules.pre_rules:
            logger.info("executing_pre_rules", frame_id=frame.frame_id, rule_count=len(frame_rules.pre_rules))
            pre_violations = await self._execute_rules(frame_rules.pre_rules, code_files)

            if pre_violations and self._has_blocker_violations(pre_violations):
                if frame_rules.on_fail == "stop":
                    logger.error("pre_rules_failed_stopping", frame_id=frame.frame_id)
                    return None

        # Execute frame
        if self.progress_callback:
            self.progress_callback("frame_started", {
                "frame_id": frame.frame_id,
                "frame_name": frame.name,
            })

        try:
            # Frames expect a single CodeFile, not a list
            if code_files and len(code_files) > 0:
                # Execute frame on first file (later we can iterate over all files)
                frame_result = await asyncio.wait_for(
                    frame.execute(code_files[0]),
                    timeout=self.config.frame_timeout or 30.0
                )
            else:
                # No files to process
                frame_result = FrameResult(
                    frame_id=frame.frame_id,
                    frame_name=frame.name,
                    status="skipped",
                    duration=0.0,
                    issues_found=0,
                    is_blocker=False,
                    findings=[],
                )

            pipeline.frames_executed += 1
            if hasattr(frame_result, 'has_critical_issues') and frame_result.has_critical_issues:
                pipeline.frames_failed += 1
            else:
                pipeline.frames_passed += 1

            logger.info("frame_executed_successfully",
                       frame_id=frame.frame_id,
                       findings=len(frame_result.findings) if hasattr(frame_result, 'findings') else 0)

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

        # Execute POST rules
        post_violations = []
        if frame_rules and frame_rules.post_rules:
            post_violations = await self._execute_rules(frame_rules.post_rules, code_files)

            if post_violations and self._has_blocker_violations(post_violations):
                if frame_rules.on_fail == "stop":
                    logger.error("post_rules_failed_stopping", frame_id=frame.frame_id)

        # Store frame result with violations
        if not hasattr(context, 'frame_results'):
            context.frame_results = {}

        context.frame_results[frame.frame_id] = {
            'result': frame_result,
            'pre_violations': pre_violations,
            'post_violations': post_violations,
        }

        if self.progress_callback:
            self.progress_callback("frame_completed", {
                "frame_id": frame.frame_id,
                "findings": len(frame_result.findings) if hasattr(frame_result, 'findings') else 0,
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

    def _store_validation_results(self, context: PipelineContext, pipeline: ValidationPipeline) -> None:
        """Store validation results in context."""
        if not hasattr(context, 'frame_results'):
            # Initialize empty results if no frame results
            context.findings = []
            context.validated_issues = []
            return

        # Aggregate findings from all frames
        all_findings = []
        for frame_id, frame_data in context.frame_results.items():
            frame_result = frame_data.get('result')
            if frame_result and hasattr(frame_result, 'findings'):
                all_findings.extend(frame_result.findings)

        context.findings = all_findings

        # Ensure validated_issues is always set, even if empty
        validated_issues = []
        for finding in all_findings:
            # Convert finding to dict if it has to_dict method
            finding_dict = finding.to_dict() if hasattr(finding, 'to_dict') else finding

            # Check if it's a false positive
            if not self._is_false_positive(
                finding_dict,
                getattr(context, 'suppression_rules', [])
            ):
                validated_issues.append(finding_dict)

        context.validated_issues = validated_issues

        # Add phase result
        context.add_phase_result("VALIDATION", {
            "total_findings": len(all_findings),
            "validated_issues": len(context.validated_issues),
            "frames_executed": pipeline.frames_executed,
            "frames_passed": pipeline.frames_passed,
            "frames_failed": pipeline.frames_failed,
        })

    def _is_false_positive(
        self,
        finding: Dict[str, Any],
        suppression_rules: List[Dict[str, Any]],
    ) -> bool:
        """Check if a finding is a false positive based on suppression rules."""
        if not suppression_rules:
            return False

        for rule in suppression_rules:
            # Handle both dict and string rules
            if isinstance(rule, dict):
                if (
                    rule.get("issue_type") == finding.get("type") and
                    rule.get("file_context") == finding.get("file_context")
                ):
                    return True
            elif isinstance(rule, str):
                # Simple string rule matching
                if finding.get("type") == rule or finding.get("message", "").find(rule) != -1:
                    return True
        return False