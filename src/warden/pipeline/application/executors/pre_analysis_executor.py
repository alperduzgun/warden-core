"""
Pre-Analysis Phase Executor.
"""

import time
import traceback

from warden.pipeline.application.executors.base_phase_executor import BasePhaseExecutor
from warden.pipeline.domain.pipeline_context import PipelineContext
from warden.shared.infrastructure.logging import get_logger
from warden.validation.domain.frame import CodeFile

logger = get_logger(__name__)


class PreAnalysisExecutor(BasePhaseExecutor):
    """Executor for the PRE-ANALYSIS phase."""

    async def execute_async(
        self,
        context: PipelineContext,
        code_files: list[CodeFile],
    ) -> None:
        """Execute PRE-ANALYSIS phase."""
        logger.info("executing_phase", phase="PRE_ANALYSIS")

        start_time = time.perf_counter()

        # Attribute LLM calls in this phase to "pre_analysis" scope
        from warden.llm.metrics import get_global_metrics_collector

        metrics_collector = get_global_metrics_collector()

        with metrics_collector.frame_scope("pre_analysis"):
            try:
                from warden.analysis.application.pre_analysis_phase import PreAnalysisPhase

                phase_config = {
                    "pre_analysis": getattr(self.config, "pre_analysis_config", {}),
                    "semantic_search": getattr(self.config, "semantic_search_config", {}),
                    "integrity_config": getattr(self.config, "integrity_config", {})
                    if hasattr(self.config, "integrity_config")
                    else {},
                    "analysis_level": getattr(self.config, "analysis_level", None),
                    "use_llm": getattr(self.config, "use_llm", True) if hasattr(self.config, "use_llm") else True,
                    "llm_config": getattr(self.config, "llm_config", None),
                    "ci_mode": getattr(self.config, "ci_mode", False),
                    # When force_scan is True, disable memory cache to re-analyze all files
                    "trust_memory_context": not getattr(self.config, "force_scan", False),
                }

                phase = PreAnalysisPhase(
                    project_root=self.project_root,
                    config=phase_config,
                    rate_limiter=self.rate_limiter,
                    llm_service=self.llm_service,
                    progress_callback=self.progress_callback,
                )

                result = await phase.execute_async(code_files, pipeline_context=context)

                # Store results in context
                context.project_type = result.project_context  # legacy field (may hold full object)
                context.project_context = result.project_context  # dedicated typed field
                context.framework = result.project_context.framework if result.project_context else None
                context.file_contexts = result.file_contexts
                context.project_metadata = {}  # Will be populated later if needed

                # Add phase result
                context.add_phase_result(
                    "PRE_ANALYSIS",
                    {
                        "project_type": result.project_context.project_type.value if result.project_context else None,
                        "framework": result.project_context.framework.value if result.project_context else None,
                        "file_count": len(result.file_contexts),
                        "confidence": result.project_context.confidence if result.project_context else 0.0,
                    },
                )

                logger.info(
                    "phase_completed",
                    phase="PRE_ANALYSIS",
                    project_type=result.project_context.project_type.value if result.project_context else None,
                )

            except RuntimeError as e:
                # Critical error: log, record in context, and re-raise to stop pipeline
                logger.error(
                    "phase_failed",
                    phase="PRE_ANALYSIS",
                    error=str(e),
                    error_type=type(e).__name__,
                    tb=traceback.format_exc(),
                )
                context.errors.append(f"PRE_ANALYSIS failed: {e!s}")
                raise
            except Exception as e:
                # Non-critical error: log with full context and continue pipeline
                logger.error(
                    "phase_failed",
                    phase="PRE_ANALYSIS",
                    error=str(e),
                    error_type=type(e).__name__,
                    tb=traceback.format_exc(),
                )
                context.errors.append(f"PRE_ANALYSIS failed: {e!s}")

        if self.progress_callback:
            duration = time.perf_counter() - start_time
            self.progress_callback(
                "phase_completed", {"phase": "PRE_ANALYSIS", "phase_name": "PRE_ANALYSIS", "duration": duration}
            )
