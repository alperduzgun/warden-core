"""
Frame executor - parallel validation engine.

Executes multiple validation frames concurrently using asyncio.gather().
Features:
- Priority-based execution groups
- Timeout protection (5 min per frame)
- Error handling per frame
- Blocker detection
"""
import asyncio
import time
import logging
from typing import List, Dict, Any, Optional

from warden.core.validation.frame import BaseValidationFrame, FrameResult
from warden.models.frame import get_frame_by_id, get_execution_groups

# Fallback logger (structlog not installed yet)
try:
    import structlog
    logger = structlog.get_logger()
except ImportError:
    from warden.shared.logger import get_logger
    logger = get_logger(__name__)


class FrameExecutor:
    """
    Parallel frame execution engine.

    Executes validation frames concurrently with priority-based grouping.
    """

    def __init__(self, frames: Optional[List[BaseValidationFrame]] = None):
        """
        Initialize frame executor.

        Args:
            frames: List of frame instances to execute (auto-loads all if None)
        """
        if frames is None:
            # Auto-register all available frames
            from warden.core.validation.frames import (
                SecurityFrame,
                ChaosEngineeringFrame,
                FuzzTestingFrame,
                PropertyTestingFrame,
                ArchitecturalConsistencyFrame,
                StressTestingFrame,
            )
            self.frames = [
                SecurityFrame(),
                ChaosEngineeringFrame(),
                FuzzTestingFrame(),
                PropertyTestingFrame(),
                ArchitecturalConsistencyFrame(),
                StressTestingFrame(),
            ]
        else:
            self.frames = frames

        self.logger = logger
        self._cache: Dict[str, FrameResult] = {}

    def register_frame(self, frame: BaseValidationFrame) -> None:
        """Register a validation frame."""
        self.frames.append(frame)

    def register_frames(self, frames: List[BaseValidationFrame]) -> None:
        """Register multiple validation frames."""
        self.frames.extend(frames)

    async def execute(
        self,
        file_path: str,
        file_content: str,
        language: str,
        recommended_frames: List[str],
        characteristics: Dict[str, Any],
        correlation_id: str = "",
        parallel: bool = True,
    ) -> Dict[str, Any]:
        """
        Execute validation frames.

        Args:
            file_path: Path to code file
            file_content: File content
            language: Programming language
            recommended_frames: Frame IDs to execute
            characteristics: Code characteristics
            correlation_id: Correlation ID for tracking
            parallel: Execute frames in parallel groups

        Returns:
            Validation summary with frame results
        """
        start_time = time.perf_counter()

        self.logger.info(
            "frame_execution_started",
            correlation_id=correlation_id,
            recommended_frames=recommended_frames,
            parallel=parallel,
        )

        # Filter frames based on recommendations
        frames_to_execute = self._filter_frames(recommended_frames)

        if not frames_to_execute:
            self.logger.warning(
                "no_frames_to_execute",
                correlation_id=correlation_id,
                recommended=recommended_frames,
            )
            return {
                "totalFrames": 0,
                "passedFrames": 0,
                "failedFrames": 0,
                "blockerFailures": [],
                "results": [],
                "durationMs": 0,
            }

        # Execute frames
        if parallel:
            results = await self._execute_parallel(
                frames_to_execute,
                file_path,
                file_content,
                language,
                characteristics,
                correlation_id,
            )
        else:
            results = await self._execute_sequential(
                frames_to_execute,
                file_path,
                file_content,
                language,
                characteristics,
                correlation_id,
            )

        # Calculate summary
        duration_ms = (time.perf_counter() - start_time) * 1000
        summary = self._create_summary(results, duration_ms, correlation_id)

        self.logger.info(
            "frame_execution_completed",
            correlation_id=correlation_id,
            total_frames=summary["totalFrames"],
            passed=summary["passedFrames"],
            failed=summary["failedFrames"],
            blocker_failures=len(summary["blockerFailures"]),
            duration_ms=duration_ms,
        )

        return summary

    async def _execute_parallel(
        self,
        frames: List[BaseValidationFrame],
        file_path: str,
        file_content: str,
        language: str,
        characteristics: Dict[str, Any],
        correlation_id: str,
    ) -> List[FrameResult]:
        """Execute frames in parallel groups (by priority)."""
        # Get priority groups from frame.py
        frame_definitions = [get_frame_by_id(f.name.lower()) for f in frames]
        frame_definitions = [f for f in frame_definitions if f]

        if not frame_definitions:
            # Fallback: execute all in parallel
            tasks = [
                self._execute_single_frame(
                    frame, file_path, file_content, language, characteristics, correlation_id
                )
                for frame in frames
            ]
            return await asyncio.gather(*tasks)

        # Group by priority
        execution_groups = get_execution_groups(frame_definitions)

        self.logger.info(
            "parallel_execution_groups",
            correlation_id=correlation_id,
            group_count=len(execution_groups),
        )

        all_results = []

        for group_idx, group in enumerate(execution_groups):
            group_start = time.perf_counter()

            # Find frame instances for this group
            group_frames = [
                f for f in frames
                if any(frame_def.id in f.name.lower() for frame_def in group)
            ]

            if not group_frames:
                continue

            self.logger.info(
                "executing_priority_group",
                correlation_id=correlation_id,
                group_index=group_idx,
                frame_count=len(group_frames),
                priority=group[0].priority if group else "unknown",
            )

            # Execute group in parallel
            tasks = [
                self._execute_single_frame(
                    frame, file_path, file_content, language, characteristics, correlation_id
                )
                for frame in group_frames
            ]
            group_results = await asyncio.gather(*tasks)
            all_results.extend(group_results)

            group_duration = (time.perf_counter() - group_start) * 1000

            self.logger.info(
                "priority_group_completed",
                correlation_id=correlation_id,
                group_index=group_idx,
                duration_ms=group_duration,
            )

        return all_results

    async def _execute_sequential(
        self,
        frames: List[BaseValidationFrame],
        file_path: str,
        file_content: str,
        language: str,
        characteristics: Dict[str, Any],
        correlation_id: str,
    ) -> List[FrameResult]:
        """Execute frames sequentially (one by one)."""
        results = []

        for frame in frames:
            result = await self._execute_single_frame(
                frame, file_path, file_content, language, characteristics, correlation_id
            )
            results.append(result)

            # Stop on blocker failure
            if result.is_blocker and not result.passed:
                self.logger.warning(
                    "blocker_failure_stopping",
                    correlation_id=correlation_id,
                    frame=frame.name,
                )
                break

        return results

    async def _execute_single_frame(
        self,
        frame: BaseValidationFrame,
        file_path: str,
        file_content: str,
        language: str,
        characteristics: Dict[str, Any],
        correlation_id: str,
        timeout: int = 300,
    ) -> FrameResult:
        """
        Execute a single frame with timeout protection.

        Args:
            frame: Frame to execute
            file_path: File path
            file_content: File content
            language: Programming language
            characteristics: Code characteristics
            correlation_id: Correlation ID
            timeout: Timeout in seconds (default 5 minutes)

        Returns:
            FrameResult
        """
        frame_start = time.perf_counter()

        self.logger.info(
            "frame_started",
            correlation_id=correlation_id,
            frame=frame.name,
            priority=frame.priority,
        )

        try:
            # Execute with timeout
            result = await asyncio.wait_for(
                frame.execute(
                    file_path=file_path,
                    file_content=file_content,
                    language=language,
                    characteristics=characteristics,
                    correlation_id=correlation_id,
                ),
                timeout=timeout,
            )

            duration_ms = (time.perf_counter() - frame_start) * 1000

            self.logger.info(
                "frame_completed",
                correlation_id=correlation_id,
                frame=frame.name,
                passed=result.passed,
                duration_ms=duration_ms,
            )

            return result

        except asyncio.TimeoutError:
            duration_ms = (time.perf_counter() - frame_start) * 1000

            self.logger.error(
                "frame_timeout",
                correlation_id=correlation_id,
                frame=frame.name,
                timeout_seconds=timeout,
                duration_ms=duration_ms,
            )

            return FrameResult(
                name=frame.name,
                passed=False,
                execution_time_ms=duration_ms,
                priority=frame.priority,
                scope=frame.scope.value,
                error_message=f"Frame execution timed out after {timeout}s",
                is_blocker=frame.is_blocker,
            )

        except Exception as ex:
            duration_ms = (time.perf_counter() - frame_start) * 1000

            self.logger.error(
                "frame_failed",
                correlation_id=correlation_id,
                frame=frame.name,
                error=str(ex),
                error_type=type(ex).__name__,
                duration_ms=duration_ms,
            )

            return FrameResult(
                name=frame.name,
                passed=False,
                execution_time_ms=duration_ms,
                priority=frame.priority,
                scope=frame.scope.value,
                error_message=str(ex),
                is_blocker=frame.is_blocker,
            )

    def _filter_frames(
        self, recommended_frame_ids: List[str]
    ) -> List[BaseValidationFrame]:
        """Filter registered frames based on recommendations."""
        if not recommended_frame_ids:
            return self.frames

        return [
            frame
            for frame in self.frames
            if any(frame_id in frame.name.lower() for frame_id in recommended_frame_ids)
        ]

    def _create_summary(
        self, results: List[FrameResult], duration_ms: float, correlation_id: str
    ) -> Dict[str, Any]:
        """Create validation summary from frame results."""
        total_frames = len(results)
        passed_frames = sum(1 for r in results if r.passed)
        failed_frames = total_frames - passed_frames

        # Find blocker failures
        blocker_failures = [
            r.name for r in results if r.is_blocker and not r.passed
        ]

        return {
            "totalFrames": total_frames,
            "passedFrames": passed_frames,
            "failedFrames": failed_frames,
            "blockerFailures": blocker_failures,
            "results": [r.to_json() for r in results],
            "durationMs": duration_ms,
        }
