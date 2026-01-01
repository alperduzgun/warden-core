"""
Phase executor for individual pipeline phases.

Handles execution of PRE-ANALYSIS, ANALYSIS, CLASSIFICATION, FORTIFICATION, and CLEANING phases.
"""

from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Callable

from warden.pipeline.domain.pipeline_context import PipelineContext
from warden.pipeline.domain.models import PipelineConfig
from warden.validation.domain.frame import CodeFile
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)


class PhaseExecutor:
    """Executes individual pipeline phases."""

    def __init__(
        self,
        config: Optional[PipelineConfig] = None,
        progress_callback: Optional[Callable] = None,
        project_root: Optional[Path] = None,
        llm_service: Optional[Any] = None,
    ):
        """
        Initialize phase executor.

        Args:
            config: Pipeline configuration
            progress_callback: Optional callback for progress updates
            project_root: Root directory of the project
            llm_service: Optional LLM service for AI-powered phases
        """
        self.config = config or PipelineConfig()
        self.progress_callback = progress_callback
        self.project_root = project_root or Path.cwd()
        self.llm_service = llm_service

    async def execute_pre_analysis_async(
        self,
        context: PipelineContext,
        code_files: List[CodeFile],
    ) -> None:
        """Execute PRE-ANALYSIS phase."""
        logger.info("executing_phase", phase="PRE_ANALYSIS")

        if self.progress_callback:
            start_time = time.perf_counter()
            self.progress_callback("phase_started", {
                "phase": "PRE_ANALYSIS",
                "phase_name": "PRE_ANALYSIS"
            })

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
                phase="PRE_ANALYSIS",
                project_type=result.project_context.project_type.value if result.project_context else None,
            )

        except Exception as e:
            logger.error("phase_failed", phase="PRE_ANALYSIS", error=str(e))
            context.errors.append(f"PRE_ANALYSIS failed: {str(e)}")

        if self.progress_callback:
            duration = time.perf_counter() - start_time
            self.progress_callback("phase_completed", {
                "phase": "PRE_ANALYSIS",
                "phase_name": "PRE_ANALYSIS",
                "duration": duration
            })

    async def execute_analysis_async(
        self,
        context: PipelineContext,
        code_files: List[CodeFile],
    ) -> None:
        """Execute ANALYSIS phase."""
        logger.info("executing_phase", phase="ANALYSIS")

        if self.progress_callback:
            start_time = time.perf_counter()
            self.progress_callback("phase_started", {
                "phase": "ANALYSIS",
                "phase_name": "ANALYSIS"
            })

        try:
            # Use LLM version if LLM service is available and configured
            use_llm = self.llm_service is not None

            # Check pre_analysis_config for use_llm setting
            if hasattr(self.config, 'pre_analysis_config') and isinstance(self.config.pre_analysis_config, dict):
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

            # Store results in context
            context.quality_metrics = result
            context.quality_score_before = result.overall_score
            context.quality_confidence = 0.8
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
            duration = time.perf_counter() - start_time
            # Include LLM analysis info in progress
            analysis_data = {
                "phase": "ANALYSIS",
                "phase_name": "ANALYSIS",
                "duration": duration
            }
            if hasattr(context, 'quality_metrics') and context.quality_metrics:
                analysis_data["llm_used"] = True
                analysis_data["quality_score"] = getattr(context.quality_metrics, 'overall_score', None)
                analysis_data["llm_reasoning"] = getattr(context.quality_metrics, 'summary', '')[:200] if hasattr(context.quality_metrics, 'summary') else None
            self.progress_callback("phase_completed", analysis_data)

    async def execute_classification_async(
        self,
        context: PipelineContext,
        code_files: List[CodeFile],
    ) -> None:
        """Execute CLASSIFICATION phase."""
        logger.info("executing_phase", phase="CLASSIFICATION")

        if self.progress_callback:
            start_time = time.perf_counter()
            self.progress_callback("phase_started", {
                "phase": "CLASSIFICATION",
                "phase_name": "CLASSIFICATION"
            })

        try:
            # Use LLM version if LLM service is available
            use_llm = self.llm_service is not None

            # Get context from previous phases
            phase_context = context.get_context_for_phase("CLASSIFICATION")

            if use_llm:
                from warden.classification.application.llm_classification_phase import LLMClassificationPhase as ClassificationPhase
                from warden.analysis.application.llm_phase_base import LLMPhaseConfig

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

            # FALLBACK: Use all configured frames if classification fails
            logger.warning("classification_failed_using_all_frames")
            # This will be handled by frame executor

        if self.progress_callback:
            duration = time.perf_counter() - start_time
            classification_data = {
                "phase": "CLASSIFICATION",
                "phase_name": "CLASSIFICATION",
                "duration": duration
            }
            if hasattr(context, 'classification_reasoning') and context.classification_reasoning:
                classification_data["llm_used"] = True
                classification_data["llm_reasoning"] = context.classification_reasoning[:200]
                classification_data["selected_frames"] = context.selected_frames if hasattr(context, 'selected_frames') else []
            self.progress_callback("phase_completed", classification_data)

    async def execute_fortification_async(
        self,
        context: PipelineContext,
        code_files: List[CodeFile],
    ) -> None:
        """Execute FORTIFICATION phase."""
        logger.info("executing_phase", phase="FORTIFICATION")

        if self.progress_callback:
            start_time = time.perf_counter()
            self.progress_callback("phase_started", {
                "phase": "FORTIFICATION",
                "phase_name": "FORTIFICATION"
            })

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
            duration = time.perf_counter() - start_time
            fortification_data = {
                "phase": "FORTIFICATION",
                "phase_name": "FORTIFICATION",
                "duration": duration
            }
            # Check if LLM was used in this phase
            if self.llm_service and hasattr(context, 'fortifications') and context.fortifications:
                 fortification_data["llm_used"] = True
                 fortification_data["fixes_generated"] = len(context.fortifications)
            
            self.progress_callback("phase_completed", fortification_data)

    async def execute_cleaning_async(
        self,
        context: PipelineContext,
        code_files: List[CodeFile],
    ) -> None:
        """Execute CLEANING phase."""
        logger.info("executing_phase", phase="CLEANING")

        if self.progress_callback:
            start_time = time.perf_counter()
            self.progress_callback("phase_started", {
                "phase": "CLEANING",
                "phase_name": "CLEANING"
            })

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
            duration = time.perf_counter() - start_time
            cleaning_data = {
                "phase": "CLEANING",
                "phase_name": "CLEANING",
                "duration": duration
            }
            # Cleaning doesn't use LLM by default yet in this version, but if we add it:
            # if self.llm_service and ...: cleaning_data["llm_used"] = True
            
            self.progress_callback("phase_completed", cleaning_data)