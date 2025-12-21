"""
Pipeline orchestrator.

Core execution engine for validation pipelines.
"""

import asyncio
import time
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime

from warden.pipeline.domain.models import (
    ValidationPipeline,
    PipelineConfig,
    PipelineResult,
    FrameExecution,
    FrameRules,
)
from warden.pipeline.domain.enums import PipelineStatus, ExecutionStrategy
from warden.validation.domain.frame import ValidationFrame, FrameResult, CodeFile
from warden.rules.application.rule_validator import CustomRuleValidator
from warden.rules.domain.models import CustomRule, CustomRuleViolation
from warden.shared.infrastructure.logging import get_logger
from warden.shared.infrastructure.exceptions import ValidationError

logger = get_logger(__name__)


class PipelineOrchestrator:
    """
    Orchestrates validation pipeline execution.

    Responsibilities:
    - Frame dependency resolution
    - Sequential/parallel execution
    - Timeout management
    - Result aggregation
    - Error handling
    """

    def __init__(
        self,
        frames: List[ValidationFrame],
        config: Optional[PipelineConfig] = None,
        progress_callback: Optional[callable] = None,
    ) -> None:
        """
        Initialize orchestrator.

        Args:
            frames: List of validation frames to execute
            config: Pipeline configuration
            progress_callback: Optional callback for progress updates
                               Signature: callback(event: str, data: dict)
        """
        self.frames = frames
        self.config = config or PipelineConfig()
        self.progress_callback = progress_callback

        # Initialize custom rule validator
        self.rule_validator = CustomRuleValidator(self.config.global_rules)

        # Sort frames by priority (CRITICAL first)
        self._sort_frames_by_priority()

        logger.info(
            "orchestrator_initialized",
            frame_count=len(frames),
            strategy=self.config.strategy.value,
            global_rules_count=len(self.config.global_rules),
            frame_rules_count=len(self.config.frame_rules),
        )

    def _sort_frames_by_priority(self) -> None:
        """Sort frames by priority (CRITICAL → HIGH → MEDIUM → LOW)."""
        # Priority is now IntEnum: CRITICAL=1, HIGH=2, MEDIUM=3, LOW=4, INFORMATIONAL=5
        # Lower values = higher priority, so we can sort directly by value
        self.frames.sort(key=lambda f: f.priority.value)

    async def execute(self, code_files: List[CodeFile]) -> PipelineResult:
        """
        Execute validation pipeline on code files.

        Args:
            code_files: List of code files to validate

        Returns:
            PipelineResult with aggregated findings

        Raises:
            ValidationError: If pipeline execution fails
        """
        # Create pipeline entity
        pipeline = ValidationPipeline(
            name="Code Validation",
            config=self.config,
            total_frames=len(self.frames),
        )

        # Initialize frame executions
        pipeline.frame_executions = [
            FrameExecution(
                frame_id=frame.frame_id,
                frame_name=frame.name,
                status="pending",
            )
            for frame in self.frames
        ]

        # Start pipeline
        pipeline.start()

        logger.info(
            "pipeline_started",
            pipeline_id=pipeline.id,
            frame_count=len(self.frames),
            file_count=len(code_files),
        )

        # Notify callback
        if self.progress_callback:
            self.progress_callback("pipeline_started", {
                "total_frames": len(self.frames),
                "total_files": len(code_files),
            })

        try:
            # Execute based on strategy
            if self.config.strategy == ExecutionStrategy.SEQUENTIAL:
                await self._execute_sequential(pipeline, code_files)
            elif self.config.strategy == ExecutionStrategy.PARALLEL:
                await self._execute_parallel(pipeline, code_files)
            elif self.config.strategy == ExecutionStrategy.FAIL_FAST:
                await self._execute_fail_fast(pipeline, code_files)

            # Mark as completed if no failures
            if pipeline.frames_failed == 0:
                pipeline.complete()
            else:
                pipeline.fail()

        except Exception as e:
            logger.error(
                "pipeline_execution_failed",
                pipeline_id=pipeline.id,
                error=str(e),
            )
            pipeline.fail()
            raise ValidationError(f"Pipeline execution failed: {e}") from e

        # Build result
        result = self._build_result(pipeline)

        logger.info(
            "pipeline_completed",
            pipeline_id=pipeline.id,
            status=pipeline.status.value,
            duration=pipeline.duration,
            total_findings=result.total_findings,
        )

        return result

    async def _execute_sequential(
        self,
        pipeline: ValidationPipeline,
        code_files: List[CodeFile],
    ) -> None:
        """Execute frames sequentially (one at a time)."""
        for idx, frame in enumerate(self.frames):
            frame_exec = pipeline.frame_executions[idx]

            # Check if should skip (fail_fast + blocker failed)
            if self.config.fail_fast and pipeline.frames_failed > 0:
                if self._has_blocker_failed(pipeline):
                    frame_exec.status = "skipped"
                    logger.info(
                        "frame_skipped",
                        frame=frame.name,
                        reason="blocker_failed",
                    )
                    continue

            # Execute frame
            await self._execute_frame(pipeline, frame, frame_exec, code_files)

    async def _execute_parallel(
        self,
        pipeline: ValidationPipeline,
        code_files: List[CodeFile],
    ) -> None:
        """Execute frames in parallel (with concurrency limit)."""
        semaphore = asyncio.Semaphore(self.config.parallel_limit)

        async def execute_with_semaphore(
            frame: ValidationFrame,
            frame_exec: FrameExecution,
        ) -> None:
            async with semaphore:
                await self._execute_frame(pipeline, frame, frame_exec, code_files)

        # Create tasks for all frames
        tasks = [
            execute_with_semaphore(frame, pipeline.frame_executions[idx])
            for idx, frame in enumerate(self.frames)
        ]

        # Execute all frames concurrently
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _execute_fail_fast(
        self,
        pipeline: ValidationPipeline,
        code_files: List[CodeFile],
    ) -> None:
        """Execute frames sequentially, stop on first blocker failure."""
        for idx, frame in enumerate(self.frames):
            frame_exec = pipeline.frame_executions[idx]

            # Execute frame
            await self._execute_frame(pipeline, frame, frame_exec, code_files)

            # Stop if blocker frame failed (check result.status, not exec status)
            if frame.is_blocker and frame_exec.result and frame_exec.result.status == "failed":
                logger.info(
                    "pipeline_stopped",
                    frame=frame.name,
                    reason="blocker_failed",
                )

                # Mark remaining frames as skipped
                for remaining_idx in range(idx + 1, len(self.frames)):
                    pipeline.frame_executions[remaining_idx].status = "skipped"

                break

    async def _execute_frame(
        self,
        pipeline: ValidationPipeline,
        frame: ValidationFrame,
        frame_exec: FrameExecution,
        code_files: List[CodeFile],
    ) -> None:
        """Execute a single frame on all code files with PRE/POST rules."""
        frame_exec.status = "running"
        frame_exec.started_at = datetime.utcnow()

        logger.info(
            "frame_started",
            pipeline_id=pipeline.id,
            frame=frame.name,
        )

        # Notify callback that frame started
        if self.progress_callback:
            self.progress_callback("frame_started", {
                "frame_name": frame.name,
                "frame_id": frame.frame_id,
            })

        try:
            # Get frame-specific rules
            frame_rules = self.config.frame_rules.get(frame.frame_id)

            # Execute frame on each code file
            all_findings = []
            all_pre_violations = []
            all_post_violations = []
            total_duration = 0.0
            blocker_found_in_pre = False
            blocker_found_in_post = False

            for code_file in code_files:
                try:
                    # 1. Execute PRE rules
                    pre_violations = []
                    if frame_rules and frame_rules.pre_rules:
                        logger.info(
                            "executing_pre_rules",
                            frame=frame.name,
                            file=code_file.path,
                            rule_count=len(frame_rules.pre_rules),
                        )
                        pre_violations = await self._execute_rules(
                            frame_rules.pre_rules,
                            code_file,
                        )
                        all_pre_violations.extend(pre_violations)
                        logger.info(
                            "pre_rules_completed",
                            frame=frame.name,
                            violations=len(pre_violations),
                        )

                        # Check if blocker violations found
                        if self._has_blocker_violations(pre_violations):
                            blocker_found_in_pre = True
                            if frame_rules.on_fail == "stop":
                                logger.warning(
                                    "pre_rule_blocker_found",
                                    frame=frame.name,
                                    file=code_file.path,
                                    violations=len(pre_violations),
                                )
                                # Don't execute frame, continue to next file
                                continue

                    # 2. Execute frame (if no blocker PRE rules or on_fail="continue")
                    result = await asyncio.wait_for(
                        frame.execute(code_file),
                        timeout=self.config.frame_timeout,
                    )

                    all_findings.extend(result.findings)
                    total_duration += result.duration

                    # 3. Execute POST rules
                    post_violations = []
                    if frame_rules and frame_rules.post_rules:
                        post_violations = await self._execute_rules(
                            frame_rules.post_rules,
                            code_file,
                        )
                        all_post_violations.extend(post_violations)

                        # Check POST blocker violations
                        if self._has_blocker_violations(post_violations):
                            blocker_found_in_post = True
                            if frame_rules.on_fail == "stop":
                                logger.warning(
                                    "post_rule_blocker_found",
                                    frame=frame.name,
                                    file=code_file.path,
                                    violations=len(post_violations),
                                )

                except asyncio.TimeoutError:
                    logger.error(
                        "frame_timeout",
                        frame=frame.name,
                        file=code_file.path,
                        timeout=self.config.frame_timeout,
                    )
                    frame_exec.error = f"Timeout after {self.config.frame_timeout}s"
                    frame_exec.status = "failed"
                    pipeline.frames_failed += 1
                    return

                except Exception as e:
                    logger.error(
                        "frame_execution_error",
                        frame=frame.name,
                        file=code_file.path,
                        error=str(e),
                    )
                    # Continue with other files
                    continue

            # Determine frame status (severity-aware)
            # Check if there are any blocker violations in PRE/POST rules
            has_blocker_violations = (
                blocker_found_in_pre or
                blocker_found_in_post or
                any(v.is_blocker for v in all_pre_violations + all_post_violations)
            )

            # No findings and no violations = passed
            if len(all_findings) == 0 and len(all_pre_violations) == 0 and len(all_post_violations) == 0:
                frame_status = "passed"
            # Blocker violations with on_fail="stop" = failed
            elif has_blocker_violations and frame_rules and frame_rules.on_fail == "stop":
                frame_status = "failed"
            # Blocker frame with findings = failed
            elif frame.is_blocker and len(all_findings) > 0:
                frame_status = "failed"
            # Any blocker violation (regardless of on_fail) = failed
            elif has_blocker_violations:
                frame_status = "failed"
            # Non-blocker with issues/violations = warning
            else:
                frame_status = "warning"

            # Create aggregated result
            frame_exec.result = FrameResult(
                frame_id=frame.frame_id,
                frame_name=frame.name,
                status=frame_status,
                duration=total_duration,
                issues_found=len(all_findings),
                is_blocker=frame.is_blocker,
                findings=all_findings,
                pre_rules=frame_rules.pre_rules if frame_rules else None,
                post_rules=frame_rules.post_rules if frame_rules else None,
                # None if no rules exist, [] if rules exist but no violations
                pre_rule_violations=(
                    all_pre_violations if (frame_rules and frame_rules.pre_rules) else None
                ),
                post_rule_violations=(
                    all_post_violations if (frame_rules and frame_rules.post_rules) else None
                ),
                metadata={"files_processed": len(code_files)},
            )

            # Update execution status
            frame_exec.status = "completed"
            frame_exec.completed_at = datetime.utcnow()
            frame_exec.duration = (
                frame_exec.completed_at - frame_exec.started_at
            ).total_seconds()

            # Update pipeline counters
            pipeline.frames_completed += 1

            # Count all issues: findings + violations
            total_violations = len(all_pre_violations) + len(all_post_violations)
            pipeline.total_issues += len(all_findings) + total_violations

            # Count blocker issues: blocker violations + blocker frame findings
            blocker_violations = [
                v for v in all_pre_violations + all_post_violations if v.is_blocker
            ]
            frame_blocker_issues = len(all_findings) if frame.is_blocker else 0
            pipeline.blocker_issues += frame_blocker_issues + len(blocker_violations)

            # Update frames_failed based on final status
            if frame_status == "failed":
                pipeline.frames_failed += 1

            logger.info(
                "frame_completed",
                pipeline_id=pipeline.id,
                frame=frame.name,
                status=frame_status,
                frame_exec_status=frame_exec.status,
                issues=len(all_findings),
                pre_violations=len(all_pre_violations),
                post_violations=len(all_post_violations),
                blocker_violations=len(blocker_violations),
                has_blocker_violations=has_blocker_violations,
                duration=frame_exec.duration,
            )

            # Notify callback
            if self.progress_callback:
                # Map internal status to Panel-compatible status
                panel_status = self._map_frame_status_for_panel(frame_status)

                self.progress_callback("frame_completed", {
                    "frame_name": frame.name,
                    "frame_status": panel_status,  # Panel-compatible: 'completed'|'failed'|'skipped'
                    "internal_status": frame_status,  # Internal: 'passed'|'warning'|'failed' (for debugging)
                    "has_warnings": frame_status == "warning",  # Flag for non-blocker issues
                    "frame_exec_status": frame_exec.status,  # Execution status (completed)
                    "issues_found": len(all_findings),
                    "pre_violations": len(all_pre_violations),
                    "post_violations": len(all_post_violations),
                    "blocker_violations": len(blocker_violations),
                    "frames_completed": pipeline.frames_completed,
                    "total_frames": pipeline.total_frames,
                    "duration": frame_exec.duration,
                })

                # Yield control to event loop to allow UI updates
                await asyncio.sleep(0)

        except Exception as e:
            logger.error(
                "frame_execution_failed",
                pipeline_id=pipeline.id,
                frame=frame.name,
                error=str(e),
            )
            frame_exec.status = "failed"
            frame_exec.error = str(e)
            frame_exec.completed_at = datetime.utcnow()
            pipeline.frames_failed += 1

    async def _execute_rules(
        self,
        rules: List[CustomRule],
        code_file: CodeFile,
    ) -> List[CustomRuleViolation]:
        """
        Execute custom rules on a code file.

        Args:
            rules: List of custom rules to execute
            code_file: Code file to validate

        Returns:
            List of rule violations found
        """
        violations = []
        file_path = Path(code_file.path)

        if not file_path.exists():
            logger.warning(
                "rule_validation_skipped",
                file=code_file.path,
                reason="file_not_found",
            )
            return violations

        # Create temporary validator for these specific rules
        temp_validator = CustomRuleValidator(rules)

        try:
            violations = await temp_validator.validate_file(file_path)
        except Exception as e:
            logger.error(
                "rule_validation_error",
                file=code_file.path,
                error=str(e),
            )

        return violations

    def _has_blocker_violations(self, violations: List[CustomRuleViolation]) -> bool:
        """
        Check if any violation is a blocker.

        Args:
            violations: List of rule violations

        Returns:
            True if any violation is a blocker, False otherwise
        """
        return any(v.is_blocker for v in violations)

    def _map_frame_status_for_panel(self, frame_status: str) -> str:
        """
        Convert internal frame status to Panel-compatible SubStep status.

        Panel expects StepStatus: 'pending'|'running'|'completed'|'failed'|'skipped'
        Internal frame status: 'failed'|'passed'|'warning'

        Mapping:
        - 'failed' → 'failed' (blocker issues or blocker violations)
        - 'passed' → 'completed' (no issues, successfully completed)
        - 'warning' → 'completed' (non-blocker issues, completed with warnings)

        Args:
            frame_status: Internal frame status

        Returns:
            Panel-compatible status string
        """
        mapping = {
            "failed": "failed",
            "passed": "completed",
            "warning": "completed",
        }
        return mapping.get(frame_status, "completed")

    def _has_blocker_failed(self, pipeline: ValidationPipeline) -> bool:
        """Check if any blocker frame has failed."""
        for idx, frame in enumerate(self.frames):
            frame_exec = pipeline.frame_executions[idx]
            # Check result.status (failed/passed/warning), not exec status (pending/running/completed)
            if frame.is_blocker and frame_exec.result and frame_exec.result.status == "failed":
                return True
        return False

    def _build_result(self, pipeline: ValidationPipeline) -> PipelineResult:
        """Build aggregated pipeline result."""
        # Collect all frame results
        frame_results = [
            fe.result for fe in pipeline.frame_executions if fe.result is not None
        ]

        # Count findings by severity
        critical_count = 0
        high_count = 0
        medium_count = 0
        low_count = 0

        for fr in frame_results:
            for finding in fr.findings:
                if finding.severity == "critical":
                    critical_count += 1
                elif finding.severity == "high":
                    high_count += 1
                elif finding.severity == "medium":
                    medium_count += 1
                elif finding.severity == "low":
                    low_count += 1

        # Count skipped frames
        skipped_count = sum(
            1 for fe in pipeline.frame_executions if fe.status == "skipped"
        )

        return PipelineResult(
            pipeline_id=pipeline.id,
            pipeline_name=pipeline.name,
            status=pipeline.status,
            duration=pipeline.duration,
            total_frames=pipeline.total_frames,
            frames_passed=pipeline.frames_completed - pipeline.frames_failed,
            frames_failed=pipeline.frames_failed,
            frames_skipped=skipped_count,
            total_findings=pipeline.total_issues,
            critical_findings=critical_count,
            high_findings=high_count,
            medium_findings=medium_count,
            low_findings=low_count,
            frame_results=frame_results,
            metadata={
                "strategy": self.config.strategy.value,
                "fail_fast": self.config.fail_fast,
                "frame_executions": [fe.to_json() for fe in pipeline.frame_executions],
            },
        )
