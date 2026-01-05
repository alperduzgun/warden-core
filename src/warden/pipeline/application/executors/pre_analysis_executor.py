"""
Pre-Analysis Phase Executor.
"""

import time
from typing import List

from warden.pipeline.domain.pipeline_context import PipelineContext
from warden.validation.domain.frame import CodeFile
from warden.shared.infrastructure.logging import get_logger
from warden.pipeline.application.executors.base_phase_executor import BasePhaseExecutor

logger = get_logger(__name__)


class PreAnalysisExecutor(BasePhaseExecutor):
    """Executor for the PRE-ANALYSIS phase."""

    async def execute_async(
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

            # Prepare config for Phase
            phase_config = {
                "pre_analysis": getattr(self.config, 'pre_analysis_config', {}),
                "semantic_search": getattr(self.config, 'semantic_search_config', {}),
                "integrity_config": getattr(self.config, 'integrity_config', {}) if hasattr(self.config, 'integrity_config') else {}
            }

            phase = PreAnalysisPhase(
                project_root=self.project_root,
                config=phase_config,
            )

            result = await phase.execute(code_files, pipeline_context=context)

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

        except RuntimeError as e:
            # Re-raise integrity check failures or other critical errors to stop pipeline
            raise e
        except Exception as e:
            logger.error("phase_failed", phase="PRE_ANALYSIS", error=str(e), type=type(e).__name__)
            context.errors.append(f"PRE_ANALYSIS failed: {str(e)}")

        if self.progress_callback:
            duration = time.perf_counter() - start_time
            self.progress_callback("phase_completed", {
                "phase": "PRE_ANALYSIS",
                "phase_name": "PRE_ANALYSIS",
                "duration": duration
            })
