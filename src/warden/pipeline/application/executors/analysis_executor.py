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
