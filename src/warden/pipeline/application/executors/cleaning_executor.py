"""
Cleaning Phase Executor.
"""

import time
from typing import List

from warden.pipeline.domain.pipeline_context import PipelineContext
from warden.validation.domain.frame import CodeFile
from warden.shared.infrastructure.logging import get_logger
from warden.pipeline.application.executors.base_phase_executor import BasePhaseExecutor

logger = get_logger(__name__)


class CleaningExecutor(BasePhaseExecutor):
    """Executor for the CLEANING phase."""

    async def execute_async(
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
                llm_service=self.llm_service,
            )

            # Optimization: Filter out unchanged files
            files_to_clean = []
            file_contexts = getattr(context, 'file_contexts', {})
            
            for cf in code_files:
                f_info = file_contexts.get(cf.path)
                # If no context info or not marked unchanged, we clean it
                # Note: is_unchanged is only True if content hash matches AND file is not impacted
                if not f_info or not getattr(f_info, 'is_unchanged', False):
                    files_to_clean.append(cf)
            
            if not files_to_clean:
                 logger.info("cleaning_phase_skipped_optimization", reason="all_files_unchanged")
                 from warden.cleaning.application.cleaning_phase import CleaningPhaseResult
                 result = CleaningPhaseResult(
                     cleaning_suggestions=[],
                     refactorings=[],
                     quality_score_after=getattr(context, 'quality_score_before', 0.0),
                     code_improvements={"message": "Cleaning skipped (No changes detected)"}
                 )
            else:
                 if len(files_to_clean) < len(code_files):
                     logger.info("cleaning_phase_optimizing", total=len(code_files), cleaning=len(files_to_clean))
                 result = await phase.execute_async(files_to_clean)

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
