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
        if self._progress_callback:
            self._progress_callback(
                "phase_started",
                {"phase": "Pre-Analysis", "phase_name": "Pre-Analysis", "total_units": len(code_files)},
            )

        if self.config.enable_pre_analysis:
            await self.phase_executor.execute_pre_analysis_async(context, code_files)

            # Populate ProjectIntelligence from AST context (zero LLM cost)
            self._populate_project_intelligence(context, code_files)

            # Populate taint analysis (zero LLM cost, per-file static analysis)
            await self._populate_taint_paths_async(context, code_files)

            # Phase 0.8: LSP Audit (optional, zero LLM cost)
            await self._populate_lsp_audit_async(context)

        # Phase 0.5: TRIAGE (Adaptive Hybrid Triage)
        from warden.pipeline.domain.enums import AnalysisLevel

        if self._progress_callback:
            self._progress_callback(
                "phase_started",
                {"phase": "Triage", "phase_name": "Triage", "total_units": len(code_files)},
            )

        if getattr(self.config, "use_llm", True) and self.config.analysis_level != AnalysisLevel.BASIC:
            if self._is_single_tier_provider():
                # CLI-tool providers (Codex, Claude Code) spawn a subprocess per
                # LLM call (~20s each).  Running 100+ triage calls is prohibitive.
                # Use heuristic-only triage: safe files → FAST, rest → MIDDLE.
                logger.info("triage_bypass_single_tier", provider=self._detect_primary_provider())
                self._apply_heuristic_triage(context, code_files)
            else:
                logger.info("phase_enabled", phase="TRIAGE", enabled=True)
                await self.phase_executor.execute_triage_async(context, code_files)

        # Batch phase done — jump counter to completion
        if self._progress_callback:
            self._progress_callback("progress_update", {"increment": len(code_files)})

        # Phase 1: ANALYSIS
        if self._progress_callback:
            self._progress_callback(
                "phase_started",
                {"phase": "Analysis", "phase_name": "Analysis", "total_units": len(code_files)},
            )

        if getattr(self.config, "enable_analysis", True):
            await self.phase_executor.execute_analysis_async(context, code_files)
            context.quality_score_after = context.quality_score_before

        # Batch phase done — jump counter to completion
        if self._progress_callback:
            self._progress_callback("progress_update", {"increment": len(code_files)})

        # Phase 2: CLASSIFICATION
        if self._progress_callback:
            self._progress_callback(
                "phase_started",
                {"phase": "Classification", "phase_name": "Classification", "total_units": len(code_files)},
            )

        if frames_to_execute:
            self._apply_manual_frame_override(context, frames_to_execute)
        else:
            logger.info("phase_enabled", phase="CLASSIFICATION", enabled=True, enforced=True)
            await self.phase_executor.execute_classification_async(context, code_files)

        # Batch phase done — jump counter to completion
        if self._progress_callback:
            self._progress_callback("progress_update", {"increment": len(code_files)})

        # Phase 3: VALIDATION
        enable_validation = getattr(self.config, "enable_validation", True)
        if enable_validation:
            logger.info("phase_enabled", phase="VALIDATION", enabled=enable_validation)
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
            findings_count = len(context.findings) if hasattr(context, "findings") and context.findings else 0
            if self._progress_callback:
                self._progress_callback(
                    "phase_started",
                    {"phase": "Verification", "phase_name": "Verification", "total_units": findings_count},
                )
            await self.post_processor.verify_findings_async(context)

        # Phase 4: FORTIFICATION
        findings_count = len(context.findings) if hasattr(context, "findings") and context.findings else 0
        if self._progress_callback:
            self._progress_callback(
                "phase_started",
                {"phase": "Fortification", "phase_name": "Fortification", "total_units": findings_count},
            )

        enable_fortification = getattr(self.config, "enable_fortification", True)
        if enable_fortification:
            logger.info("phase_enabled", phase="FORTIFICATION", enabled=enable_fortification)
            await self.phase_executor.execute_fortification_async(context, code_files)

            # Batch phase done — jump counter to completion
            if self._progress_callback and findings_count > 0:
                self._progress_callback("progress_update", {"increment": findings_count})
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
        if self._progress_callback:
            self._progress_callback(
                "phase_started",
                {"phase": "Cleaning", "phase_name": "Cleaning", "total_units": len(code_files)},
            )

        enable_cleaning = getattr(self.config, "enable_cleaning", True)
        if enable_cleaning:
            logger.info("phase_enabled", phase="CLEANING", enabled=enable_cleaning)
            await self.phase_executor.execute_cleaning_async(context, code_files)

            # Batch phase done — jump counter to completion
            if self._progress_callback:
                self._progress_callback("progress_update", {"increment": len(code_files)})
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

            # Only process if ast_data is a dictionary (not a raw AST Module)
            if not isinstance(ast_data, dict):
                continue

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

    async def _populate_taint_paths_async(
        self, context: PipelineContext, code_files: list[CodeFile]
    ) -> None:
        """Populate taint analysis results into context (zero LLM cost).

        Runs the shared ``TaintAnalysisService`` once per pipeline and stores
        the results in ``context.taint_paths`` for consumption by any
        ``TaintAware`` frame.
        """
        try:
            from warden.analysis.taint.service import TaintAnalysisService

            project_root = self.project_root or context.project_root
            if not project_root:
                return

            # Read taint config from frames_config.security.taint
            taint_config: dict = {}
            if hasattr(self.config, "frames_config") and self.config.frames_config:
                taint_config = (
                    self.config.frames_config.get("security", {}).get("taint", {})
                )

            from pathlib import Path as _Path

            service = TaintAnalysisService(
                project_root=_Path(str(project_root)),
                taint_config=taint_config,
            )
            context.taint_paths = await service.analyze_all_async(code_files)
        except Exception as e:
            logger.warning("taint_population_failed", error=str(e))

    async def _populate_lsp_audit_async(self, context: PipelineContext) -> None:
        """Phase 0.8: Validate CodeGraph edges via LSP (optional, zero LLM cost).

        Only runs if a CodeGraph was built in Phase 0.7 and LSP is available.
        Stores results in ``context.chain_validation``.
        Hard-capped at 30 seconds to prevent scan stalls.
        """
        if not context.code_graph:
            return

        # Config-level skip
        if hasattr(self, "config") and self.config and not getattr(self.config, "enable_lsp_audit", True):
            logger.debug("lsp_audit_skipped", reason="disabled_by_config")
            return

        try:
            import asyncio as _asyncio

            from warden.lsp.audit_service import LSPAuditService

            project_root = self.project_root or context.project_root
            service = LSPAuditService(project_root=str(project_root) if project_root else None)

            if not await service.health_check_async():
                logger.debug("lsp_audit_skipped", reason="lsp_unavailable")
                return

            # Hard cap: entire LSP phase must finish within 30 seconds
            chain_validation = await _asyncio.wait_for(
                service.validate_dependency_chain_async(context.code_graph),
                timeout=30.0,
            )
            context.chain_validation = chain_validation

            # Persist to disk (matches pre_analysis_phase.py pattern)
            try:
                from warden.analysis.services.intelligence_saver import IntelligenceSaver

                _root = self.project_root or context.project_root
                if _root:
                    from pathlib import Path as _Path

                    IntelligenceSaver(_Path(str(_root))).save_chain_validation(chain_validation)
            except Exception as exc:
                logger.warning("chain_validation_save_failed", error=str(exc))

            logger.info(
                "lsp_audit_completed",
                confirmed=chain_validation.confirmed,
                unconfirmed=chain_validation.unconfirmed,
                dead_symbols=len(chain_validation.dead_symbols),
            )
        except TimeoutError:
            logger.warning("lsp_audit_timeout", timeout=30.0)
        except Exception as e:
            logger.warning("lsp_audit_failed", error=str(e))

    # ------------------------------------------------------------------
    # Single-tier provider triage bypass helpers
    # ------------------------------------------------------------------

    def _detect_primary_provider(self) -> str:
        """Return the lowercase provider name of the primary LLM client."""
        client = self.llm_service
        if client is None:
            return ""

        # OrchestratedLlmClient wraps a smart_client
        inner = getattr(client, "_smart_client", None) or getattr(client, "smart_client", None)
        if inner:
            return str(getattr(inner, "provider", "")).lower()
        return str(getattr(client, "provider", "")).lower()

    def _is_single_tier_provider(self) -> bool:
        """True when the primary provider is a CLI-tool (subprocess-based)."""
        from warden.llm.factory import SINGLE_TIER_PROVIDERS
        from warden.llm.types import LlmProvider

        provider_str = self._detect_primary_provider()
        if not provider_str:
            return False
        try:
            return LlmProvider(provider_str) in SINGLE_TIER_PROVIDERS
        except ValueError:
            return False

    def _apply_heuristic_triage(self, context: PipelineContext, code_files: list[CodeFile]) -> None:
        """Assign triage lanes using heuristics only (zero LLM calls).

        Safe files go to FAST lane; everything else goes to MIDDLE lane so
        that all validation frames still run — there is no coverage loss.
        """
        import time

        from warden.analysis.domain.triage_heuristics import is_heuristic_safe
        from warden.analysis.domain.triage_models import RiskScore, TriageDecision, TriageLane

        start = time.time()
        decisions: dict[str, dict] = {}
        fast_count = 0

        for cf in code_files:
            if is_heuristic_safe(cf):
                lane = TriageLane.FAST
                score = 0.0
                reason = "Heuristic bypass: safe file"
                fast_count += 1
            else:
                lane = TriageLane.MIDDLE
                score = 5.0
                reason = "Heuristic bypass: non-trivial file"

            decision = TriageDecision(
                file_path=str(cf.path),
                lane=lane,
                risk_score=RiskScore(score=score, confidence=1.0, reasoning=reason, category="heuristic"),
                processing_time_ms=(time.time() - start) * 1000,
            )
            decisions[str(cf.path)] = decision.model_dump()

        context.triage_decisions = decisions

        duration_ms = (time.time() - start) * 1000
        logger.info(
            "heuristic_triage_completed",
            total=len(code_files),
            fast=fast_count,
            middle=len(code_files) - fast_count,
            duration_ms=f"{duration_ms:.1f}",
        )

        context.add_phase_result(
            "TRIAGE",
            {
                "mode": "heuristic_bypass",
                "total_files": len(code_files),
                "fast_lane": fast_count,
                "middle_lane": len(code_files) - fast_count,
                "deep_lane": 0,
                "duration_ms": duration_ms,
            },
        )

        if self._progress_callback:
            self._progress_callback(
                "triage_completed",
                {
                    "duration": f"{duration_ms / 1000:.2f}s",
                    "mode": "heuristic_bypass",
                    "stats": {"fast": fast_count, "middle": len(code_files) - fast_count, "deep": 0},
                },
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
