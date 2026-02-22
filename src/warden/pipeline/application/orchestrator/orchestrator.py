"""
Main Phase Orchestrator for 6-phase pipeline.

Coordinates execution of all pipeline phases with shared PipelineContext.
"""

import asyncio
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import structlog

from warden.lsp.diagnostic_service import LSPDiagnosticService
from warden.pipeline.domain.enums import PipelineStatus
from warden.pipeline.domain.models import (
    PipelineConfig,
    PipelineResult,
    ValidationPipeline,
)
from warden.pipeline.domain.pipeline_context import PipelineContext
from warden.rules.application.rule_validator import CustomRuleValidator
from warden.shared.infrastructure.logging import get_logger
from warden.shared.services.semantic_search_service import SemanticSearchService
from warden.validation.domain.frame import CodeFile, ValidationFrame

from .findings_post_processor import FindingsPostProcessor
from .frame_executor import FrameExecutor
from .phase_executor import PhaseExecutor
from .pipeline_phase_runner import PipelinePhaseRunner
from .pipeline_result_builder import PipelineResultBuilder

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

        # Initialize rule validator if global rules or frame rules exist
        self.rule_validator = None
        if self.config.global_rules or self.config.frame_rules:
            self.rule_validator = CustomRuleValidator(self.config.global_rules or [], llm_service=self.llm_service)

        # Initialize Semantic Search Service if enabled in config
        self.semantic_search_service = None
        ss_config = getattr(self.config, "semantic_search_config", None)
        if ss_config and ss_config.get("enabled", False):
            # Pass project root for relative path calculations in indexing
            ss_config["project_root"] = str(self.project_root)
            self.semantic_search_service = SemanticSearchService(ss_config)

        # Initialize LSP Diagnostic Service if enabled in config
        self.lsp_service = None
        lsp_config = getattr(self.config, "lsp_config", None)
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
            rate_limiter=self.rate_limiter,
        )

        # Initialize frame executor
        self.frame_executor = FrameExecutor(
            frames=self.frames,  # User configured frames (default fallback)
            config=self.config,
            progress_callback=self.progress_callback,
            rule_validator=self.rule_validator,
            llm_service=self.llm_service,
            available_frames=self.available_frames,  # All available frames for lookup
            semantic_search_service=self.semantic_search_service,
        )

        # Initialize post-processor
        self.post_processor = FindingsPostProcessor(
            config=self.config,
            project_root=self.project_root,
            llm_service=self.llm_service,
            progress_callback=self.progress_callback,
        )

        # Initialize result builder
        self.result_builder = PipelineResultBuilder(
            config=self.config,
            frames=self.frames,
        )

        # Initialize phase runner
        self.phase_runner = PipelinePhaseRunner(
            config=self.config,
            phase_executor=self.phase_executor,
            frame_executor=self.frame_executor,
            post_processor=self.post_processor,
            project_root=self.project_root,
            lsp_service=self.lsp_service,
            llm_service=self.llm_service,
            progress_callback=self.progress_callback,
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
        if hasattr(self, "phase_executor"):
            self.phase_executor.progress_callback = value
        if hasattr(self, "frame_executor"):
            self.frame_executor.progress_callback = value
        if hasattr(self, "post_processor"):
            self.post_processor.progress_callback = value
        if hasattr(self, "phase_runner"):
            self.phase_runner.progress_callback = value

    def _sort_frames_by_priority(self) -> None:
        """Sort frames by priority value (lower value = higher priority)."""
        if self.frames:
            self.frames.sort(key=lambda f: f.priority.value if hasattr(f, "priority") else 999)

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
        result = self.result_builder.build(context, self.pipeline, scan_id=getattr(self, "current_scan_id", None))

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
                    logger.info("basic_level_overrides_applied", use_llm=False, fortification=False, cleaning=False)
                elif self.config.analysis_level == AnalysisLevel.STANDARD:
                    self.config.use_llm = True
                    self.config.enable_fortification = True
                    self.config.enable_issue_validation = True
                    logger.info("standard_level_overrides_applied", use_llm=True, fortification=True, verification=True)
            except ValueError:
                logger.warning(
                    "invalid_analysis_level", provided=analysis_level, fallback=self.config.analysis_level.value
                )

        # Initialize shared context
        context = PipelineContext(
            pipeline_id=str(uuid4()),
            started_at=datetime.now(),
            file_path=Path(code_files[0].path) if code_files else Path.cwd(),
            project_root=self.project_root,  # Pass from orchestrator
            use_gitignore=getattr(self.config, "use_gitignore", True),
            source_code=code_files[0].content if code_files else "",
            language=language,
            llm_config=getattr(self.llm_service, "config", None) if hasattr(self.llm_service, "config") else None,
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
            self.progress_callback(
                "pipeline_started",
                {
                    "pipeline_id": context.pipeline_id,
                    "file_count": len(code_files),
                },
            )

        try:
            # Wrap phase execution in timeout (ID 29 - CRITICAL)
            timeout = getattr(self.config, "timeout", 300)  # Default 5 minutes

            await asyncio.wait_for(
                self.phase_runner.execute_all_phases(context, code_files, self.pipeline, frames_to_execute),
                timeout=timeout,
            )

        except asyncio.TimeoutError:
            # ID 29 - Timeout handler
            self.pipeline.status = PipelineStatus.FAILED
            error_msg = f"Pipeline execution timeout after {timeout}s"
            context.errors.append(error_msg)
            logger.error("pipeline_timeout", timeout=timeout, pipeline_id=context.pipeline_id)
            raise RuntimeError(error_msg)

        except RuntimeError as e:
            self.pipeline.status = PipelineStatus.FAILED
            context.errors.append(str(e))
            if "Integrity check failed" in str(e):
                logger.error("integrity_check_failed", error=str(e))
                # Add a dummy result so CLI can show it
                return context
            logger.error("pipeline_runtime_error", error=str(e), pipeline_id=context.pipeline_id)
            raise e

        except Exception as e:
            # Global pipeline failure handler - ensures status is updated and error is traced.
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
            context.errors.append(f"Pipeline failed: {e!s}")
            raise

        finally:
            # Cleanup and state consistency - always run regardless of success/failure
            await self._cleanup_on_completion_async(context)
            self.post_processor.ensure_state_consistency(context, self.pipeline)

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

    async def _cleanup_on_completion_async(self, context: PipelineContext) -> None:
        """
        Cleanup resources after pipeline execution (success or failure).
        Always called in finally block to ensure cleanup happens.
        """
        try:
            # Close semantic search service if open
            if self.semantic_search_service and hasattr(self.semantic_search_service, "close"):
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
            if hasattr(self.phase_executor, "lsp_diagnostics") and self.phase_executor.lsp_diagnostics:
                try:
                    if hasattr(self.phase_executor.lsp_diagnostics, "shutdown"):
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
            if hasattr(self.frame_executor, "cleanup"):
                try:
                    await self.frame_executor.cleanup()
                except Exception as e:
                    logger.warning("frame_executor_cleanup_failed", error=str(e))

            logger.info("pipeline_cleanup_completed", pipeline_id=context.pipeline_id)

        except Exception as e:
            logger.error("cleanup_failed", pipeline_id=context.pipeline_id, error=str(e))

    async def _execute_lsp_diagnostics_async(self, context: PipelineContext) -> None:
        """Run LSP diagnostics phase (no-op stub, can be patched in tests)."""
