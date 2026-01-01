"""
Main Phase Orchestrator for 6-phase pipeline.

Coordinates execution of all pipeline phases with shared PipelineContext.
"""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable
from uuid import uuid4

from warden.pipeline.domain.pipeline_context import PipelineContext
from warden.pipeline.domain.models import (
    PipelineResult,
    ValidationPipeline,
    PipelineConfig,
)
from warden.pipeline.domain.enums import PipelineStatus
from warden.rules.application.rule_validator import CustomRuleValidator
from warden.validation.domain.frame import CodeFile, ValidationFrame
from warden.shared.infrastructure.logging import get_logger

from .phase_executor import PhaseExecutor
from .frame_executor import FrameExecutor

logger = get_logger(__name__)


class PhaseOrchestrator:
    """
    Orchestrates the complete 6-phase validation pipeline.

    Phases:
    0. PRE-ANALYSIS: Project/file understanding
    1. ANALYSIS: Quality metrics calculation
    2. CLASSIFICATION: Frame selection & suppression
    3. VALIDATION: Execute validation frames
    4. FORTIFICATION: Generate security fixes
    5. CLEANING: Suggest quality improvements
    """

    def __init__(
        self,
        frames: Optional[List[ValidationFrame]] = None,
        config: Optional[PipelineConfig] = None,
        progress_callback: Optional[Callable] = None,
        project_root: Optional[Path] = None,
        llm_service: Optional[Any] = None,
    ):
        """
        Initialize phase orchestrator.

        Args:
            frames: List of validation frames to execute
            config: Pipeline configuration (can be dict or PipelineConfig)
            progress_callback: Optional callback for progress updates
            project_root: Root directory of the project
            llm_service: Optional LLM service for AI-powered phases
        """
        self.frames = frames or []

        # Handle both dict and PipelineConfig for backward compatibility
        if config is None:
            self.config = PipelineConfig()
        elif isinstance(config, dict):
            # Convert dict to PipelineConfig
            self.config = PipelineConfig()
            for key, value in config.items():
                setattr(self.config, key, value)
        else:
            self.config = config

        self._progress_callback = progress_callback
        self.project_root = project_root or Path.cwd()
        self.llm_service = llm_service

        # Initialize rule validator if global rules exist
        self.rule_validator = None
        if self.config.global_rules:
            self.rule_validator = CustomRuleValidator(self.config.global_rules)

        # Initialize phase executor
        self.phase_executor = PhaseExecutor(
            config=self.config,
            progress_callback=self.progress_callback,
            project_root=self.project_root,
            llm_service=self.llm_service,
        )

        # Initialize frame executor
        self.frame_executor = FrameExecutor(
            frames=self.frames,
            config=self.config,
            progress_callback=self.progress_callback,
            rule_validator=self.rule_validator,
            llm_service=self.llm_service,
        )

        # Sort frames by priority
        self._sort_frames_by_priority()

        logger.info(
            "phase_orchestrator_initialized",
            project_root=str(self.project_root),
            frame_count=len(self.frames),
            strategy=self.config.strategy.value if self.config.strategy else "sequential",
            frame_rules_count=len(self.config.frame_rules) if self.config.frame_rules else 0,
        )

    @property
    def progress_callback(self) -> Optional[Callable]:
        """Get progress callback."""
        return self._progress_callback

    @progress_callback.setter
    def progress_callback(self, value: Optional[Callable]) -> None:
        """Set progress callback and propagate to executors."""
        self._progress_callback = value
        if hasattr(self, 'phase_executor'):
            self.phase_executor.progress_callback = value
        if hasattr(self, 'frame_executor'):
            self.frame_executor.progress_callback = value

    def _sort_frames_by_priority(self) -> None:
        """Sort frames by priority value (lower value = higher priority)."""
        if self.frames:
            self.frames.sort(key=lambda f: f.priority.value if hasattr(f, 'priority') else 999)

    async def execute(
        self,
        code_files: List[CodeFile],
        frames_to_execute: Optional[List[str]] = None,
    ) -> tuple[PipelineResult, PipelineContext]:
        """
        Execute the complete 6-phase pipeline with shared context.
        Compatible with old orchestrator interface.

        Args:
            code_files: List of code files to process
            frames_to_execute: Optional list of frame IDs to execute (overrides classification)

        Returns:
            Tuple of (PipelineResult, PipelineContext)
        """
        context = await self.execute_pipeline_async(code_files, frames_to_execute)

        # Build PipelineResult from context for compatibility
        result = self._build_pipeline_result(context)

        return result, context

    async def execute_pipeline_async(
        self,
        code_files: List[CodeFile],
        frames_to_execute: Optional[List[str]] = None,
    ) -> PipelineContext:
        """
        Execute the complete 6-phase pipeline with shared context.

        Args:
            code_files: List of code files to process
            frames_to_execute: Optional list of frame IDs to execute (overrides classification)

        Returns:
            PipelineContext with results from results of all phases
        """
        # Initialize shared context
        context = PipelineContext(
            pipeline_id=str(uuid4()),
            started_at=datetime.now(),
            file_path=Path(code_files[0].path) if code_files else Path.cwd(),
            source_code=code_files[0].content if code_files else "",
            language="python",  # TODO: Detect from files
        )

        # Create pipeline entity
        self.pipeline = ValidationPipeline(
            id=context.pipeline_id,
            status=PipelineStatus.RUNNING,
            started_at=context.started_at,
        )

        logger.info(
            "pipeline_execution_started",
            pipeline_id=context.pipeline_id,
            file_count=len(code_files),
            frames_override=frames_to_execute,
        )

        if self.progress_callback:
            self.progress_callback("pipeline_started", {
                "pipeline_id": context.pipeline_id,
                "file_count": len(code_files),
            })

        try:
            # Phase 0: PRE-ANALYSIS
            if self.config.enable_pre_analysis:
                await self.phase_executor.execute_pre_analysis_async(context, code_files)

            # Phase 1: ANALYSIS
            if getattr(self.config, 'enable_analysis', True):
                await self.phase_executor.execute_analysis_async(context, code_files)

            # Phase 2: CLASSIFICATION
            # If frames override is provided, use it and skip AI classification
            if frames_to_execute:
                context.selected_frames = frames_to_execute
                context.classification_reasoning = "User manually selected frames via CLI"
                logger.info("using_frame_override", selected_frames=frames_to_execute)
                
                # Add phase result placeholder
                context.add_phase_result("CLASSIFICATION", {
                    "selected_frames": frames_to_execute,
                    "suppression_rules_count": 0,
                    "reasoning": "Manual override",
                    "skipped": True
                })
                
                if self.progress_callback:
                    self.progress_callback("phase_skipped", {
                        "phase": "CLASSIFICATION",
                        "reason": "manual_frame_override"
                    })
            else:
                # Classification is critical for intelligent frame selection
                logger.info("phase_enabled", phase="CLASSIFICATION", enabled=True, enforced=True)
                await self.phase_executor.execute_classification_async(context, code_files)

            # Phase 3: VALIDATION with execution strategies
            enable_validation = getattr(self.config, 'enable_validation', True)
            if enable_validation:
                logger.info("phase_enabled", phase="VALIDATION", enabled=enable_validation)
                # Pass pipeline reference to frame executor
                await self.frame_executor.execute_validation_with_strategy_async(
                    context, code_files, self.pipeline
                )
            else:
                logger.info("phase_skipped", phase="VALIDATION", reason="disabled_in_config")
                if self.progress_callback:
                    self.progress_callback("phase_skipped", {
                        "phase": "VALIDATION",
                        "phase_name": "VALIDATION",
                        "reason": "disabled_in_config"
                    })

            # Phase 4: FORTIFICATION
            enable_fortification = getattr(self.config, 'enable_fortification', True)
            if enable_fortification:
                logger.info("phase_enabled", phase="FORTIFICATION", enabled=enable_fortification)
                await self.phase_executor.execute_fortification_async(context, code_files)
            else:
                logger.info("phase_skipped", phase="FORTIFICATION", reason="disabled_in_config")
                if self.progress_callback:
                    self.progress_callback("phase_skipped", {
                        "phase": "FORTIFICATION",
                        "phase_name": "FORTIFICATION",
                        "reason": "disabled_in_config"
                    })

            # Phase 5: CLEANING
            enable_cleaning = getattr(self.config, 'enable_cleaning', True)
            if enable_cleaning:
                logger.info("phase_enabled", phase="CLEANING", enabled=enable_cleaning)
                await self.phase_executor.execute_cleaning_async(context, code_files)
            else:
                logger.info("phase_skipped", phase="CLEANING", reason="disabled_in_config")
                if self.progress_callback:
                    self.progress_callback("phase_skipped", {
                        "phase": "CLEANING",
                        "phase_name": "CLEANING",
                        "reason": "disabled_in_config"
                    })

            self.pipeline.status = PipelineStatus.COMPLETED
            self.pipeline.ended_at = datetime.now()

            logger.info(
                "pipeline_execution_completed",
                pipeline_id=context.pipeline_id,
                summary=context.get_summary(),
            )

        except Exception as e:
            import traceback
            self.pipeline.status = PipelineStatus.FAILED
            self.pipeline.ended_at = datetime.now()
            logger.error(
                "pipeline_execution_failed",
                pipeline_id=context.pipeline_id,
                error=str(e),
                error_type=type(e).__name__,
                traceback=traceback.format_exc(),
            )
            context.errors.append(f"Pipeline failed: {str(e)}")
            raise

        return context

    def _build_pipeline_result(self, context: PipelineContext) -> PipelineResult:
        """Build PipelineResult from context for compatibility."""
        frame_results = []

        # Convert context frame results to FrameResult objects
        if hasattr(context, 'frame_results') and context.frame_results:
            for frame_id, frame_data in context.frame_results.items():
                result = frame_data.get('result')
                if result:
                    frame_results.append(result)

        return PipelineResult(
            pipeline_id=context.pipeline_id,
            pipeline_name="Validation Pipeline",
            status=self.pipeline.status if hasattr(self, 'pipeline') else PipelineStatus.COMPLETED,
            duration=(datetime.now() - context.started_at).total_seconds() if context.started_at else 0.0,
            total_frames=len(self.frames),
            frames_passed=getattr(self.pipeline, 'frames_passed', 0) if hasattr(self, 'pipeline') else 0,
            frames_failed=getattr(self.pipeline, 'frames_failed', 0) if hasattr(self, 'pipeline') else 0,
            frames_skipped=0,
            total_findings=len(context.findings) if hasattr(context, 'findings') else 0,
            critical_findings=len([f for f in context.findings if isinstance(f, dict) and f.get('severity') == 'critical'])
                             if hasattr(context, 'findings') else 0,
            high_findings=len([f for f in context.findings if isinstance(f, dict) and f.get('severity') == 'high'])
                         if hasattr(context, 'findings') else 0,
            medium_findings=len([f for f in context.findings if isinstance(f, dict) and f.get('severity') == 'medium'])
                           if hasattr(context, 'findings') else 0,
            low_findings=len([f for f in context.findings if isinstance(f, dict) and f.get('severity') == 'low'])
                        if hasattr(context, 'findings') else 0,
            frame_results=frame_results,
        )