"""Execute all pipeline phases sequentially with progress tracking."""

from collections.abc import Callable
from datetime import datetime
from typing import Any

from warden.pipeline.domain.enums import PipelineStatus
from warden.pipeline.domain.models import PipelineConfig, ValidationPipeline
from warden.pipeline.domain.pipeline_context import PipelineContext
from warden.shared.infrastructure.error_handler import async_error_handler
from warden.shared.infrastructure.logging import get_logger
from warden.validation.domain.frame import CodeFile, FrameResult

logger = get_logger(__name__)


class PipelinePhaseRunner:
    """Coordinates sequential execution of all pipeline phases."""

    def __init__(
        self,
        config: PipelineConfig,
        phase_executor: Any,
        frame_executor: Any,
        post_processor: Any,
        project_root: Any | None = None,
        lsp_service: Any | None = None,
        llm_service: Any | None = None,
        progress_callback: Callable | None = None,
    ):
        self.config = config
        self.phase_executor = phase_executor
        self.frame_executor = frame_executor
        self.post_processor = post_processor
        self.project_root = project_root
        self.lsp_service = lsp_service
        self.llm_service = llm_service
        self._progress_callback = progress_callback

    @property
    def progress_callback(self) -> Callable | None:
        return self._progress_callback

    @progress_callback.setter
    def progress_callback(self, value: Callable | None) -> None:
        self._progress_callback = value

    async def execute_all_phases(
        self,
        context: PipelineContext,
        code_files: list[CodeFile],
        pipeline: ValidationPipeline,
        frames_to_execute: list[str] | None = None,
    ) -> None:
        """Execute all pipeline phases in order."""

        # Phase 0: PRE-ANALYSIS
        if self.config.enable_pre_analysis:
            await self.phase_executor.execute_pre_analysis_async(context, code_files)

            # Populate ProjectIntelligence from AST context (zero LLM cost)
            self._populate_project_intelligence(context, code_files)

        # Phase 0.5: TRIAGE (Adaptive Hybrid Triage)
        from warden.pipeline.domain.enums import AnalysisLevel

        if getattr(self.config, "use_llm", True) and self.config.analysis_level != AnalysisLevel.BASIC:
            logger.info("phase_enabled", phase="TRIAGE", enabled=True)
            await self.phase_executor.execute_triage_async(context, code_files)

        # Phase 1: ANALYSIS
        if getattr(self.config, "enable_analysis", True):
            await self.phase_executor.execute_analysis_async(context, code_files)
            context.quality_score_after = context.quality_score_before

        # Phase 2: CLASSIFICATION
        if frames_to_execute:
            self._apply_manual_frame_override(context, frames_to_execute)
        else:
            logger.info("phase_enabled", phase="CLASSIFICATION", enabled=True, enforced=True)
            await self.phase_executor.execute_classification_async(context, code_files)

        # Phase 3: VALIDATION
        enable_validation = getattr(self.config, "enable_validation", True)
        if enable_validation:
            logger.info("phase_enabled", phase="VALIDATION", enabled=enable_validation)
            total_work_units = self._calculate_total_work_units(context, code_files)
            if self._progress_callback:
                self._progress_callback(
                    "progress_init",
                    {
                        "total_units": total_work_units,
                        "phase_units": {
                            "VALIDATION": len(context.selected_frames or []) * len(code_files)
                            if context.selected_frames
                            else 0,
                        },
                    },
                )
            await self.frame_executor.execute_validation_with_strategy_async(context, code_files, pipeline)
        else:
            logger.info("phase_skipped", phase="VALIDATION", reason="disabled_in_config")
            if self._progress_callback:
                self._progress_callback(
                    "phase_skipped",
                    {
                        "phase": "VALIDATION",
                        "phase_name": "VALIDATION",
                        "reason": "disabled_in_config",
                    },
                )

        # Phase 3.3: LSP DIAGNOSTICS (Optional)
        if self.lsp_service:
            await self._execute_lsp_diagnostics_async(context, code_files)

        # Phase 3.5: VERIFICATION (False Positive Reduction)
        if getattr(self.config, "enable_issue_validation", False):
            await self.post_processor.verify_findings_async(context)

        # Phase 4: FORTIFICATION
        enable_fortification = getattr(self.config, "enable_fortification", True)
        if enable_fortification:
            logger.info("phase_enabled", phase="FORTIFICATION", enabled=enable_fortification)
            await self.phase_executor.execute_fortification_async(context, code_files)
        else:
            logger.info("phase_skipped", phase="FORTIFICATION", reason="disabled_in_config")
            if self._progress_callback:
                self._progress_callback(
                    "phase_skipped",
                    {
                        "phase": "FORTIFICATION",
                        "phase_name": "FORTIFICATION",
                        "reason": "disabled_in_config",
                    },
                )

        # Phase 5: CLEANING
        enable_cleaning = getattr(self.config, "enable_cleaning", True)
        if enable_cleaning:
            logger.info("phase_enabled", phase="CLEANING", enabled=enable_cleaning)
            await self.phase_executor.execute_cleaning_async(context, code_files)
        else:
            logger.info("phase_skipped", phase="CLEANING", reason="disabled_in_config")
            if self._progress_callback:
                self._progress_callback(
                    "phase_skipped",
                    {
                        "phase": "CLEANING",
                        "phase_name": "CLEANING",
                        "reason": "disabled_in_config",
                    },
                )

        # Post-Process: Apply Baseline (Smart Filter)
        self.post_processor.apply_baseline(context)

        # Finalize pipeline status and capture metrics
        self._finalize_pipeline_status(context, pipeline)

    def _apply_manual_frame_override(self, context: PipelineContext, frames_to_execute: list[str]) -> None:
        """Apply manual frame selection, skipping AI classification."""
        context.selected_frames = frames_to_execute
        context.classification_reasoning = "User manually selected frames via CLI"
        logger.info("using_frame_override", selected_frames=frames_to_execute)

        context.add_phase_result(
            "CLASSIFICATION",
            {
                "selected_frames": frames_to_execute,
                "suppression_rules_count": 0,
                "reasoning": "Manual override",
                "skipped": True,
            },
        )

        if self._progress_callback:
            self._progress_callback(
                "phase_skipped",
                {
                    "phase": "CLASSIFICATION",
                    "reason": "manual_frame_override",
                },
            )

    def _populate_project_intelligence(self, context: PipelineContext, code_files: list[CodeFile]) -> None:
        """
        Populate ProjectIntelligence from AST analysis (zero LLM cost).

        Scans code files for input sources, critical sinks, and project metadata.
        This runs during PRE-ANALYSIS and the result is shared with all frames.
        """
        from warden.pipeline.domain.intelligence import ProjectIntelligence

        intel = ProjectIntelligence()
        intel.total_files = len(code_files)

        # Language distribution
        lang_counts: dict[str, int] = {}
        for cf in code_files:
            lang = cf.language or "unknown"
            lang_counts[lang] = lang_counts.get(lang, 0) + 1
            intel.total_lines += cf.line_count

            # Detect entry points
            path_lower = cf.path.lower()
            if any(p in path_lower for p in ["main.py", "app.py", "wsgi.py", "asgi.py", "manage.py", "index."]):
                intel.entry_points.append(cf.path)

            # Detect test files
            if any(p in path_lower for p in ["test_", "_test.", "tests/", "spec/"]):
                intel.test_files.append(cf.path)

            # Detect config files
            if any(p in path_lower for p in ["config", "settings", ".env", ".yaml", ".yml", ".toml"]):
                intel.config_files.append(cf.path)

        intel.file_types = lang_counts
        if lang_counts:
            intel.primary_language = max(lang_counts, key=lang_counts.get)

        # Extract from AST cache if available
        for cf in code_files:
            ast_data = context.ast_cache.get(cf.path, {})

            # Input sources from AST
            for src in ast_data.get("input_sources", []):
                intel.input_sources.append(
                    {
                        "source": src.get("source", ""),
                        "file": cf.path,
                        "line": src.get("line", 0),
                    }
                )

            # Critical sinks from AST
            for call in ast_data.get("dangerous_calls", []):
                func_name = call.get("function", "").lower()
                sink_type = "CMD"
                if any(s in func_name for s in ["execute", "query", "cursor", "raw"]):
                    sink_type = "SQL"
                elif any(s in func_name for s in ["render", "html", "template"]):
                    sink_type = "HTML"

                intel.critical_sinks.append(
                    {
                        "sink": call.get("function", ""),
                        "type": sink_type,
                        "file": cf.path,
                        "line": call.get("line", 0),
                    }
                )

            for q in ast_data.get("sql_queries", []):
                intel.critical_sinks.append(
                    {
                        "sink": q.get("function", ""),
                        "type": "SQL",
                        "file": cf.path,
                        "line": q.get("line", 0),
                    }
                )

        context.project_intelligence = intel

        logger.info(
            "project_intelligence_populated",
            total_files=intel.total_files,
            input_sources=len(intel.input_sources),
            critical_sinks=len(intel.critical_sinks),
            entry_points=len(intel.entry_points),
            primary_language=intel.primary_language,
        )

    def _finalize_pipeline_status(self, context: PipelineContext, pipeline: ValidationPipeline) -> None:
        """Update pipeline status based on results and capture LLM usage."""
        has_errors = len(context.errors) > 0
        if has_errors:
            logger.warning("pipeline_has_errors", count=len(context.errors), errors=context.errors[:5])

        blocker_failures = []
        non_blocker_failures = []

        for fr in getattr(context, "frame_results", {}).values():
            result = fr.get("result")
            if result and result.status == "failed":
                if result.is_blocker:
                    blocker_failures.append(fr)
                else:
                    non_blocker_failures.append(fr)

        if has_errors or blocker_failures:
            pipeline.status = PipelineStatus.FAILED
        elif non_blocker_failures:
            pipeline.status = PipelineStatus.COMPLETED_WITH_FAILURES
        else:
            pipeline.status = PipelineStatus.COMPLETED

        pipeline.completed_at = datetime.now()

        # Capture LLM Usage if available
        if self.llm_service and hasattr(self.llm_service, "get_usage"):
            usage = self.llm_service.get_usage()
            context.total_tokens = usage.get("total_tokens", 0)
            context.prompt_tokens = usage.get("prompt_tokens", 0)
            context.completion_tokens = usage.get("completion_tokens", 0)
            context.request_count = usage.get("request_count", 0)
            logger.info("llm_usage_recorded", **usage)

        logger.info(
            "pipeline_execution_completed",
            pipeline_id=context.pipeline_id,
            summary=context.get_summary(),
        )

    def _calculate_total_work_units(self, context: PipelineContext, code_files: list[CodeFile]) -> int:
        """Calculate total work units for progress reporting."""
        selected_frames = getattr(context, "selected_frames", [])
        effective_frames_count = len(selected_frames) if selected_frames else len(self.frame_executor.frames)
        total_units = effective_frames_count * len(code_files)
        return max(total_units, 1)

    @async_error_handler(
        fallback_value=None,
        log_level="warning",
        context_keys=["pipeline_id"],
        reraise=False,
    )
    async def _execute_lsp_diagnostics_async(
        self,
        context: PipelineContext,
        code_files: list[CodeFile],
    ) -> None:
        """
        Execute Phase 3.3: LSP Diagnostics (Optional).
        Collects diagnostics from language servers and merges them into findings.
        """
        logger.info("phase_started", phase="LSP_DIAGNOSTICS")

        if self._progress_callback:
            self._progress_callback(
                "phase_started",
                {
                    "phase": "LSP_DIAGNOSTICS",
                    "phase_name": "LSP Diagnostics",
                },
            )

        try:
            lsp_findings = await self.lsp_service.collect_diagnostics_async(
                code_files,
                self.project_root,
            )

            if lsp_findings:
                if not hasattr(context, "findings"):
                    context.findings = []
                context.findings.extend(lsp_findings)

                lsp_result = FrameResult(
                    frame_id="lsp",
                    frame_name="LSP Diagnostics",
                    status="passed",
                    findings=lsp_findings,
                    issues_found=len(lsp_findings),
                    duration=0.0,
                    is_blocker=False,
                    metadata={
                        "source": "lsp",
                        "description": "Language Server Protocol diagnostics",
                    },
                )

                if not hasattr(context, "frame_results"):
                    context.frame_results = {}

                context.frame_results["lsp"] = {
                    "result": lsp_result,
                    "frame_id": "lsp",
                    "status": "completed",
                }

                languages_found = []
                for f in lsp_findings:
                    if f.detail and "from" in f.detail:
                        detail_parts = f.detail.split("from")
                        if len(detail_parts) > 1:
                            source = detail_parts[1].split("(")[0].strip()
                            languages_found.append(source)

                logger.info(
                    "lsp_diagnostics_collected",
                    findings_count=len(lsp_findings),
                    sources=list(set(languages_found)) if languages_found else ["unknown"],
                )

        except Exception as e:
            logger.warning(
                "lsp_diagnostics_failed",
                error=str(e),
                error_type=type(e).__name__,
            )
            context.add_phase_result(
                "LSP_DIAGNOSTICS",
                {
                    "status": "failed",
                    "error": str(e),
                },
            )

        finally:
            if self._progress_callback:
                self._progress_callback(
                    "phase_completed",
                    {
                        "phase": "LSP_DIAGNOSTICS",
                        "phase_name": "LSP Diagnostics",
                    },
                )
