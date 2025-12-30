"""
Phase Orchestrator for 6-phase pipeline.

Coordinates execution of all pipeline phases with shared PipelineContext.
Ensures proper data flow and phase sequencing.
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
    FrameResult,
    FrameRules,
    PipelineConfig,
)
from warden.pipeline.domain.enums import PipelineStatus, ExecutionStrategy
from warden.rules.application.rule_validator import CustomRuleValidator
from warden.rules.domain.models import CustomRule, CustomRuleViolation
from warden.validation.domain.frame import CodeFile, ValidationFrame
from warden.shared.infrastructure.logging import get_logger

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
            config: Pipeline configuration
            progress_callback: Optional callback for progress updates
            project_root: Root directory of the project
            llm_service: Optional LLM service for AI-powered phases
        """
        self.frames = frames or []
        self.config = config or PipelineConfig()
        self.progress_callback = progress_callback
        self.project_root = project_root or Path.cwd()
        self.llm_service = llm_service

        # Initialize rule validator if global rules exist
        self.rule_validator = None
        if self.config.global_rules:
            self.rule_validator = CustomRuleValidator(self.config.global_rules)

        # Sort frames by priority
        self._sort_frames_by_priority()

        logger.info(
            "phase_orchestrator_initialized",
            project_root=str(self.project_root),
            frame_count=len(self.frames),
            strategy=self.config.strategy.value if self.config.strategy else "sequential",
            frame_rules_count=len(self.config.frame_rules) if self.config.frame_rules else 0,
        )

    def _sort_frames_by_priority(self) -> None:
        """Sort frames by priority value (lower value = higher priority)."""
        if self.frames:
            self.frames.sort(key=lambda f: f.priority.value if hasattr(f, 'priority') else 999)

    async def execute(
        self,
        code_files: List[CodeFile],
    ) -> tuple[PipelineResult, PipelineContext]:
        """
        Execute the complete 6-phase pipeline with shared context.
        Compatible with old orchestrator interface.

        Args:
            code_files: List of code files to process

        Returns:
            Tuple of (PipelineResult, PipelineContext)
        """
        context = await self.execute_pipeline_async(code_files)

        # Build PipelineResult from context for compatibility
        result = self._build_pipeline_result(context)

        return result, context

    async def execute_pipeline_async(
        self,
        code_files: List[CodeFile],
    ) -> PipelineContext:
        """
        Execute the complete 6-phase pipeline with shared context.

        Args:
            code_files: List of code files to process

        Returns:
            PipelineContext with results from all phases
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
        )

        if self.progress_callback:
            self.progress_callback("pipeline_started", {
                "pipeline_id": context.pipeline_id,
                "file_count": len(code_files),
            })

        try:
            # Phase 0: PRE-ANALYSIS
            if self.config.enable_pre_analysis:
                await self._execute_pre_analysis_async(context, code_files)

            # Phase 1: ANALYSIS
            if getattr(self.config, 'enable_analysis', True):
                await self._execute_analysis_async(context, code_files)

            # Phase 2: CLASSIFICATION (ALWAYS ENABLED - Cannot be disabled)
            # Classification is critical for intelligent frame selection
            logger.info("phase_enabled", phase="CLASSIFICATION", enabled=True, enforced=True)
            await self._execute_classification_async(context, code_files)

            # Phase 3: VALIDATION with execution strategies
            enable_validation = getattr(self.config, 'enable_validation', True)
            if enable_validation:
                logger.info("phase_enabled", phase="VALIDATION", enabled=enable_validation)
                await self._execute_validation_with_strategy_async(context, code_files)
            else:
                logger.info("phase_skipped", phase="VALIDATION", reason="disabled_in_config")
                if self.progress_callback:
                    self.progress_callback("phase_skipped", {"phase": "VALIDATION", "reason": "disabled_in_config"})

            # Phase 4: FORTIFICATION
            enable_fortification = getattr(self.config, 'enable_fortification', True)
            if enable_fortification:
                logger.info("phase_enabled", phase="FORTIFICATION", enabled=enable_fortification)
                await self._execute_fortification_async(context, code_files)
            else:
                logger.info("phase_skipped", phase="FORTIFICATION", reason="disabled_in_config")
                if self.progress_callback:
                    self.progress_callback("phase_skipped", {"phase": "FORTIFICATION", "reason": "disabled_in_config"})

            # Phase 5: CLEANING
            enable_cleaning = getattr(self.config, 'enable_cleaning', True)
            if enable_cleaning:
                logger.info("phase_enabled", phase="CLEANING", enabled=enable_cleaning)
                await self._execute_cleaning_async(context, code_files)
            else:
                logger.info("phase_skipped", phase="CLEANING", reason="disabled_in_config")
                if self.progress_callback:
                    self.progress_callback("phase_skipped", {"phase": "CLEANING", "reason": "disabled_in_config"})

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

    async def _execute_pre_analysis_async(
        self,
        context: PipelineContext,
        code_files: List[CodeFile],
    ) -> None:
        """Execute PRE-ANALYSIS phase."""
        logger.info("executing_phase", phase="PRE-ANALYSIS")

        if self.progress_callback:
            self.progress_callback("phase_started", {"phase": "PRE-ANALYSIS"})

        try:
            from warden.analysis.application.pre_analysis_phase import PreAnalysisPhase

            phase = PreAnalysisPhase(
                project_root=self.project_root,
                config=getattr(self.config, 'pre_analysis_config', {}),
            )

            result = await phase.execute(code_files)

            # Store results in context
            context.project_type = result.project_context
            context.framework = result.project_context.framework if result.project_context else None
            context.file_contexts = result.file_contexts
            context.project_metadata = {}  # Will be populated later if needed

            # Add phase result
            context.add_phase_result("PRE_ANALYSIS", {
                "project_type": result.project_context.project_type.value if result.project_context else None,
                "framework": result.project_context.framework.value if result.project_context else None,
                "file_count": len(result.file_contexts),
                "confidence": result.project_context.confidence if result.project_context else 0.0,
            })

            logger.info(
                "phase_completed",
                phase="PRE-ANALYSIS",
                project_type=result.project_context.project_type.value if result.project_context else None,
            )

        except Exception as e:
            logger.error("phase_failed", phase="PRE-ANALYSIS", error=str(e))
            context.errors.append(f"PRE-ANALYSIS failed: {str(e)}")

        if self.progress_callback:
            self.progress_callback("phase_completed", {"phase": "PRE-ANALYSIS"})

    async def _execute_analysis_async(
        self,
        context: PipelineContext,
        code_files: List[CodeFile],
    ) -> None:
        """Execute ANALYSIS phase."""
        logger.info("executing_phase", phase="ANALYSIS")

        if self.progress_callback:
            self.progress_callback("phase_started", {"phase": "ANALYSIS"})

        try:
            # Use LLM version if LLM service is available and configured
            # Default to using LLM if service is available
            use_llm = self.llm_service is not None

            # Check pre_analysis_config for use_llm setting
            if hasattr(self.config, 'pre_analysis_config') and isinstance(self.config.pre_analysis_config, dict):
                # If config explicitly sets use_llm, respect that
                config_use_llm = self.config.pre_analysis_config.get('use_llm', True)
                use_llm = self.llm_service and config_use_llm

            logger.info(
                "analysis_phase_config",
                has_llm_service=self.llm_service is not None,
                pre_analysis_config=self.config.pre_analysis_config if hasattr(self.config, 'pre_analysis_config') else None,
                use_llm_final=use_llm
            )

            # Get context from previous phases
            phase_context = context.get_context_for_phase("ANALYSIS")

            if use_llm:
                from warden.analysis.application.llm_analysis_phase import LLMAnalysisPhase as AnalysisPhase
                from warden.analysis.application.llm_phase_base import LLMPhaseConfig

                # Create LLM phase with service
                phase = AnalysisPhase(
                    config=LLMPhaseConfig(enabled=True, fallback_to_rules=True),
                    llm_service=self.llm_service
                )
                logger.info("using_llm_analysis_phase")
            else:
                from warden.analysis.application.analysis_phase import AnalysisPhase
                phase = AnalysisPhase(
                    config=getattr(self.config, 'analysis_config', {}),
                )

            result = await phase.execute(code_files)

            # Store results in context (result is QualityMetrics object)
            context.quality_metrics = result
            context.quality_score_before = result.overall_score
            context.quality_confidence = 0.8  # Default confidence
            context.hotspots = result.hotspots
            context.quick_wins = result.quick_wins
            context.technical_debt_hours = result.technical_debt_hours

            # Add phase result
            context.add_phase_result("ANALYSIS", {
                "quality_score": result.overall_score,
                "confidence": 0.8,
                "hotspots_count": len(result.hotspots),
                "quick_wins_count": len(result.quick_wins),
                "technical_debt_hours": result.technical_debt_hours,
            })

            logger.info(
                "phase_completed",
                phase="ANALYSIS",
                quality_score=result.overall_score,
            )

        except Exception as e:
            logger.error("phase_failed", phase="ANALYSIS", error=str(e))
            context.errors.append(f"ANALYSIS failed: {str(e)}")

        if self.progress_callback:
            # Include LLM analysis info in progress
            analysis_data = {"phase": "ANALYSIS"}
            if hasattr(context, 'quality_metrics') and context.quality_metrics:
                analysis_data["llm_used"] = True
                analysis_data["quality_score"] = getattr(context.quality_metrics, 'overall_score', None)
                analysis_data["llm_reasoning"] = getattr(context.quality_metrics, 'summary', '')[:200] if hasattr(context.quality_metrics, 'summary') else None
            self.progress_callback("phase_completed", analysis_data)

    async def _execute_classification_async(
        self,
        context: PipelineContext,
        code_files: List[CodeFile],
    ) -> None:
        """Execute CLASSIFICATION phase."""
        logger.info("executing_phase", phase="CLASSIFICATION")

        if self.progress_callback:
            self.progress_callback("phase_started", {"phase": "CLASSIFICATION"})

        try:
            # Use LLM version if LLM service is available
            use_llm = self.llm_service is not None

            # Get context from previous phases
            phase_context = context.get_context_for_phase("CLASSIFICATION")

            if use_llm:
                from warden.classification.application.llm_classification_phase import LLMClassificationPhase as ClassificationPhase
                from warden.analysis.application.llm_phase_base import LLMPhaseConfig

                # Create LLM phase with service
                phase = ClassificationPhase(
                    config=LLMPhaseConfig(enabled=True, fallback_to_rules=True),
                    llm_service=self.llm_service
                )
                logger.info("using_llm_classification_phase")
            else:
                from warden.classification.application.classification_phase import ClassificationPhase
                phase = ClassificationPhase(
                    config=getattr(self.config, 'classification_config', {}),
                    context=phase_context,
                )

            result = await phase.execute_async(code_files)

            # Store results in context
            context.selected_frames = result.selected_frames
            context.suppression_rules = result.suppression_rules
            context.frame_priorities = result.frame_priorities
            context.classification_reasoning = result.reasoning
            context.learned_patterns = result.learned_patterns

            # Add phase result
            context.add_phase_result("CLASSIFICATION", {
                "selected_frames": result.selected_frames,
                "suppression_rules_count": len(result.suppression_rules),
                "reasoning": result.reasoning,
            })

            logger.info(
                "phase_completed",
                phase="CLASSIFICATION",
                selected_frames=result.selected_frames,
            )

        except Exception as e:
            logger.error("phase_failed", phase="CLASSIFICATION", error=str(e))
            context.errors.append(f"CLASSIFICATION failed: {str(e)}")

        if self.progress_callback:
            # Include LLM classification info in progress
            classification_data = {"phase": "CLASSIFICATION"}
            if hasattr(context, 'classification_reasoning') and context.classification_reasoning:
                classification_data["llm_used"] = True
                classification_data["llm_reasoning"] = context.classification_reasoning[:200]
                classification_data["selected_frames"] = context.selected_frames if hasattr(context, 'selected_frames') else []
            self.progress_callback("phase_completed", classification_data)

    async def _execute_validation_with_strategy_async(
        self,
        context: PipelineContext,
        code_files: List[CodeFile],
    ) -> None:
        """Execute VALIDATION phase with execution strategies."""
        logger.info("executing_phase", phase="VALIDATION")

        if self.progress_callback:
            self.progress_callback("phase_started", {"phase": "VALIDATION"})

        try:
            # Filter files based on context if needed
            file_contexts = context.file_contexts or {}
            filtered_files = self._filter_files_by_context(code_files, file_contexts)

            # Execute frames based on strategy
            if self.config.strategy == ExecutionStrategy.SEQUENTIAL:
                await self._execute_frames_sequential(context, filtered_files)
            elif self.config.strategy == ExecutionStrategy.PARALLEL:
                await self._execute_frames_parallel(context, filtered_files)
            elif self.config.strategy == ExecutionStrategy.FAIL_FAST:
                await self._execute_frames_fail_fast(context, filtered_files)
            else:
                # Default to sequential
                await self._execute_frames_sequential(context, filtered_files)

            # Store results in context
            self._store_validation_results(context)

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

    async def _execute_frames_sequential(
        self,
        context: PipelineContext,
        code_files: List[CodeFile],
    ) -> None:
        """Execute frames sequentially."""
        # Use frames selected by Classification phase if available
        frames_to_execute = self.frames
        if hasattr(context, 'selected_frames') and context.selected_frames:
            # Filter frames to only include those selected by Classification
            # Normalize frame names for matching (handle various formats)
            selected_frame_ids = []
            for f in context.selected_frames:
                # Handle different formats: SecurityFrame, security, security-frame, etc.
                normalized = f.lower().replace('frame', '').replace('-', '').replace('_', '')
                selected_frame_ids.append(normalized)

            frames_to_execute = []
            for frame in self.frames:
                # Normalize frame ID for comparison
                frame_id_normalized = frame.frame_id.lower().replace('frame', '').replace('-', '').replace('_', '')
                frame_name_normalized = frame.name.lower().replace(' ', '').replace('-', '').replace('_', '') if hasattr(frame, 'name') else ''

                # Check if this frame was selected
                if frame_id_normalized in selected_frame_ids or frame_name_normalized in selected_frame_ids:
                    frames_to_execute.append(frame)
                    logger.debug(f"Including frame: {frame.frame_id} (matched with Classification selection)")
                else:
                    logger.debug(f"Skipping frame: {frame.frame_id} (not selected by Classification)")
            logger.info(
                "using_classification_selected_frames",
                selected_count=len(frames_to_execute),
                selected_ids=selected_frame_ids,
                original_count=len(self.frames)
            )

        for frame in frames_to_execute:
            if self.config.fail_fast and self.pipeline.frames_failed > 0:
                logger.info("skipping_frame_fail_fast", frame_id=frame.frame_id)
                continue

            await self._execute_frame_with_rules(context, frame, code_files)

    async def _execute_frames_parallel(
        self,
        context: PipelineContext,
        code_files: List[CodeFile],
    ) -> None:
        """Execute frames in parallel with concurrency limit."""
        semaphore = asyncio.Semaphore(self.config.parallel_limit or 3)

        # Use frames selected by Classification phase if available
        frames_to_execute = self.frames
        if hasattr(context, 'selected_frames') and context.selected_frames:
            # Filter frames to only include those selected by Classification
            # Normalize frame names for matching (handle various formats)
            selected_frame_ids = []
            for f in context.selected_frames:
                # Handle different formats: SecurityFrame, security, security-frame, etc.
                normalized = f.lower().replace('frame', '').replace('-', '').replace('_', '')
                selected_frame_ids.append(normalized)

            frames_to_execute = []
            for frame in self.frames:
                # Normalize frame ID for comparison
                frame_id_normalized = frame.frame_id.lower().replace('frame', '').replace('-', '').replace('_', '')
                frame_name_normalized = frame.name.lower().replace(' ', '').replace('-', '').replace('_', '') if hasattr(frame, 'name') else ''

                # Check if this frame was selected
                if frame_id_normalized in selected_frame_ids or frame_name_normalized in selected_frame_ids:
                    frames_to_execute.append(frame)
                    logger.debug(f"Including frame: {frame.frame_id} (matched with Classification selection)")
                else:
                    logger.debug(f"Skipping frame: {frame.frame_id} (not selected by Classification)")
            logger.info(
                "using_classification_selected_frames_parallel",
                selected_count=len(frames_to_execute),
                selected_ids=selected_frame_ids,
                original_count=len(self.frames)
            )

        async def execute_with_semaphore(frame):
            async with semaphore:
                await self._execute_frame_with_rules(context, frame, code_files)

        tasks = [execute_with_semaphore(frame) for frame in frames_to_execute]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _execute_frames_fail_fast(
        self,
        context: PipelineContext,
        code_files: List[CodeFile],
    ) -> None:
        """Execute frames sequentially, stop on first blocker failure."""
        # Use frames selected by Classification phase if available
        frames_to_execute = self.frames
        if hasattr(context, 'selected_frames') and context.selected_frames:
            # Filter frames to only include those selected by Classification
            # Normalize frame names for matching (handle various formats)
            selected_frame_ids = []
            for f in context.selected_frames:
                # Handle different formats: SecurityFrame, security, security-frame, etc.
                normalized = f.lower().replace('frame', '').replace('-', '').replace('_', '')
                selected_frame_ids.append(normalized)

            frames_to_execute = []
            for frame in self.frames:
                # Normalize frame ID for comparison
                frame_id_normalized = frame.frame_id.lower().replace('frame', '').replace('-', '').replace('_', '')
                frame_name_normalized = frame.name.lower().replace(' ', '').replace('-', '').replace('_', '') if hasattr(frame, 'name') else ''

                # Check if this frame was selected
                if frame_id_normalized in selected_frame_ids or frame_name_normalized in selected_frame_ids:
                    frames_to_execute.append(frame)
                    logger.debug(f"Including frame: {frame.frame_id} (matched with Classification selection)")
                else:
                    logger.debug(f"Skipping frame: {frame.frame_id} (not selected by Classification)")
            logger.info(
                "using_classification_selected_frames_failfast",
                selected_count=len(frames_to_execute),
                selected_ids=selected_frame_ids,
                original_count=len(self.frames)
            )

        for frame in frames_to_execute:
            result = await self._execute_frame_with_rules(context, frame, code_files)

            # Check if frame has blocker issues
            if result and hasattr(result, 'has_blocker_issues') and result.has_blocker_issues:
                logger.info("stopping_on_blocker", frame_id=frame.frame_id)
                break

    async def _execute_frame_with_rules(
        self,
        context: PipelineContext,
        frame: ValidationFrame,
        code_files: List[CodeFile],
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
            # For now, use the first file if available
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

            self.pipeline.frames_executed += 1
            if hasattr(frame_result, 'has_critical_issues') and frame_result.has_critical_issues:
                self.pipeline.frames_failed += 1
            else:
                self.pipeline.frames_passed += 1

        except asyncio.TimeoutError:
            logger.error("frame_timeout", frame_id=frame.frame_id)
            frame_result = FrameResult(
                frame_id=frame.frame_id,
                frame_name=frame.name,
                status="timeout",
                findings=[],
            )
            self.pipeline.frames_failed += 1

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
                "findings": len(frame_result.findings),
            })

        return frame_result

    async def _execute_validation_async(
        self,
        context: PipelineContext,
        code_files: List[CodeFile],
    ) -> None:
        """Legacy method for compatibility."""
        await self._execute_validation_with_strategy_async(context, code_files)

    async def _execute_fortification_async(
        self,
        context: PipelineContext,
        code_files: List[CodeFile],
    ) -> None:
        """Execute FORTIFICATION phase."""
        logger.info("executing_phase", phase="FORTIFICATION")

        if self.progress_callback:
            self.progress_callback("phase_started", {"phase": "FORTIFICATION"})

        try:
            from warden.fortification.application.fortification_phase import FortificationPhase

            # Get context from previous phases
            phase_context = context.get_context_for_phase("FORTIFICATION")

            phase = FortificationPhase(
                config=getattr(self.config, 'fortification_config', {}),
                context=phase_context,
                llm_service=self.llm_service,
            )

            # Ensure validated_issues exists and is a list
            validated_issues = getattr(context, 'validated_issues', [])
            if validated_issues is None:
                validated_issues = []

            result = await phase.execute_async(validated_issues)

            # Store results in context
            context.fortifications = result.fortifications
            context.applied_fixes = result.applied_fixes
            context.security_improvements = result.security_improvements

            # Add phase result
            context.add_phase_result("FORTIFICATION", {
                "fortifications_count": len(result.fortifications),
                "critical_fixes": len([f for f in result.fortifications if f.get("severity") == "critical"]),
                "auto_fixable": len([f for f in result.fortifications if f.get("auto_fixable")]),
            })

            logger.info(
                "phase_completed",
                phase="FORTIFICATION",
                fortifications=len(result.fortifications),
            )

        except Exception as e:
            import traceback
            logger.error("phase_failed",
                        phase="FORTIFICATION",
                        error=str(e),
                        error_type=type(e).__name__,
                        traceback=traceback.format_exc())
            context.errors.append(f"FORTIFICATION failed: {str(e)}")

        if self.progress_callback:
            self.progress_callback("phase_completed", {"phase": "FORTIFICATION"})

    async def _execute_cleaning_async(
        self,
        context: PipelineContext,
        code_files: List[CodeFile],
    ) -> None:
        """Execute CLEANING phase."""
        logger.info("executing_phase", phase="CLEANING")

        if self.progress_callback:
            self.progress_callback("phase_started", {"phase": "CLEANING"})

        try:
            from warden.cleaning.application.cleaning_phase import CleaningPhase

            # Get context from previous phases
            phase_context = context.get_context_for_phase("CLEANING")

            phase = CleaningPhase(
                config=getattr(self.config, 'cleaning_config', {}),
                context=phase_context,
            )

            result = await phase.execute_async(code_files)

            # Store results in context
            context.cleaning_suggestions = result.cleaning_suggestions
            context.refactorings = result.refactorings
            context.quality_score_after = result.quality_score_after
            context.code_improvements = result.code_improvements

            # Add phase result
            context.add_phase_result("CLEANING", {
                "suggestions_count": len(result.cleaning_suggestions),
                "refactorings_count": len(result.refactorings),
                "quality_improvement": result.quality_score_after - context.quality_score_before,
            })

            logger.info(
                "phase_completed",
                phase="CLEANING",
                suggestions=len(result.cleaning_suggestions),
                quality_improvement=result.quality_score_after - context.quality_score_before,
            )

        except Exception as e:
            logger.error("phase_failed", phase="CLEANING", error=str(e))
            context.errors.append(f"CLEANING failed: {str(e)}")

        if self.progress_callback:
            self.progress_callback("phase_completed", {"phase": "CLEANING"})

    def _is_false_positive(
        self,
        finding: Dict[str, Any],
        suppression_rules: List[Dict[str, Any]],
    ) -> bool:
        """
        Check if a finding is a false positive based on suppression rules.

        Args:
            finding: Finding to check
            suppression_rules: List of suppression rules

        Returns:
            True if finding is a false positive
        """
        for rule in suppression_rules:
            # Check if rule matches finding
            if (
                rule.get("issue_type") == finding.get("type") and
                rule.get("file_context") == finding.get("file_context")
            ):
                return True

        return False

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

    def _store_validation_results(self, context: PipelineContext) -> None:
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
            "frames_executed": self.pipeline.frames_executed,
            "frames_passed": self.pipeline.frames_passed,
            "frames_failed": self.pipeline.frames_failed,
        })

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