"""
Main Phase Orchestrator for 6-phase pipeline.

Coordinates execution of all pipeline phases with shared PipelineContext.
"""

import asyncio
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional
from uuid import uuid4

import structlog

from warden.analysis.services.finding_verifier import FindingVerificationService
from warden.llm.factory import create_client
from warden.lsp.diagnostic_service import LSPDiagnosticService
from warden.pipeline.domain.enums import PipelineStatus
from warden.pipeline.domain.models import (
    PipelineConfig,
    PipelineResult,
    ValidationPipeline,
)
from warden.pipeline.domain.pipeline_context import PipelineContext
from warden.rules.application.rule_validator import CustomRuleValidator
from warden.shared.infrastructure.error_handler import OperationTimeoutError, ValidationError, async_error_handler
from warden.shared.infrastructure.logging import get_logger
from warden.shared.services.semantic_search_service import SemanticSearchService
from warden.shared.utils.finding_utils import get_finding_attribute, get_finding_severity
from warden.validation.domain.frame import CodeFile, ValidationFrame

from .frame_executor import FrameExecutor
from .phase_executor import PhaseExecutor

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
        frames: list[ValidationFrame] | None = None,
        config: PipelineConfig | None = None,
        progress_callback: Callable | None = None,
        project_root: Path | None = None,
        llm_service: Any | None = None,
        available_frames: list[ValidationFrame] | None = None,
        rate_limiter: Any | None = None,
    ):
        """
        Initialize phase orchestrator.

        Args:
            frames: List of validation frames to execute (User configured)
            config: Pipeline configuration (can be dict or PipelineConfig)
            progress_callback: Optional callback for progress updates
            project_root: Root directory of the project
            llm_service: Optional LLM service for AI-powered phases
            available_frames: List of all discoverable frames (for AI selection)
        """
        self.frames = frames or []
        self.available_frames = available_frames or self.frames  # Fallback to frames if not provided
        self.rate_limiter = rate_limiter

        # Handle both dict and PipelineConfig for backward compatibility
        if config is None:
            self.config = PipelineConfig()
        elif isinstance(config, dict):
            # Convert dict to PipelineConfig
            self.config = PipelineConfig()
            for key, value in config.items():
                setattr(self.config, key, value)
        else:
            self.config = config

        self._progress_callback = progress_callback
        self.project_root = project_root or Path.cwd()
        self.llm_service = llm_service

        # Initialize rule validator if global rules exist
        self.rule_validator = None
        if self.config.global_rules:
            self.rule_validator = CustomRuleValidator(self.config.global_rules, llm_service=self.llm_service)

        # Initialize Semantic Search Service if enabled in config
        self.semantic_search_service = None
        ss_config = getattr(self.config, 'semantic_search_config', None)
        if ss_config and ss_config.get("enabled", False):
            # Pass project root for relative path calculations in indexing
            ss_config["project_root"] = str(self.project_root)
            self.semantic_search_service = SemanticSearchService(ss_config)

        # Initialize LSP Diagnostic Service if enabled in config
        self.lsp_service = None
        lsp_config = getattr(self.config, 'lsp_config', None)
        if lsp_config and lsp_config.get("enabled", False):
            servers = lsp_config.get("servers", [])
            self.lsp_service = LSPDiagnosticService(enabled=True, servers=servers)
            logger.info("lsp_service_initialized", servers=servers)

        # Initialize phase executor
        self.phase_executor = PhaseExecutor(
            config=self.config,
            progress_callback=self.progress_callback,
            project_root=self.project_root,
            llm_service=self.llm_service,
            # Validation logic needs all available frames for AI selection
            frames=self.available_frames,
            semantic_search_service=self.semantic_search_service,
            rate_limiter=self.rate_limiter
        )

        # Initialize frame executor
        self.frame_executor = FrameExecutor(
            frames=self.frames,  # User configured frames (default fallback)
            config=self.config,
            progress_callback=self.progress_callback,
            rule_validator=self.rule_validator,
            llm_service=self.llm_service,
            available_frames=self.available_frames, # All available frames for lookup
            semantic_search_service=self.semantic_search_service
        )

        # Sort frames by priority
        self._sort_frames_by_priority()

        logger.info(
            "phase_orchestrator_initialized",
            project_root=str(self.project_root),
            frame_count=len(self.frames),
            strategy=self.config.strategy.value if self.config.strategy else "sequential",
            frame_rules_count=len(self.config.frame_rules) if self.config.frame_rules else 0,
        )

    @property
    def progress_callback(self) -> Callable | None:
        """Get progress callback."""
        return self._progress_callback

    @progress_callback.setter
    def progress_callback(self, value: Callable | None) -> None:
        """Set progress callback and propagate to executors."""
        self._progress_callback = value
        if hasattr(self, 'phase_executor'):
            self.phase_executor.progress_callback = value
        if hasattr(self, 'frame_executor'):
            self.frame_executor.progress_callback = value

    def _sort_frames_by_priority(self) -> None:
        """Sort frames by priority value (lower value = higher priority)."""
        if self.frames:
            self.frames.sort(key=lambda f: f.priority.value if hasattr(f, 'priority') else 999)

    async def execute_async(
        self,
        code_files: list[CodeFile],
        frames_to_execute: list[str] | None = None,
        analysis_level: str | None = None,
    ) -> tuple[PipelineResult, PipelineContext]:
        """
        Execute the complete 6-phase pipeline with shared context.
        Compatible with old orchestrator interface.

        Args:
            code_files: List of code files to process
            frames_to_execute: Optional list of frame IDs to execute (overrides classification)

        Returns:
            Tuple of (PipelineResult, PipelineContext)
        """
        context = await self.execute_pipeline_async(code_files, frames_to_execute, analysis_level)

        # Build PipelineResult from context for compatibility
        result = self._build_pipeline_result(context)

        return result, context

    async def execute_pipeline_async(
        self,
        code_files: list[CodeFile],
        frames_to_execute: list[str] | None = None,
        analysis_level: str | None = None,
    ) -> PipelineContext:
        """
        Execute the complete 6-phase pipeline with shared context.

        Args:
            code_files: List of code files to process
            frames_to_execute: Optional list of frame IDs to execute (overrides classification)

        Returns:
            PipelineContext with results from results of all phases
        """
        language = "unknown"
        if code_files and len(code_files) > 0:
            language = code_files[0].language or "unknown"
            if language == "unknown" and code_files[0].path:
                # Use Language Registry for detection
                from warden.ast.domain.enums import CodeLanguage
                from warden.shared.languages.registry import LanguageRegistry

                lang_enum = LanguageRegistry.get_language_from_path(code_files[0].path)
                if lang_enum != CodeLanguage.UNKNOWN:
                    language = lang_enum.value

        # Apply analysis level if provided
        if analysis_level:
            from warden.pipeline.domain.enums import AnalysisLevel
            try:
                self.config.analysis_level = AnalysisLevel(analysis_level.lower())
                logger.info("analysis_level_overridden", level=self.config.analysis_level.value)

                # Global overrides for BASIC level to ensure speed and local-only execution
                if self.config.analysis_level == AnalysisLevel.BASIC:
                    self.config.use_llm = False
                    self.config.enable_fortification = False
                    self.config.enable_cleaning = False
                    self.config.enable_issue_validation = False
                    # Classification and Analysis will fallback to rule-based automatically if use_llm is False
                    logger.info("basic_level_overrides_applied", use_llm=False, fortification=False, cleaning=False)
                elif self.config.analysis_level == AnalysisLevel.STANDARD:
                    self.config.use_llm = True
                    self.config.enable_fortification = True
                    self.config.enable_issue_validation = True
                    logger.info("standard_level_overrides_applied", use_llm=True, fortification=True, verification=True)
            except ValueError:
                logger.warning("invalid_analysis_level", provided=analysis_level, fallback=self.config.analysis_level.value)

        # Initialize shared context
        context = PipelineContext(
            pipeline_id=str(uuid4()),
            started_at=datetime.now(),
            file_path=Path(code_files[0].path) if code_files else Path.cwd(),
            project_root=self.project_root, # Pass from orchestrator
            use_gitignore=getattr(self.config, 'use_gitignore', True),
            source_code=code_files[0].content if code_files else "",
            language=language,
            llm_config=getattr(self.llm_service, 'config', None) if hasattr(self.llm_service, 'config') else None
        )

        # Create pipeline entity
        self.pipeline = ValidationPipeline(
            id=context.pipeline_id,
            status=PipelineStatus.RUNNING,
            started_at=context.started_at,
        )

        # Bind scan_id to context vars for correlation tracking (Issue #20)
        self.current_scan_id = str(uuid4())[:8]
        structlog.contextvars.bind_contextvars(scan_id=self.current_scan_id)

        logger.info(
            "pipeline_execution_started",
            pipeline_id=context.pipeline_id,
            scan_id=self.current_scan_id,
            file_count=len(code_files),
            frames_override=frames_to_execute,
        )

        if self.progress_callback:
            self.progress_callback("pipeline_started", {
                "pipeline_id": context.pipeline_id,
                "file_count": len(code_files),
            })

        try:
            # Wrap phase execution in timeout (ID 29 - CRITICAL)
            timeout = getattr(self.config, 'timeout', 300)  # Default 5 minutes

            async def _execute_phases():
                # Phase 0: PRE-ANALYSIS
                if self.config.enable_pre_analysis:
                    await self.phase_executor.execute_pre_analysis_async(context, code_files)

                    # Populate ProjectIntelligence from AST context (zero LLM cost)
                    self._populate_project_intelligence(context, code_files)

                # Phase 0.5: TRIAGE (Adaptive Hybrid Triage)
                # Only run if LLM is enabled and level is not BASIC
                from warden.pipeline.domain.enums import AnalysisLevel
                if getattr(self.config, 'use_llm', True) and self.config.analysis_level != AnalysisLevel.BASIC:
                    logger.info("phase_enabled", phase="TRIAGE", enabled=True)
                    await self.phase_executor.execute_triage_async(context, code_files)

                # Phase 1: ANALYSIS
                if getattr(self.config, 'enable_analysis', True):
                    await self.phase_executor.execute_analysis_async(context, code_files)
                    # Initialize after score to before score
                    context.quality_score_after = context.quality_score_before

                # Phase 2: CLASSIFICATION
                # If frames override is provided, use it and skip AI classification
                if frames_to_execute:
                    context.selected_frames = frames_to_execute
                    context.classification_reasoning = "User manually selected frames via CLI"
                    logger.info("using_frame_override", selected_frames=frames_to_execute)

                    # Add phase result placeholder
                    context.add_phase_result("CLASSIFICATION", {
                        "selected_frames": frames_to_execute,
                        "suppression_rules_count": 0,
                        "reasoning": "Manual override",
                        "skipped": True
                    })

                    if self.progress_callback:
                        self.progress_callback("phase_skipped", {
                            "phase": "CLASSIFICATION",
                            "reason": "manual_frame_override"
                        })
                else:
                    # Classification is critical for intelligent frame selection
                    logger.info("phase_enabled", phase="CLASSIFICATION", enabled=True, enforced=True)
                    await self.phase_executor.execute_classification_async(context, code_files)

                # Phase 3: VALIDATION with execution strategies
                enable_validation = getattr(self.config, 'enable_validation', True)
                if enable_validation:
                    logger.info("phase_enabled", phase="VALIDATION", enabled=enable_validation)
                    # Pass pipeline reference to frame executor
                    # Calculate work units for progress bar
                    total_work_units = self._calculate_total_work_units(context, code_files)
                    if self.progress_callback:
                        self.progress_callback("progress_init", {
                            "total_units": total_work_units,
                            "phase_units": {
                                "VALIDATION": len(context.selected_frames or []) * len(code_files) if context.selected_frames else 0,
                            }
                        })

                    await self.frame_executor.execute_validation_with_strategy_async(
                        context, code_files, self.pipeline
                    )
                else:
                    logger.info("phase_skipped", phase="VALIDATION", reason="disabled_in_config")
                    if self.progress_callback:
                        self.progress_callback("phase_skipped", {
                            "phase": "VALIDATION",
                            "phase_name": "VALIDATION",
                            "reason": "disabled_in_config"
                        })

                # Phase 3.3: LSP DIAGNOSTICS (Optional Language Server Integration)
                if self.lsp_service:
                    await self._execute_lsp_diagnostics_async(context, code_files)

                # Phase 3.5: VERIFICATION (False Positive Reduction)
                # Must run BEFORE Fortification to avoid fixing false positives
                if getattr(self.config, 'enable_issue_validation', False):
                    await self._execute_verification_phase_async(context)

                # Phase 4: FORTIFICATION
                enable_fortification = getattr(self.config, 'enable_fortification', True)
                if enable_fortification:
                    logger.info("phase_enabled", phase="FORTIFICATION", enabled=enable_fortification)
                    await self.phase_executor.execute_fortification_async(context, code_files)
                else:
                    logger.info("phase_skipped", phase="FORTIFICATION", reason="disabled_in_config")
                    if self.progress_callback:
                        self.progress_callback("phase_skipped", {
                            "phase": "FORTIFICATION",
                            "phase_name": "FORTIFICATION",
                            "reason": "disabled_in_config"
                        })

                # Phase 5: CLEANING
                enable_cleaning = getattr(self.config, 'enable_cleaning', True)
                if enable_cleaning:
                    logger.info("phase_enabled", phase="CLEANING", enabled=enable_cleaning)
                    await self.phase_executor.execute_cleaning_async(context, code_files)
                else:
                    logger.info("phase_skipped", phase="CLEANING", reason="disabled_in_config")
                    if self.progress_callback:
                        self.progress_callback("phase_skipped", {
                            "phase": "CLEANING",
                            "phase_name": "CLEANING",
                            "reason": "disabled_in_config"
                        })

                # Post-Process: Apply Baseline (Smart Filter)
                self._apply_baseline(context)

                # Update pipeline status based on results (ID 3 - Status Machine Fix)
                has_errors = len(context.errors) > 0
                if has_errors:
                    logger.warning("pipeline_has_errors", count=len(context.errors), errors=context.errors[:5])

                # Classify failures as blocker vs non-blocker (ID 3 fix)
                blocker_failures = []
                non_blocker_failures = []

                for fr in getattr(context, 'frame_results', {}).values():
                    result = fr.get('result')
                    if result and result.status == "failed":
                        if result.is_blocker:
                            blocker_failures.append(fr)
                        else:
                            non_blocker_failures.append(fr)

                # Status logic: FAILED > COMPLETED_WITH_FAILURES > COMPLETED
                if has_errors or blocker_failures:
                    self.pipeline.status = PipelineStatus.FAILED
                elif non_blocker_failures:
                    self.pipeline.status = PipelineStatus.COMPLETED_WITH_FAILURES
                else:
                    self.pipeline.status = PipelineStatus.COMPLETED

                self.pipeline.completed_at = datetime.now()

                # Capture LLM Usage if available
                if self.llm_service and hasattr(self.llm_service, 'get_usage'):
                    usage = self.llm_service.get_usage()
                    context.total_tokens = usage.get('total_tokens', 0)
                    context.prompt_tokens = usage.get('prompt_tokens', 0)
                    context.completion_tokens = usage.get('completion_tokens', 0)
                    context.request_count = usage.get('request_count', 0)
                    logger.info("llm_usage_recorded", **usage)

                logger.info(
                    "pipeline_execution_completed",
                    pipeline_id=context.pipeline_id,
                    summary=context.get_summary(),
                )

            # Execute phases with timeout enforcement (ID 29)
            await asyncio.wait_for(_execute_phases(), timeout=timeout)

        except asyncio.TimeoutError:
            # ID 29 - Timeout handler
            self.pipeline.status = PipelineStatus.FAILED
            error_msg = f"Pipeline execution timeout after {timeout}s"
            context.errors.append(error_msg)
            logger.error("pipeline_timeout", timeout=timeout, pipeline_id=context.pipeline_id)
            raise RuntimeError(error_msg)

        except RuntimeError as e:
            if "Integrity check failed" in str(e):
                logger.error("integrity_check_failed", error=str(e))
                self.pipeline.status = PipelineStatus.FAILED
                context.errors.append(str(e))
                # Add a dummy result so CLI can show it
                return context
            raise e

        except Exception as e:
            # Global pipeline failure handler - ensures status is updated and error is traced.
            # While generic, this is necessary at the top orchestration level to catch any phase failure.
            import traceback
            self.pipeline.status = PipelineStatus.FAILED
            self.pipeline.completed_at = datetime.now()
            logger.error(
                "pipeline_execution_failed",
                pipeline_id=context.pipeline_id,
                error=str(e),
                error_type=type(e).__name__,
                traceback=traceback.format_exc(),
            )
            context.errors.append(f"Pipeline failed: {str(e)}")
            raise

        finally:
            # Cleanup and state consistency - always run regardless of success/failure
            await self._cleanup_on_completion_async(context)
            self._ensure_state_consistency(context)

            # Unbind scan_id from context vars (Issue #20)
            try:
                structlog.contextvars.unbind_contextvars("scan_id")
            except Exception:
                pass  # Don't mask original exception if unbind fails

        return context

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
                intel.input_sources.append({
                    "source": src.get("source", ""),
                    "file": cf.path,
                    "line": src.get("line", 0),
                })

            # Critical sinks from AST
            for call in ast_data.get("dangerous_calls", []):
                func_name = call.get("function", "").lower()
                sink_type = "CMD"
                if any(s in func_name for s in ["execute", "query", "cursor", "raw"]):
                    sink_type = "SQL"
                elif any(s in func_name for s in ["render", "html", "template"]):
                    sink_type = "HTML"

                intel.critical_sinks.append({
                    "sink": call.get("function", ""),
                    "type": sink_type,
                    "file": cf.path,
                    "line": call.get("line", 0),
                })

            for q in ast_data.get("sql_queries", []):
                intel.critical_sinks.append({
                    "sink": q.get("function", ""),
                    "type": "SQL",
                    "file": cf.path,
                    "line": q.get("line", 0),
                })

        context.project_intelligence = intel

        logger.info(
            "project_intelligence_populated",
            total_files=intel.total_files,
            input_sources=len(intel.input_sources),
            critical_sinks=len(intel.critical_sinks),
            entry_points=len(intel.entry_points),
            primary_language=intel.primary_language,
        )

    def _calculate_total_work_units(self, context: PipelineContext, code_files: list[CodeFile]) -> int:
        """Calculate total work units for progress reporting."""
        total_units = 0

        # 1. Validation units (Effective Frames * Files)
        # If no frames selected by classification yet, use configured frames as fallback estimate
        selected_frames = getattr(context, 'selected_frames', [])
        effective_frames_count = len(selected_frames) if selected_frames else len(self.frames)

        total_units += effective_frames_count * len(code_files)

        # 2. Verification and Fortification will be added dynamically as we find issues

        return max(total_units, 1)

    @async_error_handler(
        fallback_value=None,
        log_level="warning",
        context_keys=["pipeline_id"],
        reraise=False
    )
    async def _execute_lsp_diagnostics_async(
        self,
        context: PipelineContext,
        code_files: list[CodeFile]
    ) -> None:
        """
        Execute Phase 3.3: LSP Diagnostics (Optional).
        Collects diagnostics from language servers and merges them into findings.

        Uses centralized error handler to prevent LSP failures from blocking pipeline.
        """
        logger.info("phase_started", phase="LSP_DIAGNOSTICS")

        if self.progress_callback:
            self.progress_callback("phase_started", {
                "phase": "LSP_DIAGNOSTICS",
                "phase_name": "LSP Diagnostics",
            })

        try:
            # Collect LSP diagnostics
            lsp_findings = await self.lsp_service.collect_diagnostics_async(
                code_files,
                self.project_root
            )

            if lsp_findings:
                # Add LSP findings to context
                if not hasattr(context, 'findings'):
                    context.findings = []

                context.findings.extend(lsp_findings)

                # Also create a pseudo frame result for LSP
                from warden.validation.domain.frame import FrameResult

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
                        "description": "Language Server Protocol diagnostics"
                    }
                )

                # Add to frame results
                if not hasattr(context, 'frame_results'):
                    context.frame_results = {}

                context.frame_results["lsp"] = {
                    "result": lsp_result,
                    "frame_id": "lsp",
                    "status": "completed"
                }

                # Extract languages from findings for logging
                languages_found = []
                for f in lsp_findings:
                    # Extract language from detail field
                    if f.detail and "from" in f.detail:
                        detail_parts = f.detail.split("from")
                        if len(detail_parts) > 1:
                            source = detail_parts[1].split("(")[0].strip()
                            languages_found.append(source)

                logger.info(
                    "lsp_diagnostics_collected",
                    findings_count=len(lsp_findings),
                    sources=list(set(languages_found)) if languages_found else ["unknown"]
                )

        except Exception as e:
            logger.warning(
                "lsp_diagnostics_failed",
                error=str(e),
                error_type=type(e).__name__
            )
            # Don't fail the pipeline if LSP fails
            context.add_phase_result("LSP_DIAGNOSTICS", {
                "status": "failed",
                "error": str(e)
            })

        finally:
            if self.progress_callback:
                self.progress_callback("phase_completed", {
                    "phase": "LSP_DIAGNOSTICS",
                    "phase_name": "LSP Diagnostics",
                })

    @async_error_handler(
        fallback_value=None,
        log_level="warning",
        context_keys=["pipeline_id"],
        reraise=False
    )
    async def _execute_verification_phase_async(self, context: PipelineContext) -> None:
        """
        Execute Phase 3.5: Verification (LLM-based filtering).
        Reduces false positives before expensive fortification or reporting.

        Uses centralized error handler to prevent verification failures from blocking pipeline.
        """
        logger.info("phase_started", phase="VERIFICATION")
        if self.progress_callback:
            # We don't know exact units until we scan findings
            total_findings = len(context.findings) if hasattr(context, 'findings') else 0
            if total_findings > 0:
                 self.progress_callback("progress_update", {
                     "phase": "VERIFICATION",
                     "total_units": total_findings
                 })

        try:
            # Initialize verifier once per phase
            verify_llm = self.llm_service or create_client()
            verify_mem_manager = getattr(self.config, 'memory_manager', None)

            verifier = FindingVerificationService(
                llm_client=verify_llm,
                memory_manager=verify_mem_manager,
                enabled=True
            )

            verified_count = 0
            dropped_count = 0

            for frame_id, frame_res in context.frame_results.items():
                result_obj = frame_res.get('result')
                if result_obj and result_obj.findings:
                    # Sync findings from object to dict for verifier contract
                    findings_to_verify = [f.to_dict() if hasattr(f, 'to_dict') else f for f in result_obj.findings]

                    # Track metrics locally for logs
                    total_findings = len(findings_to_verify)

                    logger.info("finding_verification_started",
                                frame_id=frame_id,
                                findings_count=len(findings_to_verify))

                    # Verify findings via LLM (Strict Async naming)
                    verified_findings_dicts = await verifier.verify_findings_async(findings_to_verify, context)

                    verified_ids = {f['id'] for f in verified_findings_dicts}

                    # Filter original objects in-place
                    final_findings = []
                    cached_count = 0

                    for f in result_obj.findings:
                        fid = f.get('id') if isinstance(f, dict) else f.id
                        if fid in verified_ids:
                            final_findings.append(f)
                            # Check if it was cached
                            if any(vf.get('verification_metadata', {}).get('cached') for vf in verified_findings_dicts if vf['id'] == fid):
                                cached_count += 1

                    dropped = len(result_obj.findings) - len(final_findings)
                    dropped_count += dropped
                    verified_count += len(final_findings)

                    result_obj.findings = final_findings
                    result_obj.issues_found = len(final_findings)

                    logger.info("finding_verification_complete",
                                frame_id=frame_id,
                                total=total_findings,
                                verified=len(final_findings),
                                dropped=dropped,
                                cached=cached_count)

            # Synchronize globally in context
            all_verified = []
            for fr in context.frame_results.values():
                res = fr.get('result')
                if res and res.findings:
                    all_verified.extend(res.findings)
            context.findings = all_verified

            logger.info("verification_phase_completed",
                        total_verified=verified_count,
                        total_dropped=dropped_count)

        except Exception as e:
            import traceback
            logger.warning("verification_phase_failed", error=str(e), type=type(e).__name__, traceback=traceback.format_exc())

    def _apply_baseline(self, context: PipelineContext) -> None:
        """Filter out existing issues present in baseline."""
        import json
        baseline_path = self.project_root / ".warden" / "baseline.json"

        # Only apply if baseline exists and NOT in 'strict' mode (unless configured otherwise)
        if not baseline_path.exists():
            return

        settings = getattr(self.config, 'settings', {})
        if settings.get('mode') == 'strict' and not settings.get('use_baseline_in_strict', False):
            # In strict mode, we might want to ignore baseline and show everything
            # But usually baseline implies "Acceptance", so default should be to use it unless disabled.
            pass

        try:
            with open(baseline_path) as f:
                baseline_data = json.load(f)

            # Extract baseline fingerprints (rule_id + file_path)
            known_issues = set()
            for frame_res in baseline_data.get('frame_results', []):
                for finding in frame_res.get('findings', []):
                    # Robust identification: rule_id + file (relative to root)
                    rid = get_finding_attribute(finding, 'rule_id')
                    fpath = get_finding_attribute(finding, 'file_path') or get_finding_attribute(finding, 'path')

                    if not fpath: continue

                    # Normalize path relative to project root
                    try:
                        abs_path = Path(fpath)
                        if not abs_path.is_absolute():
                            abs_path = self.project_root / fpath
                        rel_path = str(abs_path.resolve().relative_to(self.project_root.resolve()))
                    except (ValueError, OSError):
                        # Path resolution failed - use original path as fallback
                        rel_path = str(fpath)

                    if rid:
                        known_issues.add(f"{rid}:{rel_path}")

            if not known_issues:
                return

            logger.info("baseline_loaded", known_issues_count=len(known_issues))

            # Filter current findings in Frame Results
            total_suppressed = 0

            for _fid, f_res in context.frame_results.items():
                result_obj = f_res.get('result') # FrameResult object
                if not result_obj: continue

                filtered_findings = []
                # Keep track of suppressions
                suppressed_in_frame = 0

                # Findings might be objects or dicts
                current_findings = result_obj.findings
                if not current_findings: continue

                for finding in current_findings:
                    rid = getattr(finding, 'rule_id', getattr(finding, 'check_id', None))
                    fpath = getattr(finding, 'file_path', getattr(finding, 'path', str(context.file_path)))

                    # Normalize current finding path
                    try:
                        abs_path = Path(fpath)
                        if not abs_path.is_absolute():
                            abs_path = self.project_root / fpath
                        rel_path = str(abs_path.resolve().relative_to(self.project_root.resolve()))
                    except (ValueError, OSError):
                        # Path resolution failed - use original path as fallback
                        rel_path = str(fpath)

                    key = f"{rid}:{rel_path}"

                    if key in known_issues:
                        suppressed_in_frame += 1
                        total_suppressed += 1
                        # We suppress it from active findings
                    else:
                        filtered_findings.append(finding)

                # Update frame result
                result_obj.findings = filtered_findings

                # Update status if all findings suppressed
                if not filtered_findings and result_obj.status == "failed":
                    result_obj.status = "passed"
                    # Also unmark is_blocker?
                    # result_obj.is_blocker = False

            if total_suppressed > 0:
                logger.info("baseline_applied", suppressed_issues=total_suppressed)

                # Sync context.findings to reflect suppression
                # Re-aggregate from frames
                all_findings = []
                for f_res in context.frame_results.values():
                    res = f_res.get('result')
                    if res and res.findings:
                        all_findings.extend(res.findings)
                context.findings = all_findings

        except Exception as e:
            logger.warning("baseline_application_failed", error=str(e))

    async def _cleanup_on_completion_async(self, context: PipelineContext) -> None:
        """
        Cleanup resources after pipeline execution (success or failure).
        Always called in finally block to ensure cleanup happens.
        """
        try:
            # Close semantic search service if open
            if self.semantic_search_service and hasattr(self.semantic_search_service, 'close'):
                try:
                    await self.semantic_search_service.close()
                except Exception as e:
                    logger.warning("semantic_search_cleanup_failed", error=str(e))

            # Shutdown LSP diagnostic service if enabled
            if self.lsp_service:
                try:
                    await self.lsp_service.shutdown_async()
                    logger.info("lsp_diagnostic_service_shutdown_complete")
                except Exception as e:
                    logger.warning("lsp_diagnostic_service_shutdown_failed", error=str(e))

            # Shutdown LSP servers if running (ID 37 - Zombie Process Fix)
            if hasattr(self.phase_executor, 'lsp_diagnostics') and self.phase_executor.lsp_diagnostics:
                try:
                    if hasattr(self.phase_executor.lsp_diagnostics, 'shutdown'):
                        await self.phase_executor.lsp_diagnostics.shutdown()
                except Exception as e:
                    logger.warning("lsp_shutdown_failed", error=str(e))

            # Shutdown global LSP manager (ensures ALL language servers are killed)
            try:
                from warden.lsp.manager import LSPManager
                lsp_manager = LSPManager.get_instance()
                await lsp_manager.shutdown_all_async()
                logger.info("lsp_manager_shutdown_complete")
            except Exception as e:
                logger.warning("lsp_manager_shutdown_failed", error=str(e))

            # Close frame executor resources
            if hasattr(self.frame_executor, 'cleanup'):
                try:
                    await self.frame_executor.cleanup()
                except Exception as e:
                    logger.warning("frame_executor_cleanup_failed", error=str(e))

            logger.info("pipeline_cleanup_completed", pipeline_id=context.pipeline_id)

        except Exception as e:
            logger.error("cleanup_failed", pipeline_id=context.pipeline_id, error=str(e))

    def _ensure_state_consistency(self, context: PipelineContext) -> None:
        """
        Ensure pipeline context is in consistent state before returning.
        Fixes: Lying state machine (incomplete phases marked as complete).
        """
        try:
            # Verify pipeline status reflects actual execution
            if not self.pipeline.completed_at:
                self.pipeline.completed_at = datetime.now()

            # Check for partial failures
            frame_results = getattr(context, 'frame_results', {})
            failed_frames = []
            passed_frames = []

            for fr_dict in frame_results.values():
                result_obj = fr_dict.get('result')  # Get FrameResult object
                if result_obj:
                    if getattr(result_obj, 'status', None) == 'failed':
                        failed_frames.append(fr_dict)
                    elif getattr(result_obj, 'status', None) == 'passed':
                        passed_frames.append(fr_dict)

            # If some frames failed but pipeline marked COMPLETED, fix it
            if failed_frames and self.pipeline.status == PipelineStatus.COMPLETED:
                logger.warning(
                    "state_inconsistency_detected",
                    expected_status="COMPLETED_WITH_FAILURES",
                    actual_status=self.pipeline.status,
                    failed_frames=len(failed_frames)
                )
                # Mark with failures if failures exist
                self.pipeline.status = PipelineStatus.FAILED

            # Verify context has errors recorded for failed state
            if self.pipeline.status == PipelineStatus.FAILED and not context.errors:
                context.errors.append("Pipeline marked FAILED but no errors recorded")

            # Sync pipeline counts to context
            self.pipeline.frames_passed = len(passed_frames)
            self.pipeline.frames_failed = len(failed_frames)

            logger.info(
                "state_consistency_verified",
                pipeline_id=context.pipeline_id,
                status=self.pipeline.status.value,
                frames_passed=self.pipeline.frames_passed,
                frames_failed=self.pipeline.frames_failed
            )

        except Exception as e:
            logger.error("state_consistency_check_failed", error=str(e))

    def _build_pipeline_result(self, context: PipelineContext) -> PipelineResult:
        """Build PipelineResult from context for compatibility."""
        frame_results = []

        # Convert context frame results to FrameResult objects
        if hasattr(context, 'frame_results') and context.frame_results:
            for _frame_id, frame_data in context.frame_results.items():
                result = frame_data.get('result')
                if result:
                    frame_results.append(result)

        # Helper to get severity from finding (object or dict)
        def get_severity(f: Any) -> str:
            return get_finding_severity(f)

        # Helper to get review_required from finding
        def is_review_required(f: Any) -> bool:
            if isinstance(f, dict):
                return f.get('verification_metadata', {}).get('review_required', False)
            v = getattr(f, 'verification_metadata', {})
            return v.get('review_required', False) if isinstance(v, dict) else False

        # Calculate finding counts
        # First try context.findings (set by verification or baseline phase)
        # If not available or empty, aggregate from frame_results
        findings = []
        if hasattr(context, 'findings') and context.findings:
            findings = context.findings
        else:
            # Aggregate findings from all frame results
            for frame_res in frame_results:
                if hasattr(frame_res, 'findings') and frame_res.findings:
                    findings.extend(frame_res.findings)

        critical_findings = len([f for f in findings if get_severity(f) == 'critical'])
        high_findings = len([f for f in findings if get_severity(f) == 'high'])
        medium_findings = len([f for f in findings if get_severity(f) == 'medium'])
        low_findings = len([f for f in findings if get_severity(f) == 'low'])
        manual_review_count = len([f for f in findings if is_review_required(f)])
        total_findings = len(findings)

        # Calculate quality score if not present or default
        quality_score = getattr(context, 'quality_score_before', None)



        if quality_score is None or quality_score == 0.0:
            # Formula: Asymptotic decay using shared utility
            from warden.shared.utils.quality_calculator import calculate_quality_score
            quality_score = calculate_quality_score(findings)

        # Sync back to context for summary reporting
        context.quality_score_after = quality_score

        # Calculate actual frames processed based on execution results
        frames_passed = getattr(self.pipeline, 'frames_passed', 0) if hasattr(self, 'pipeline') else 0
        frames_failed = getattr(self.pipeline, 'frames_failed', 0) if hasattr(self, 'pipeline') else 0
        frames_skipped = 0

        actual_total = frames_passed + frames_failed + frames_skipped
        planned_total = len(getattr(context, 'selected_frames', [])) or len(self.frames)
        executed_count = len(frame_results)

        # Ensure total never shows less than what was actually processed/passed or exists in results
        total_frames = max(actual_total, planned_total, executed_count)

        return PipelineResult(
            pipeline_id=context.pipeline_id,
            pipeline_name="Validation Pipeline",
            status=self.pipeline.status if hasattr(self, 'pipeline') else PipelineStatus.COMPLETED,
            duration=(datetime.now() - context.started_at).total_seconds() if context.started_at else 0.0,
            total_frames=total_frames,
            frames_passed=frames_passed,
            frames_failed=frames_failed,
            frames_skipped=frames_skipped,
            total_findings=total_findings,
            critical_findings=critical_findings,
            high_findings=high_findings,
            medium_findings=medium_findings,
            low_findings=low_findings,
            manual_review_findings=manual_review_count,
            findings=[f if isinstance(f, dict) else f.to_dict() for f in findings],

            frame_results=frame_results,
            # Populate metadata
            metadata={
                "strategy": self.config.strategy.value,
                "fail_fast": self.config.fail_fast,
                "scan_id": getattr(self, 'current_scan_id', None),
                "advisories": getattr(context, "advisories", []),
                "frame_executions": [
                    {
                        "frame_id": fe.frame_id,
                        "status": fe.status,
                        "duration": fe.duration
                    } for fe in getattr(self.pipeline, 'frame_executions', [])
                ]
            },
            # Populate new fields
            artifacts=getattr(context, 'artifacts', []),
            quality_score=quality_score,
            # LLM Usage
            total_tokens=getattr(context, 'total_tokens', 0),
            prompt_tokens=getattr(context, 'prompt_tokens', 0),
            completion_tokens=getattr(context, 'completion_tokens', 0),
        )
