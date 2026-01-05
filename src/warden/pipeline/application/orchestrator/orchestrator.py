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
        available_frames: Optional[List[ValidationFrame]] = None,
    ):
        """
        Initialize phase orchestrator.

        Args:
            frames: List of validation frames to execute (User configured)
            config: Pipeline configuration (can be dict or PipelineConfig)
            progress_callback: Optional callback for progress updates
            project_root: Root directory of the project
            llm_service: Optional LLM service for AI-powered phases
            available_frames: List of all discoverable frames (for AI selection)
        """
        self.frames = frames or []
        self.available_frames = available_frames or self.frames  # Fallback to frames if not provided

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
            # Validation logic needs all available frames for AI selection
            frames=self.available_frames
        )

        # Initialize frame executor
        self.frame_executor = FrameExecutor(
            frames=self.frames,  # User configured frames (default fallback)
            config=self.config,
            progress_callback=self.progress_callback,
            rule_validator=self.rule_validator,
            llm_service=self.llm_service,
            available_frames=self.available_frames # All available frames for lookup
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
            project_root=self.project_root, # Pass from orchestrator
            use_gitignore=getattr(self.config, 'use_gitignore', True),
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
                # Initialize after score to before score
                context.quality_score_after = context.quality_score_before

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

            # Update pipeline status based on results
            has_errors = len(context.errors) > 0
            if has_errors:
                logger.warning("pipeline_has_errors", count=len(context.errors), errors=context.errors[:5])
            
            if self.pipeline.frames_failed > 0 or has_errors:
                # Only fail if there are actual failures or blocker violations
                if (has_errors) or (self.pipeline.frames_failed > 0) or any(
                    fr.get('result').is_blocker for fr in getattr(context, 'frame_results', {}).values() 
                    if fr.get('result') and fr.get('result').status == "failed"
                ):
                    self.pipeline.status = PipelineStatus.FAILED
                else:
                    self.pipeline.status = PipelineStatus.COMPLETED
            else:
                self.pipeline.status = PipelineStatus.COMPLETED
                
            self.pipeline.completed_at = datetime.now()

            logger.info(
                "pipeline_execution_completed",
                pipeline_id=context.pipeline_id,
                summary=context.get_summary(),
            )

        except Exception as e:
            import traceback
            self.pipeline.status = PipelineStatus.FAILED
            self.pipeline.completed_at = datetime.now()
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

        # Helper to get severity from finding (object or dict)
        def get_severity(f: Any) -> str:
            val = None
            if isinstance(f, dict):
                val = f.get('severity')
            else:
                val = getattr(f, 'severity', None)
            
            
            
            return str(val).lower() if val else ''

        # Calculate finding counts
        findings = context.findings if hasattr(context, 'findings') else []
        critical_findings = len([f for f in findings if get_severity(f) == 'critical'])
        high_findings = len([f for f in findings if get_severity(f) == 'high'])
        medium_findings = len([f for f in findings if get_severity(f) == 'medium'])
        low_findings = len([f for f in findings if get_severity(f) == 'low'])
        total_findings = len(findings)

        # Calculate quality score if not present or default
        quality_score = getattr(context, 'quality_score_before', None)
        


        if quality_score is None or quality_score == 0.0:
            # Formula: Asymptotic decay
            # Base Score: 10
            # Penalties: Critical=3, High=1.5, Medium=0.5, Low=0.1
            # Formula: 10 * (20 / (penalty + 20))
            # This ensures score never hits absolute 0 and scales well with finding count
            penalty = (critical_findings * 3.0) + (high_findings * 1.5) + (medium_findings * 0.5) + (low_findings * 0.1)
            quality_score = 10.0 * (20.0 / (penalty + 20.0))
            
            # Cap at 10.0 just in case
            quality_score = min(10.0, max(0.1, quality_score))

        # Sync back to context for summary reporting
        context.quality_score_after = quality_score

        # Calculate actual frames processed based on execution results
        frames_passed = getattr(self.pipeline, 'frames_passed', 0) if hasattr(self, 'pipeline') else 0
        frames_failed = getattr(self.pipeline, 'frames_failed', 0) if hasattr(self, 'pipeline') else 0
        frames_skipped = 0 
        
        actual_total = frames_passed + frames_failed + frames_skipped
        planned_total = len(getattr(context, 'selected_frames', [])) or len(self.frames)
        
        # Ensure total never shows less than what was actually processed/passed
        total_frames = max(actual_total, planned_total)

        return PipelineResult(
            pipeline_id=context.pipeline_id,
            pipeline_name="Validation Pipeline",
            status=self.pipeline.status if hasattr(self, 'pipeline') else PipelineStatus.COMPLETED,
            duration=(datetime.now() - context.started_at).total_seconds() if context.started_at else 0.0,
            total_frames=total_frames,
            frames_passed=frames_passed,
            frames_failed=frames_failed,
            frames_skipped=frames_skipped,
            total_findings=total_findings,
            critical_findings=critical_findings,
            high_findings=high_findings,
            medium_findings=medium_findings,
            low_findings=low_findings,

            frame_results=frame_results,
            # Populate metadata
            metadata={
                "strategy": self.config.strategy.value,
                "fail_fast": self.config.fail_fast,
                "frame_executions": [
                    {
                        "frame_id": fe.frame_id,
                        "status": fe.status,
                        "duration": fe.duration
                    } for fe in getattr(self.pipeline, 'frame_executions', [])
                ]
            },
            # Populate new fields
            artifacts=getattr(context, 'artifacts', []),
            quality_score=quality_score,
            # LLM Usage
            total_tokens=getattr(context, 'total_tokens', 0),
            prompt_tokens=getattr(context, 'prompt_tokens', 0),
            completion_tokens=getattr(context, 'completion_tokens', 0),
        )