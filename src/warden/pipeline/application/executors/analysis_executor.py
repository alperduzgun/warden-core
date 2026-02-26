"""
Analysis Phase Executor.
"""

import time
import traceback

from warden.pipeline.application.executors.base_phase_executor import BasePhaseExecutor
from warden.pipeline.domain.pipeline_context import PipelineContext
from warden.shared.infrastructure.logging import get_logger
from warden.validation.domain.frame import CodeFile

logger = get_logger(__name__)


class AnalysisExecutor(BasePhaseExecutor):
    """Executor for the ANALYSIS phase."""

    async def execute_async(
        self,
        context: PipelineContext,
        code_files: list[CodeFile],
    ) -> None:
        """Execute ANALYSIS phase."""
        # Check if verbose mode is enabled via context
        verbose = getattr(context, "verbose_mode", False)

        logger.info("executing_phase", phase="ANALYSIS", verbose=verbose)

        start_time = time.perf_counter()

        def _emit(status: str) -> None:
            if self.progress_callback:
                self.progress_callback("progress_update", {"status": status})

        # Attribute LLM calls in this phase to "analysis" scope
        from warden.llm.metrics import get_global_metrics_collector

        metrics_collector = get_global_metrics_collector()

        with metrics_collector.frame_scope("analysis"):
            try:
                # Respect global use_llm flag and LLM service availability
                use_llm = getattr(self.config, "use_llm", True) and self.llm_service is not None

                if verbose:
                    logger.info(
                        "analysis_phase_config_verbose",
                        has_llm_service=self.llm_service is not None,
                        pre_analysis_config=self.config.pre_analysis_config
                        if hasattr(self.config, "pre_analysis_config")
                        else None,
                        use_llm_final=use_llm,
                        file_count=len(code_files),
                    )

                logger.info(
                    "analysis_phase_config",
                    has_llm_service=self.llm_service is not None,
                    pre_analysis_config=self.config.pre_analysis_config
                    if hasattr(self.config, "pre_analysis_config")
                    else None,
                    use_llm_final=use_llm,
                )

                # Get context from previous phases
                context.get_context_for_phase("ANALYSIS")

                if use_llm:
                    from warden.analysis.application.llm_analysis_phase import LLMAnalysisPhase as AnalysisPhase
                    from warden.analysis.application.llm_phase_base import LLMPhaseConfig
                    from warden.shared.services.semantic_search_service import SemanticSearchService

                    phase = AnalysisPhase(
                        config=LLMPhaseConfig(
                            enabled=True,
                            fallback_to_rules=True,
                            tpm_limit=self.config.llm_config.get("tpm_limit", 1000)
                            if getattr(self.config, "llm_config", None)
                            else (
                                getattr(self.config.llm, "tpm_limit", 1000)
                                if hasattr(self.config, "llm")
                                else 1000
                            ),
                            rpm_limit=self.config.llm_config.get("rpm_limit", 6)
                            if getattr(self.config, "llm_config", None)
                            else (getattr(self.config.llm, "rpm_limit", 6) if hasattr(self.config, "llm") else 6),
                        ),
                        llm_service=self.llm_service,
                        project_root=self.project_root,
                        use_gitignore=getattr(self.config, "use_gitignore", True),
                        memory_manager=getattr(self.config, "memory_manager", None),
                        semantic_search_service=SemanticSearchService(),
                        rate_limiter=self.rate_limiter,
                    )
                    if verbose:
                        logger.info(
                            "using_llm_analysis_phase_verbose",
                            llm_provider=self.llm_service.__class__.__name__ if self.llm_service else "None",
                        )
                    logger.info("using_llm_analysis_phase")
                else:
                    from warden.analysis.application.analysis_phase import AnalysisPhase

                    analysis_config = getattr(self.config, "analysis_config", {})
                    if not isinstance(analysis_config, dict):
                        analysis_config = {}

                    # Propagate analysis_level
                    if hasattr(self.config, "analysis_level"):
                        analysis_config["analysis_level"] = self.config.analysis_level.value

                    phase = AnalysisPhase(
                        config=analysis_config,
                        project_root=self.project_root,
                        use_gitignore=getattr(self.config, "use_gitignore", True),
                    )
                    if verbose:
                        logger.info("using_rule_based_analysis_phase_verbose")

                if verbose:
                    logger.info("analysis_phase_execute_starting", file_count=len(code_files))

                # -------------------------------------------------------------
                # LINTER METRICS (Fast Quality Health Check)
                # -------------------------------------------------------------
                _emit("Running linter metrics (Ruff, ESLint, etc.)")
                from warden.analysis.services.linter_service import LinterService

                linter_service = LinterService()
                await linter_service.detect_and_setup(context)
                linter_metrics = await linter_service.run_metrics(code_files)
                context.linter_metrics = linter_metrics

                # Simple Quality Score Impact (e.g., -0.2 per blocker, max -5.0 penalty)
                # This provides an objective baseline before LLM subjectivity
                linter_penalty = 0.0
                total_errors = 0

                for tool, m in linter_metrics.items():
                    if m.is_available:
                        linter_penalty += (m.blocker_count * 0.5) + (m.total_errors * 0.05)
                        total_errors += m.total_errors
                        logger.info(
                            "linter_metrics_integrated", tool=tool, errors=m.total_errors, penalty=linter_penalty
                        )

                # Cap penalty
                linter_penalty = min(linter_penalty, 5.0)

                # Filter out unchanged files to save LLM tokens
                _emit("Filtering unchanged files (incremental optimization)")
                files_to_analyze = []
                file_contexts = getattr(context, "file_contexts", {})

                for cf in code_files:
                    f_info = file_contexts.get(cf.path)
                    if not f_info or not getattr(f_info, "is_unchanged", False):
                        files_to_analyze.append(cf)

                if not files_to_analyze:
                    logger.info("analysis_phase_skipped_optimization", reason="all_files_unchanged")
                    # Create a baseline result from objective linter metrics to satisfy pipeline expectations
                    from warden.analysis.domain.quality_metrics import QualityMetrics
                    from warden.shared.utils.quality_calculator import calculate_base_score

                    base_score = calculate_base_score(linter_metrics)
                    result = QualityMetrics(
                        complexity_score=base_score,
                        duplication_score=base_score,
                        maintainability_score=base_score,
                        naming_score=base_score,
                        documentation_score=base_score,
                        testability_score=base_score,
                        overall_score=base_score,
                        technical_debt_hours=0.0,
                        summary=f"Analysis skipped (No changes detected). Base structural score: {base_score:.1f}/10",
                    )
                    llm_duration = 0.0
                else:
                    if verbose:
                        logger.info(
                            "analysis_phase_analyzing_subset", total=len(code_files), changed=len(files_to_analyze)
                        )

                    # Identify impacted files for hints
                    impacted_paths = [
                        cf.path
                        for cf in files_to_analyze
                        if getattr(file_contexts.get(cf.path), "is_impacted", False)
                    ]

                    llm_start_time = time.perf_counter()
                    _emit(f"Analyzing {len(files_to_analyze)} files with LLM")
                    result = await phase.execute_async(
                        files_to_analyze, pipeline_context=context, impacted_files=impacted_paths
                    )
                    llm_duration = time.perf_counter() - llm_start_time

                if verbose:
                    logger.info(
                        "analysis_phase_execute_completed",
                        duration=llm_duration,
                        overall_score=result.overall_score if hasattr(result, "overall_score") else None,
                    )

                # Store results in context
                context.quality_metrics = result
                context.quality_score_before = result.overall_score
                context.quality_confidence = 0.8
                context.hotspots = result.hotspots
                context.quick_wins = result.quick_wins
                context.technical_debt_hours = result.technical_debt_hours

                # Add phase result
                context.add_phase_result(
                    "ANALYSIS",
                    {
                        "quality_score": result.overall_score,
                        "confidence": 0.8,
                        "hotspots_count": len(result.hotspots),
                        "quick_wins_count": len(result.quick_wins),
                        "technical_debt_hours": result.technical_debt_hours,
                        "linter_errors": total_errors,  # New metric
                        "linter_penalty_applied": linter_penalty,
                    },
                )

                logger.info(
                    "phase_completed",
                    phase="ANALYSIS",
                    quality_score=result.overall_score,
                )

            except RuntimeError as e:
                # Critical error: log, record in context, and re-raise to stop pipeline
                logger.error(
                    "phase_failed",
                    phase="ANALYSIS",
                    error=str(e),
                    error_type=type(e).__name__,
                    tb=traceback.format_exc(),
                )
                context.errors.append(f"ANALYSIS failed: {e!s}")
                raise
            except Exception as e:
                # Non-critical error: log with full context and continue pipeline
                logger.error(
                    "phase_failed",
                    phase="ANALYSIS",
                    error=str(e),
                    error_type=type(e).__name__,
                    tb=traceback.format_exc(),
                )
                context.errors.append(f"ANALYSIS failed: {e!s}")

        if self.progress_callback:
            duration = time.perf_counter() - start_time
            # Include LLM analysis info in progress
            analysis_data = {"phase": "ANALYSIS", "phase_name": "ANALYSIS", "duration": duration}
            if hasattr(context, "quality_metrics") and context.quality_metrics:
                analysis_data["llm_used"] = True
                analysis_data["quality_score"] = getattr(context.quality_metrics, "overall_score", None)
                analysis_data["llm_reasoning"] = (
                    getattr(context.quality_metrics, "summary", "")[:200]
                    if hasattr(context.quality_metrics, "summary")
                    else None
                )
            self.progress_callback("phase_completed", analysis_data)
