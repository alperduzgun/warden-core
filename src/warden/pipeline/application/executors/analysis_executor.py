"""
Analysis Phase Executor.
"""

import time
from typing import List

from warden.pipeline.domain.pipeline_context import PipelineContext
from warden.validation.domain.frame import CodeFile
from warden.shared.infrastructure.logging import get_logger
from warden.pipeline.application.executors.base_phase_executor import BasePhaseExecutor

logger = get_logger(__name__)


class AnalysisExecutor(BasePhaseExecutor):
    """Executor for the ANALYSIS phase."""

    async def execute_async(
        self,
        context: PipelineContext,
        code_files: List[CodeFile],
    ) -> None:
        """Execute ANALYSIS phase."""
        # Check if verbose mode is enabled via context
        verbose = getattr(context, 'verbose_mode', False)

        logger.info("executing_phase", phase="ANALYSIS", verbose=verbose)

        if self.progress_callback:
            start_time = time.perf_counter()
            self.progress_callback("phase_started", {
                "phase": "ANALYSIS",
                "phase_name": "ANALYSIS",
                "verbose": verbose
            })

        try:
            # Use LLM version if LLM service is available and configured
            use_llm = self.llm_service is not None

            # Check pre_analysis_config for use_llm setting
            if hasattr(self.config, 'pre_analysis_config') and isinstance(self.config.pre_analysis_config, dict):
                config_use_llm = self.config.pre_analysis_config.get('use_llm', True)
                use_llm = self.llm_service and config_use_llm

            if verbose:
                logger.info(
                    "analysis_phase_config_verbose",
                    has_llm_service=self.llm_service is not None,
                    pre_analysis_config=self.config.pre_analysis_config if hasattr(self.config, 'pre_analysis_config') else None,
                    use_llm_final=use_llm,
                    file_count=len(code_files)
                )

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
                    llm_service=self.llm_service,
                    project_root=self.project_root,
                    use_gitignore=getattr(self.config, 'use_gitignore', True),
                )
                if verbose:
                    logger.info("using_llm_analysis_phase_verbose", llm_provider=self.llm_service.__class__.__name__ if self.llm_service else "None")
                logger.info("using_llm_analysis_phase")
            else:
                from warden.analysis.application.analysis_phase import AnalysisPhase
                phase = AnalysisPhase(
                    config=getattr(self.config, 'analysis_config', {}),
                    project_root=self.project_root,
                    use_gitignore=getattr(self.config, 'use_gitignore', True),
                )
                if verbose:
                    logger.info("using_rule_based_analysis_phase_verbose")

            if verbose:
                logger.info("analysis_phase_execute_starting", file_count=len(code_files))

            # Filter out unchanged files to save LLM tokens
            files_to_analyze = []
            file_contexts = getattr(context, 'file_contexts', {})
            
            for cf in code_files:
                f_info = file_contexts.get(cf.path)
                # If no context info or not marked unchanged, we analyze it
                if not f_info or not getattr(f_info, 'is_unchanged', False):
                    files_to_analyze.append(cf)
            
            if not files_to_analyze:
                 logger.info("analysis_phase_skipped_optimization", reason="all_files_unchanged")
                 # Create a dummy result to satisfy pipeline expectations
                 from warden.analysis.domain.quality_metrics import QualityMetrics
                 result = QualityMetrics(
                     complexity_score=5.0,
                     duplication_score=5.0,
                     maintainability_score=5.0,
                     naming_score=5.0,
                     documentation_score=5.0,
                     testability_score=5.0,
                     overall_score=5.0,
                     technical_debt_hours=0.0,
                     summary="Analysis skipped (No changes detected)"
                 )
                 llm_duration = 0.0
            else:
                if verbose:
                    logger.info("analysis_phase_analyzing_subset", total=len(code_files), changed=len(files_to_analyze))
                
                # Identify impacted files for hints
                impacted_paths = [
                    cf.path for cf in files_to_analyze 
                    if getattr(file_contexts.get(cf.path), 'is_impacted', False)
                ]
                
                llm_start_time = time.perf_counter()
                result = await phase.execute(files_to_analyze, pipeline_context=context, impacted_files=impacted_paths)
                llm_duration = time.perf_counter() - llm_start_time

            if verbose:
                logger.info("analysis_phase_execute_completed", duration=llm_duration, overall_score=result.overall_score if hasattr(result, 'overall_score') else None)

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
