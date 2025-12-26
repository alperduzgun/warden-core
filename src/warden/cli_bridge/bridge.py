"""
Warden Bridge - Core IPC Service

Exposes Warden's Python backend functionality to the Ink CLI through JSON-RPC.
"""

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional, AsyncIterator
from datetime import datetime

from warden.cli_bridge.protocol import IPCError, ErrorCode

# Optional imports - graceful degradation if Warden validation framework not available
try:
    from warden.pipeline.application.orchestrator import PipelineOrchestrator
    from warden.pipeline.domain.models import PipelineConfig, PipelineResult
    from warden.validation.domain.frame import CodeFile
    from warden.llm.config import load_llm_config
    from warden.llm.factory import LlmClientFactory
    from warden.llm.types import LlmProvider
    from warden.shared.infrastructure.logging import get_logger

    WARDEN_AVAILABLE = True
    logger = get_logger(__name__)
except ImportError as e:
    WARDEN_AVAILABLE = False
    # Fallback logger using standard logging
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    logger.warning(f"Warden validation framework not available: {e}")


class WardenBridge:
    """
    Core bridge service exposing Warden functionality via IPC

    Methods exposed via JSON-RPC:
    - execute_pipeline(file_path: str) -> PipelineResult
    - get_config() -> ConfigData
    - analyze_with_llm(prompt: str, provider?: str) -> StreamingResponse
    - ping() -> pong (health check)
    - get_available_frames() -> List[FrameInfo]
    """

    def __init__(self, project_root: Optional[Path] = None, config_path: Optional[str] = None) -> None:
        """
        Initialize bridge service with persistent orchestrator (TUI pattern)

        Args:
            project_root: Project root directory (default: cwd)
            config_path: Optional config file path
        """
        self.project_root = project_root or Path.cwd()
        self.orchestrator = None
        self.active_config_name = "no-config"

        if not WARDEN_AVAILABLE:
            logger.warning("WardenBridge initialized without validation framework - limited functionality")
            self.llm_config = None
            self.llm_factory = None
            return

        self.llm_config = load_llm_config()
        self.llm_factory = LlmClientFactory(self.llm_config)

        # Initialize pipeline orchestrator (like TUI does)
        self._load_pipeline_config(config_path)

        # Validate frame consistency between config.yaml and rules.yaml
        self._validate_frame_consistency()

        logger.info(
            "warden_bridge_initialized",
            providers=len(self.llm_config.get_all_providers_chain()),
            orchestrator_ready=self.orchestrator is not None,
            config_name=self.active_config_name
        )

    def _load_pipeline_config(self, config_name: str) -> None:
        """Load pipeline configuration from .warden/config.yaml (TUI pattern)."""
        if not WARDEN_AVAILABLE:
            return

        try:
            import yaml
            from warden.pipeline.domain.models import PipelineConfig as PipelineOrchestratorConfig

            # Find config file
            config_file = self.project_root / ".warden" / "config.yaml"

            if not config_file.exists():
                logger.warning("no_config_found", path=str(config_file))
                self.active_config_name = "default"

                # Use default frames when no config
                frames = self._get_default_frames()
                self.orchestrator = PipelineOrchestrator(frames=frames, config=None)
                return

            # Parse YAML
            with open(config_file) as f:
                config_data = yaml.safe_load(f)

            # Extract frame list and frame-specific configs
            frame_names = config_data.get('frames', [])
            frame_config = config_data.get('frame_config', {})

            if not frame_names:
                logger.warning("no_frames_in_config")
                frames = self._get_default_frames()
                self.active_config_name = "default"
            else:
                # Load frames from list with their configs
                frames = self._load_frames_from_list(frame_names, frame_config)

                if not frames:
                    logger.warning("failed_to_load_frames")
                    frames = self._get_default_frames()
                    self.active_config_name = "default"
                else:
                    self.active_config_name = config_data.get('name', 'project-config')

            # Create pipeline orchestrator config
            settings = config_data.get('settings', {})
            pipeline_config = PipelineOrchestratorConfig(
                fail_fast=settings.get('fail_fast', True),
                timeout=settings.get('timeout', 300),
                frame_timeout=settings.get('timeout', 120),
                parallel_limit=4,
            )

            # Create orchestrator with frames and config
            self.orchestrator = PipelineOrchestrator(frames=frames, config=pipeline_config)
            logger.info("pipeline_loaded", config_name=self.active_config_name, frame_count=len(frames))

        except Exception as e:
            # Log error but don't crash - use default frames
            logger.error("pipeline_loading_error", error=str(e))
            self.active_config_name = "error-fallback"

            # Fallback to default frames
            try:
                frames = self._get_default_frames()
                self.orchestrator = PipelineOrchestrator(frames=frames, config=None)
            except Exception:
                self.orchestrator = None

    def _validate_frame_consistency(self) -> None:
        """Validate frame IDs are consistent between config.yaml and rules.yaml"""
        try:
            from warden.cli_bridge.config_manager import ConfigManager

            config_mgr = ConfigManager(self.project_root)
            validation_result = config_mgr.validate_frame_consistency()

            if not validation_result.get("valid"):
                # Log warnings but don't crash
                for warning in validation_result.get("warnings", []):
                    logger.warning(f"Frame consistency: {warning}")
            else:
                logger.info("Frame consistency validation passed")

        except Exception as e:
            # Don't crash on validation errors, just log
            logger.warning(f"Frame consistency validation failed: {e}")

    def _get_default_frames(self) -> list:
        """Get default validation frames when no config is found (TUI pattern)."""
        from warden.validation.frames import (
            SecurityFrame,
            ChaosFrame,
            ArchitecturalConsistencyFrame,
            OrphanFrame,
        )

        return [
            SecurityFrame(),
            ChaosFrame(),
            ArchitecturalConsistencyFrame(),
            OrphanFrame(),
        ]

    def _load_frames_from_list(self, frame_names: list, frame_config: dict = None) -> list:
        """
        Load validation frames from frame name list (TUI pattern).

        Args:
            frame_names: List of frame names (e.g., ['security', 'chaos', 'orphan'])
            frame_config: Frame-specific configurations from config.yaml

        Returns:
            List of initialized ValidationFrame instances
        """
        from warden.validation.frames import (
            SecurityFrame,
            ChaosFrame,
            ArchitecturalConsistencyFrame,
            ProjectArchitectureFrame,
            GitChangesFrame,
            OrphanFrame,
            FuzzFrame,
            PropertyFrame,
            StressFrame,
        )

        if frame_config is None:
            frame_config = {}

        # Map frame names to frame classes
        frame_map = {
            'security': SecurityFrame,
            'chaos': ChaosFrame,
            'architectural': ArchitecturalConsistencyFrame,
            'architecturalconsistency': ArchitecturalConsistencyFrame,
            'project_architecture': ProjectArchitectureFrame,
            'projectarchitecture': ProjectArchitectureFrame,
            'gitchanges': GitChangesFrame,
            'orphan': OrphanFrame,
            'fuzz': FuzzFrame,
            'property': PropertyFrame,
            'stress': StressFrame,
        }

        frames = []

        # Load each frame by name with its config
        for frame_name in frame_names:
            if frame_name in frame_map:
                # Get frame-specific config
                config = frame_config.get(frame_name, {})
                frames.append(frame_map[frame_name](config=config))
            else:
                logger.warning("unknown_frame", frame_name=frame_name)

        return frames

    async def execute_pipeline(self, file_path: str, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Execute validation pipeline on a file using persistent orchestrator.

        Args:
            file_path: Path to file to validate
            config: Optional pipeline configuration override

        Returns:
            Dictionary containing pipeline results

        Raises:
            IPCError: If execution fails
        """
        if not WARDEN_AVAILABLE:
            raise IPCError(
                code=ErrorCode.INTERNAL_ERROR,
                message="Warden validation framework not available",
                data={"feature": "execute_pipeline", "requires": "warden.pipeline"},
            )

        if not self.orchestrator:
            raise IPCError(
                code=ErrorCode.INTERNAL_ERROR,
                message="Pipeline orchestrator not initialized",
                data={"hint": "Check config loading in bridge initialization"},
            )

        try:
            logger.info("execute_pipeline_called", file_path=file_path)

            # Validate file exists
            path = Path(file_path)
            if not path.exists():
                raise IPCError(
                    code=ErrorCode.FILE_NOT_FOUND,
                    message=f"File not found: {file_path}",
                    data={"file_path": file_path},
                )

            # Create code file
            code_file = CodeFile(
                path=str(path.absolute()),
                content=path.read_text(encoding="utf-8"),
                language=self._detect_language(path),
            )

            # Execute pipeline with persistent orchestrator
            result = await self.orchestrator.execute([code_file])

            # Convert to serializable dict
            return self._serialize_pipeline_result(result)

        except IPCError:
            raise
        except Exception as e:
            logger.error("execute_pipeline_failed", error=str(e), file_path=file_path)
            raise IPCError(
                code=ErrorCode.PIPELINE_EXECUTION_ERROR,
                message=f"Pipeline execution failed: {str(e)}",
                data={"file_path": file_path, "error_type": type(e).__name__},
            )

    async def execute_pipeline_stream(self, file_path: str, config: Optional[Dict[str, Any]] = None) -> AsyncIterator[Dict[str, Any]]:
        """
        Execute validation pipeline on a file with streaming progress updates.

        Real-time streaming using asyncio.Queue for immediate event delivery.

        Args:
            file_path: Path to file to validate
            config: Optional pipeline configuration override

        Yields:
            Progress updates and final result as JSON events:
            - {"type": "progress", "event": "pipeline_started", "data": {...}}
            - {"type": "progress", "event": "frame_started", "data": {...}}
            - {"type": "progress", "event": "frame_completed", "data": {...}}
            - {"type": "result", "data": {...}}

        Raises:
            IPCError: If execution fails
        """
        if not WARDEN_AVAILABLE:
            raise IPCError(
                code=ErrorCode.INTERNAL_ERROR,
                message="Warden validation framework not available",
                data={"feature": "execute_pipeline_stream", "requires": "warden.pipeline"},
            )

        if not self.orchestrator:
            raise IPCError(
                code=ErrorCode.INTERNAL_ERROR,
                message="Pipeline orchestrator not initialized",
                data={"hint": "Check config loading in bridge initialization"},
            )

        try:
            logger.info("execute_pipeline_stream_called", file_path=file_path)

            # Validate file exists
            path = Path(file_path)
            if not path.exists():
                raise IPCError(
                    code=ErrorCode.FILE_NOT_FOUND,
                    message=f"File not found: {file_path}",
                    data={"file_path": file_path},
                )

            # Create code file
            code_file = CodeFile(
                path=str(path.absolute()),
                content=path.read_text(encoding="utf-8"),
                language=self._detect_language(path),
            )

            # Create async queue for real-time progress streaming
            progress_queue: asyncio.Queue = asyncio.Queue()
            pipeline_done = asyncio.Event()
            pipeline_error: Optional[Exception] = None

            # Set up progress callback to enqueue events
            def progress_callback(event: str, data: dict) -> None:
                """Capture and enqueue progress events immediately."""
                try:
                    # Non-blocking put for real-time streaming
                    progress_queue.put_nowait({"type": "progress", "event": event, "data": data})
                except Exception as e:
                    logger.warning("progress_callback_error", error=str(e))

            # Set callback on orchestrator temporarily
            original_callback = self.orchestrator.progress_callback
            self.orchestrator.progress_callback = progress_callback

            async def run_pipeline():
                """Run pipeline in background task."""
                nonlocal pipeline_error
                try:
                    result = await self.orchestrator.execute([code_file])
                    # Enqueue final result
                    await progress_queue.put({"type": "result", "data": self._serialize_pipeline_result(result)})
                except Exception as e:
                    pipeline_error = e
                finally:
                    pipeline_done.set()

            # Start pipeline in background
            pipeline_task = asyncio.create_task(run_pipeline())

            try:
                # Yield events as they arrive
                while not pipeline_done.is_set() or not progress_queue.empty():
                    try:
                        # Wait for next event with timeout to check pipeline status
                        event = await asyncio.wait_for(progress_queue.get(), timeout=0.1)
                        yield event

                        # If this was the result, we're done
                        if event.get("type") == "result":
                            break
                    except asyncio.TimeoutError:
                        # No event yet, check if pipeline failed
                        if pipeline_error:
                            raise pipeline_error
                        continue

                # Wait for pipeline to complete
                await pipeline_task

                # Check for errors
                if pipeline_error:
                    raise pipeline_error

            finally:
                # Restore original callback
                self.orchestrator.progress_callback = original_callback

                # Cancel pipeline task if still running
                if not pipeline_task.done():
                    pipeline_task.cancel()
                    try:
                        await pipeline_task
                    except asyncio.CancelledError:
                        pass

        except IPCError:
            raise
        except Exception as e:
            logger.error("execute_pipeline_stream_failed", error=str(e), file_path=file_path)
            raise IPCError(
                code=ErrorCode.PIPELINE_EXECUTION_ERROR,
                message=f"Pipeline stream failed: {str(e)}",
                data={"file_path": file_path, "error_type": type(e).__name__},
            )

    async def get_config(self) -> Dict[str, Any]:
        """
        Get Warden configuration

        Returns:
            Configuration data including LLM providers, frames, etc.
        """
        if not WARDEN_AVAILABLE:
            # Return minimal config without validation framework
            return {
                "version": "0.1.0",
                "llm_providers": [],
                "default_provider": "none",
                "frames": [],
                "total_frames": 0,
                "warning": "Warden validation framework not available",
            }

        try:
            logger.info("get_config_called")

            # Get LLM provider status
            providers = []
            for provider in self.llm_config.get_all_providers_chain():
                config = self.llm_config.get_provider_config(provider)
                if config and config.enabled:
                    providers.append({
                        "name": provider.value,
                        "model": config.default_model,
                        "endpoint": config.endpoint or "default",
                        "enabled": config.enabled,
                    })

            # Get available frames from orchestrator
            frame_info = []
            if self.orchestrator and self.orchestrator.frames:
                frame_info = [
                    {
                        "id": frame.frame_id,
                        "name": frame.name,
                        "description": frame.description,
                        "priority": frame.priority.name,
                        "is_blocker": frame.is_blocker,
                    }
                    for frame in self.orchestrator.frames
                ]

            return {
                "version": "0.1.0",
                "llm_providers": providers,
                "default_provider": self.llm_config.default_provider.value,
                "frames": frame_info,
                "total_frames": len(frame_info),
                "config_name": self.active_config_name,
            }

        except Exception as e:
            logger.error("get_config_failed", error=str(e))
            raise IPCError(
                code=ErrorCode.CONFIGURATION_ERROR,
                message=f"Failed to get configuration: {str(e)}",
                data={"error_type": type(e).__name__},
            )

    async def analyze_with_llm(
        self, prompt: str, provider: Optional[str] = None, stream: bool = True
    ) -> AsyncIterator[str]:
        """
        Analyze code with LLM (streaming response)

        Args:
            prompt: Analysis prompt
            provider: Optional provider override (default: use configured default)
            stream: Whether to stream response (default: True)

        Yields:
            Streamed response chunks

        Raises:
            IPCError: If LLM analysis fails
        """
        if not WARDEN_AVAILABLE:
            raise IPCError(
                code=ErrorCode.INTERNAL_ERROR,
                message="Warden LLM integration not available",
                data={"feature": "analyze_with_llm", "requires": "warden.llm"},
            )

        try:
            logger.info("analyze_with_llm_called", provider=provider, stream=stream)

            # Get LLM provider
            llm_provider = None
            if provider:
                try:
                    llm_provider = LlmProvider(provider)
                except ValueError:
                    raise IPCError(
                        code=ErrorCode.INVALID_PARAMS,
                        message=f"Invalid provider: {provider}",
                        data={"valid_providers": [p.value for p in LlmProvider]},
                    )

            # Get LLM client
            llm_client = await self.llm_factory.get_provider(llm_provider or self.llm_config.default_provider)

            if not llm_client:
                raise IPCError(
                    code=ErrorCode.LLM_ERROR,
                    message="No LLM provider available",
                    data={"requested_provider": provider},
                )

            # Stream response
            if stream:
                async for chunk in llm_client.stream_completion(prompt):
                    yield chunk
            else:
                # Non-streaming response
                response = await llm_client.complete(prompt)
                yield response

        except IPCError:
            raise
        except Exception as e:
            logger.error("analyze_with_llm_failed", error=str(e), provider=provider)
            raise IPCError(
                code=ErrorCode.LLM_ERROR,
                message=f"LLM analysis failed: {str(e)}",
                data={"provider": provider, "error_type": type(e).__name__},
            )

    async def scan(self, path: str) -> Dict[str, Any]:
        """
        Scan a directory or file for validation

        Args:
            path: Directory or file path to scan

        Returns:
            Scan results with found files and issues

        Raises:
            IPCError: If scan fails
        """
        if not WARDEN_AVAILABLE:
            raise IPCError(
                code=ErrorCode.INTERNAL_ERROR,
                message="Warden validation framework not available",
                data={"feature": "scan", "requires": "warden.pipeline"},
            )

        try:
            logger.info("scan_called", path=path)

            # Resolve to absolute path (handles relative paths like cli/src)
            scan_path = Path(path).resolve()

            # Validate path exists
            if not scan_path.exists():
                raise IPCError(
                    code=ErrorCode.FILE_NOT_FOUND,
                    message=f"Path not found: {path}",
                    data={"path": str(scan_path)},
                )

            # Find all code files in the path
            files_to_scan = []
            if scan_path.is_file():
                files_to_scan = [scan_path]
            else:
                # Scan directory for code files
                extensions = {'.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.cs', '.go', '.rs', '.cpp', '.c', '.h'}
                for ext in extensions:
                    files_to_scan.extend(scan_path.rglob(f"*{ext}"))

            logger.info("scan_files_found", count=len(files_to_scan), path=path)

            # Safe relative path conversion (fallback to absolute if relative fails)
            file_list = []
            for f in files_to_scan[:50]:  # Limit to first 50
                try:
                    file_list.append(str(f.relative_to(scan_path)))
                except ValueError:
                    # Can't make relative, use absolute
                    file_list.append(str(f))

            return {
                "path": str(scan_path.absolute()),
                "total_files": len(files_to_scan),
                "files": file_list,
                "message": f"Found {len(files_to_scan)} files to scan",
            }

        except IPCError:
            raise
        except Exception as e:
            logger.error("scan_failed", error=str(e), path=path)
            raise IPCError(
                code=ErrorCode.INTERNAL_ERROR,
                message=f"Scan failed: {str(e)}",
                data={"path": path, "error_type": type(e).__name__},
            )

    async def analyze(self, filePath: str) -> Dict[str, Any]:
        """
        Analyze a single file with validation pipeline

        Args:
            filePath: Path to file to analyze

        Returns:
            Analysis results

        Raises:
            IPCError: If analysis fails
        """
        # Delegate to execute_pipeline
        return await self.execute_pipeline(filePath)

    async def ping(self) -> Dict[str, str]:
        """
        Health check endpoint

        Returns:
            Pong response with timestamp
        """
        return {
            "status": "ok",
            "message": "pong",
            "timestamp": datetime.utcnow().isoformat(),
        }

    async def get_available_frames(self) -> List[Dict[str, Any]]:
        """
        Get list of available validation frames from orchestrator

        Returns:
            List of frame information (empty list if framework not available)
        """
        if not WARDEN_AVAILABLE:
            logger.warning("get_available_frames called but validation framework not available")
            return []

        if not self.orchestrator:
            logger.warning("get_available_frames called but orchestrator not initialized")
            return []

        try:
            logger.info("get_available_frames_called")

            # Import config manager to get frame enabled status
            from warden.cli_bridge.config_manager import ConfigManager
            config_mgr = ConfigManager(self.project_root)

            frames_info = []
            for frame in self.orchestrator.frames:
                # Get enabled status from config (default True if not configured)
                enabled = config_mgr.get_frame_status(frame.frame_id)
                if enabled is None:
                    enabled = True  # Default to enabled if not in config

                frames_info.append({
                    "id": frame.frame_id,
                    "name": frame.name,
                    "description": frame.description,
                    "priority": frame.priority.name,
                    "is_blocker": frame.is_blocker,
                    "enabled": enabled,
                    "tags": getattr(frame, "tags", []),
                })

            return frames_info

        except Exception as e:
            logger.error("get_available_frames_failed", error=str(e))
            raise IPCError(
                code=ErrorCode.INTERNAL_ERROR,
                message=f"Failed to get frames: {str(e)}",
                data={"error_type": type(e).__name__},
            )

    async def get_available_providers(self) -> List[Dict[str, Any]]:
        """
        Get installed AST providers with metadata.

        Returns:
            List of provider information dictionaries (camelCase for Panel compatibility)
        """
        try:
            logger.info("get_available_providers_called")

            # Import AST provider registry
            from warden.ast.application.provider_registry import ASTProviderRegistry

            # Initialize registry and discover providers
            registry = ASTProviderRegistry()
            await registry.discover_providers()

            # Get all providers
            providers = []
            for metadata in registry.list_providers():
                providers.append({
                    "name": metadata.name,
                    "languages": [lang.value for lang in metadata.supported_languages],
                    "priority": metadata.priority.name,
                    "version": metadata.version,
                    "source": "built-in" if metadata.name in ["Python AST", "Tree-sitter"] else "PyPI",
                })

            logger.info("get_available_providers_success", provider_count=len(providers))
            return providers

        except Exception as e:
            logger.error("get_available_providers_failed", error=str(e))
            raise IPCError(
                code=ErrorCode.INTERNAL_ERROR,
                message=f"Failed to get providers: {str(e)}",
                data={"error_type": type(e).__name__},
            )

    async def test_provider(self, language: str) -> Dict[str, Any]:
        """
        Test if a language provider is available and functional.

        Args:
            language: Programming language name (e.g., 'python', 'java')

        Returns:
            Test result with provider details (camelCase for Panel compatibility)
        """
        try:
            logger.info("test_provider_called", language=language)

            # Import AST dependencies
            from warden.ast.application.provider_registry import ASTProviderRegistry
            from warden.ast.domain.enums import CodeLanguage

            # Parse language enum
            try:
                lang = CodeLanguage(language.lower())
            except ValueError:
                # Invalid language
                logger.warning("test_provider_invalid_language", language=language)
                return {
                    "available": False,
                    "error": f"Unknown language: {language}",
                    "supportedLanguages": [lang.value for lang in CodeLanguage if lang != CodeLanguage.UNKNOWN],
                }

            # Initialize registry and discover providers
            registry = ASTProviderRegistry()
            await registry.discover_providers()

            # Get provider for language
            provider = registry.get_provider(lang)

            if not provider:
                # No provider found
                logger.warning("test_provider_not_found", language=language)
                return {
                    "available": False,
                    "language": language,
                }

            # Provider found - validate it
            is_valid = await provider.validate()

            if is_valid:
                # Provider is functional
                logger.info("test_provider_success", language=language, provider=provider.metadata.name)
                return {
                    "available": True,
                    "providerName": provider.metadata.name,
                    "priority": provider.metadata.priority.name,
                    "version": provider.metadata.version,
                    "validated": True,
                }
            else:
                # Provider found but validation failed
                logger.warning("test_provider_validation_failed", language=language, provider=provider.metadata.name)
                return {
                    "available": True,
                    "providerName": provider.metadata.name,
                    "priority": provider.metadata.priority.name,
                    "version": provider.metadata.version,
                    "validated": False,
                }

        except Exception as e:
            logger.error("test_provider_failed", language=language, error=str(e))
            raise IPCError(
                code=ErrorCode.INTERNAL_ERROR,
                message=f"Provider test failed: {str(e)}",
                data={"language": language, "error_type": type(e).__name__},
            )

    def _detect_language(self, path: Path) -> str:
        """
        Detect programming language from file extension

        Args:
            path: File path

        Returns:
            Language identifier
        """
        extension_map = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".jsx": "javascript",
            ".tsx": "typescript",
            ".java": "java",
            ".cs": "csharp",
            ".go": "go",
            ".rs": "rust",
            ".cpp": "cpp",
            ".c": "c",
            ".h": "c",
            ".hpp": "cpp",
            ".rb": "ruby",
            ".php": "php",
            ".swift": "swift",
            ".kt": "kotlin",
            ".scala": "scala",
        }
        return extension_map.get(path.suffix.lower(), "unknown")

    def _serialize_pipeline_result(self, result: "PipelineResult") -> Dict[str, Any]:
        """
        Convert PipelineResult to serializable dictionary

        Args:
            result: Pipeline result

        Returns:
            Serializable dictionary
        """
        return {
            "pipeline_id": result.pipeline_id,
            "pipeline_name": result.pipeline_name,
            "status": result.status.value,
            "duration": result.duration,
            "total_frames": result.total_frames,
            "frames_passed": result.frames_passed,
            "frames_failed": result.frames_failed,
            "frames_skipped": result.frames_skipped,
            "total_findings": result.total_findings,
            "critical_findings": result.critical_findings,
            "high_findings": result.high_findings,
            "medium_findings": result.medium_findings,
            "low_findings": result.low_findings,
            "frame_results": [
                {
                    "frame_id": fr.frame_id,
                    "frame_name": fr.frame_name,
                    "status": fr.status,
                    "duration": fr.duration,
                    "issues_found": fr.issues_found,
                    "is_blocker": fr.is_blocker,
                    "findings": [
                        {
                            "severity": getattr(f, "severity", "unknown"),
                            "message": getattr(f, "message", str(f)),
                            "line": getattr(f, "line_number", getattr(f, "line", None)),  # Support both line_number and line
                            "column": getattr(f, "column", None),
                            "code": getattr(f, "code", None),
                            "file": getattr(f, "file_path", getattr(f, "file", None)),  # Map file_path to file for CLI
                        }
                        for f in fr.findings
                    ],
                }
                for fr in result.frame_results
            ],
            "metadata": result.metadata,
        }

    async def update_frame_status(self, frame_id: str, enabled: bool) -> Dict[str, Any]:
        """
        Update frame enabled status in config

        Args:
            frame_id: Frame identifier (e.g., 'security', 'chaos')
            enabled: Whether frame should be enabled

        Returns:
            Updated frame configuration

        Raises:
            IPCError: If update fails
        """
        try:
            logger.info("update_frame_status_called", frame_id=frame_id, enabled=enabled)

            # Import config manager
            from warden.cli_bridge.config_manager import ConfigManager

            # Create config manager with project root
            config_mgr = ConfigManager(self.project_root)

            # Update frame status
            result = config_mgr.update_frame_status(frame_id, enabled)

            logger.info("update_frame_status_success", frame_id=frame_id, enabled=enabled)

            return {
                "success": True,
                "frame_id": result["frame_id"],
                "enabled": result["enabled"],
                "message": f"Frame '{frame_id}' {'enabled' if enabled else 'disabled'}",
            }

        except FileNotFoundError as e:
            logger.error("update_frame_status_config_not_found", error=str(e))
            raise IPCError(
                code=ErrorCode.FILE_NOT_FOUND,
                message=f"Config file not found: {str(e)}",
                data={"frame_id": frame_id},
            )

        except Exception as e:
            logger.error("update_frame_status_failed", frame_id=frame_id, error=str(e))
            raise IPCError(
                code=ErrorCode.INTERNAL_ERROR,
                message=f"Failed to update frame status: {str(e)}",
                data={"frame_id": frame_id, "error_type": type(e).__name__},
            )
