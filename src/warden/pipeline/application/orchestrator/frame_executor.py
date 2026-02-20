"""
Frame executor for validation frames.

Handles frame execution strategies and validation orchestration.
"""

import asyncio
import time
from collections.abc import Callable
from typing import Any

from warden.pipeline.domain.enums import ExecutionStrategy
from warden.pipeline.domain.models import (
    FrameResult,
    PipelineConfig,
    ValidationPipeline,
)
from warden.pipeline.domain.pipeline_context import PipelineContext
from warden.rules.application.rule_validator import CustomRuleValidator
from warden.shared.infrastructure.logging import get_logger
from warden.validation.domain.frame import CodeFile, ValidationFrame

from .ast_pre_parser import ASTPreParser
from .file_filter import FileFilter
from .frame_matcher import FrameMatcher
from .frame_runner import FrameRunner
from .result_aggregator import ResultAggregator
from .rule_executor import RuleExecutor
from .rust_pre_filter import RustPreFilter

logger = get_logger(__name__)


class FrameExecutor:
    """Executes validation frames with various strategies."""

    def __init__(
        self,
        frames: list[ValidationFrame] | None = None,
        config: PipelineConfig | None = None,
        progress_callback: Callable | None = None,
        rule_validator: CustomRuleValidator | None = None,
        llm_service: Any | None = None,
        available_frames: list[ValidationFrame] | None = None,
        semantic_search_service: Any | None = None,
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

        self.frame_matcher = FrameMatcher(frames, available_frames=self.available_frames)
        self.result_aggregator = ResultAggregator()
        self.rust_pre_filter = RustPreFilter(config=self.config, rule_validator=rule_validator)
        self.rule_executor = RuleExecutor(rule_validator=rule_validator)
        self.frame_runner = FrameRunner(
            config=self.config,
            progress_callback=progress_callback,
            rule_executor=self.rule_executor,
            llm_service=llm_service,
            semantic_search_service=semantic_search_service,
        )

    async def execute_validation_with_strategy_async(
        self,
        context: PipelineContext,
        code_files: list[CodeFile],
        pipeline: ValidationPipeline,
    ) -> None:
        """Execute VALIDATION phase with execution strategies."""
        start_time = time.perf_counter()
        logger.info("executing_phase", phase="VALIDATION")

        try:
            file_contexts = context.file_contexts or {}
            include_test_files = getattr(self.config, "include_test_files", False)
            filtered_files = FileFilter.filter_by_context(code_files, file_contexts, include_test_files)

            logger.info(
                "validation_file_filtering",
                total_files=len(code_files),
                filtered_files=len(filtered_files),
                filtered_out=len(code_files) - len(filtered_files),
            )

            selected_frames = getattr(context, "selected_frames", None)
            frames_to_execute = self.frame_matcher.get_frames_to_execute(selected_frames)

            # Emit phase_started with accurate total (frames * filtered_files + rules files)
            rules_file_count = len(filtered_files) if self.rule_validator and self.rule_validator.rules else 0
            frame_units = len(frames_to_execute) * len(filtered_files) if frames_to_execute else 0
            validation_total = frame_units + rules_file_count
            if self.progress_callback:
                self.progress_callback(
                    "phase_started",
                    {"phase": "Validation", "phase_name": "Validation", "total_units": max(validation_total, 1)},
                )

            if not frames_to_execute:
                logger.warning(
                    "no_frames_to_execute",
                    selected_frames=getattr(context, "selected_frames", None),
                    configured_frames=len(self.frames),
                )
                context.findings = []
                context.validated_issues = []
                context.add_phase_result(
                    "VALIDATION",
                    {
                        "total_findings": 0,
                        "validated_issues": 0,
                        "frames_executed": 0,
                        "frames_passed": 0,
                        "frames_failed": 0,
                        "no_frames_reason": "no_frames_selected",
                    },
                )

            if not hasattr(context, "frame_results") or context.frame_results is None:
                context.frame_results = {}

            # Pre-parse ASTs for all files (centralized cache)
            ast_pre_parser = ASTPreParser()
            await ast_pre_parser.pre_parse_all_async(context, filtered_files)

            await self.rust_pre_filter.run_async(context, filtered_files)

            if frames_to_execute:
                if self.config.strategy == ExecutionStrategy.SEQUENTIAL:
                    await self._execute_frames_sequential_async(context, filtered_files, frames_to_execute, pipeline)
                elif self.config.strategy == ExecutionStrategy.PARALLEL:
                    await self._execute_frames_parallel_async(context, filtered_files, frames_to_execute, pipeline)
                elif self.config.strategy == ExecutionStrategy.FAIL_FAST:
                    await self._execute_frames_fail_fast_async(context, filtered_files, frames_to_execute, pipeline)
                elif self.config.strategy == ExecutionStrategy.PIPELINE:
                    await self._execute_frames_pipeline_async(context, filtered_files, frames_to_execute, pipeline)
                else:
                    await self._execute_frames_sequential_async(context, filtered_files, frames_to_execute, pipeline)

            if self.rule_validator and self.rule_validator.rules:
                logger.info("executing_global_rules", rule_count=len(self.rule_validator.rules))
                if self.progress_callback:
                    self.progress_callback(
                        "progress_update",
                        {"phase": "Validating Rules", "increment": 0},
                    )
                global_violations = []
                for code_file in filtered_files:
                    file_violations = await self.rule_validator.validate_file_async(code_file.path)
                    global_violations.extend(file_violations)
                    if self.progress_callback:
                        self.progress_callback("progress_update", {"increment": 1})

                if global_violations:
                    logger.info("global_rules_found_violations", count=len(global_violations))

                    frame_id = "global_script_rules"
                    frame_result = FrameResult(
                        frame_id=frame_id,
                        frame_name="Global Script Rules",
                        status="failed",
                        duration=0.5,
                        issues_found=len(global_violations),
                        is_blocker=any(v.is_blocker for v in global_violations),
                        findings=[RuleExecutor.convert_to_finding(v) for v in global_violations],
                        metadata={"engine": "python_rules"},
                    )

                    if not hasattr(context, "frame_results") or context.frame_results is None:
                        context.frame_results = {}

                    context.frame_results[frame_id] = {
                        "result": frame_result,
                        "pre_violations": [],
                        "post_violations": [],
                    }

            logger.info("debug_frame_results_before_aggregation", frames=list(context.frame_results.keys()))
            self.result_aggregator.store_validation_results(context, pipeline)

            logger.info(
                "phase_completed",
                phase="VALIDATION",
                findings=len(context.findings) if hasattr(context, "findings") else 0,
            )

        except Exception as e:
            logger.error("phase_failed", phase="VALIDATION", error=str(e))
            context.errors.append(f"VALIDATION failed: {e!s}")

        if self.progress_callback:
            duration = time.perf_counter() - start_time
            self.progress_callback(
                "phase_completed",
                {
                    "phase": "VALIDATION",
                    "phase_name": "VALIDATION",
                    "duration": duration,
                    "llm_used": self.llm_service is not None,
                },
            )

    async def _execute_frames_sequential_async(
        self,
        context: PipelineContext,
        code_files: list[CodeFile],
        frames_to_execute: list[ValidationFrame],
        pipeline: ValidationPipeline,
    ) -> None:
        """Execute frames sequentially."""
        logger.info("executing_frames_sequential", count=len(frames_to_execute))

        for frame in frames_to_execute:
            if self.config.fail_fast and pipeline.frames_failed > 0:
                logger.info("skipping_frame_fail_fast", frame_id=frame.frame_id)
                continue

            await self.frame_runner.execute_frame_with_rules_async(context, frame, code_files, pipeline)

    async def _execute_frames_parallel_async(
        self,
        context: PipelineContext,
        code_files: list[CodeFile],
        frames_to_execute: list[ValidationFrame],
        pipeline: ValidationPipeline,
    ) -> None:
        """Execute frames in parallel with concurrency limit."""
        logger.info("executing_frames_parallel", count=len(frames_to_execute))

        semaphore = asyncio.Semaphore(self.config.parallel_limit or 3)

        async def execute_with_semaphore_async(frame):
            async with semaphore:
                await self.frame_runner.execute_frame_with_rules_async(context, frame, code_files, pipeline)

        tasks = [execute_with_semaphore_async(frame) for frame in frames_to_execute]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _execute_frames_fail_fast_async(
        self,
        context: PipelineContext,
        code_files: list[CodeFile],
        frames_to_execute: list[ValidationFrame],
        pipeline: ValidationPipeline,
    ) -> None:
        """Execute frames sequentially, stop on first blocker failure."""
        logger.info("executing_frames_fail_fast", count=len(frames_to_execute))

        for frame in frames_to_execute:
            result = await self.frame_runner.execute_frame_with_rules_async(context, frame, code_files, pipeline)

            if result and hasattr(result, "has_blocker_issues") and result.has_blocker_issues:
                logger.info("stopping_on_blocker", frame_id=frame.frame_id)
                break

    async def _execute_frames_pipeline_async(
        self,
        context: PipelineContext,
        code_files: list[CodeFile],
        frames_to_execute: list[ValidationFrame],
        pipeline: ValidationPipeline,
    ) -> None:
        """
        Execute frames with dependency-aware PIPELINE strategy.

        Uses asyncio.wait(FIRST_COMPLETED) to maximize throughput while
        respecting frame dependencies. Frames with met dependencies execute
        in parallel up to parallel_limit.
        """
        logger.info("executing_frames_pipeline", count=len(frames_to_execute))

        # Build dependency graph from frame metadata
        frame_map = {f.frame_id: f for f in frames_to_execute}
        completed: set[str] = set()
        pending: set[str] = {f.frame_id for f in frames_to_execute}
        running: dict[str, asyncio.Task] = {}

        parallel_limit = self.config.parallel_limit or 4

        def _dependencies_met(frame: ValidationFrame) -> bool:
            """Check if all required frames have completed."""
            requires = getattr(frame, "requires_frames", [])
            return all(dep in completed for dep in requires)

        while pending or running:
            # Find ready frames (dependencies met, not running)
            ready = [fid for fid in pending if fid in frame_map and _dependencies_met(frame_map[fid])]

            # Launch ready frames up to parallel limit
            available_slots = parallel_limit - len(running)
            for fid in ready[:available_slots]:
                frame = frame_map[fid]
                pending.discard(fid)

                task = asyncio.create_task(
                    self.frame_runner.execute_frame_with_rules_async(context, frame, code_files, pipeline),
                    name=f"frame-{fid}",
                )
                running[fid] = task
                logger.debug("pipeline_frame_launched", frame_id=fid)

            if not running:
                if pending:
                    # Deadlock: pending frames but none can run
                    logger.error("pipeline_deadlock_detected", pending=list(pending), completed=list(completed))
                    # Fail-fast: skip remaining frames
                    for fid in pending:
                        logger.warning("pipeline_frame_skipped_deadlock", frame_id=fid)
                    break
                else:
                    break

            # Wait for first completion
            done, _ = await asyncio.wait(
                running.values(), return_when=asyncio.FIRST_COMPLETED, timeout=self.config.frame_timeout
            )

            if not done:
                # Timeout -- cancel all running
                logger.warning("pipeline_timeout", running=list(running.keys()))
                for task in running.values():
                    task.cancel()
                break

            # Process completed tasks
            for task in done:
                # Find which frame this task belongs to
                finished_fid = None
                for fid, t in running.items():
                    if t is task:
                        finished_fid = fid
                        break

                if finished_fid:
                    del running[finished_fid]
                    completed.add(finished_fid)

                    try:
                        result = task.result()
                        logger.debug(
                            "pipeline_frame_completed",
                            frame_id=finished_fid,
                            status=getattr(result, "status", "unknown"),
                        )
                    except Exception as e:
                        logger.error("pipeline_frame_failed", frame_id=finished_fid, error=str(e))

        logger.info("pipeline_execution_complete", completed=len(completed), total=len(frames_to_execute))
