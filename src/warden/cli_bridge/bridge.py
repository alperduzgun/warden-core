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
    from warden.pipeline.application.phase_orchestrator import PhaseOrchestrator
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

        try:
            self.llm_config = load_llm_config()
            self.llm_factory = LlmClientFactory(self.llm_config)
        except Exception as e:
            logger.warning("LLM config loading failed, continuing without LLM", error=str(e))
            self.llm_config = None
            self.llm_factory = None

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

    def _load_pipeline_config(self, config_path: Optional[str] = None) -> None:
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
                # Create LLM service if factory is available
                if self.llm_factory and self.llm_config:
                    llm_service = self.llm_factory.create_client(self.llm_config.default_provider)
                else:
                    llm_service = None
                self.orchestrator = PhaseOrchestrator(frames=frames, config=None, llm_service=llm_service)
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
                frame_timeout=settings.get('frame_timeout', 120),
                parallel_limit=4,
                enable_pre_analysis=settings.get('enable_pre_analysis', True),
                enable_analysis=settings.get('enable_analysis', True),
                enable_classification=True,  # ALWAYS ENABLED - Classification is critical for intelligent frame selection
                enable_validation=settings.get('enable_validation', True),
                enable_fortification=settings.get('enable_fortification', True),
                enable_cleaning=settings.get('enable_cleaning', True),
                pre_analysis_config=settings.get('pre_analysis_config', None),
            )

            # Create orchestrator with frames, config, and LLM service
            if self.llm_factory and self.llm_config:
                llm_service = self.llm_factory.create_client(self.llm_config.default_provider)
            else:
                llm_service = None
            self.orchestrator = PhaseOrchestrator(frames=frames, config=pipeline_config, llm_service=llm_service)
            logger.info("pipeline_loaded", config_name=self.active_config_name, frame_count=len(frames), has_llm=llm_service is not None)

        except Exception as e:
            # Log error but don't crash - use default frames
            logger.error("pipeline_loading_error", error=str(e))
            self.active_config_name = "error-fallback"

            # Fallback to default frames
            try:
                frames = self._get_default_frames()
                if self.llm_factory and self.llm_config:
                    llm_service = self.llm_factory.create_client(self.llm_config.default_provider)
                else:
                    llm_service = None
                self.orchestrator = PhaseOrchestrator(frames=frames, config=None, llm_service=llm_service)
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
        Load validation frames from frame name list using FrameRegistry.

        Supports both built-in and custom frames through frame discovery.

        Args:
            frame_names: List of frame names (e.g., ['security', 'chaos', 'env-security'])
            frame_config: Frame-specific configurations from config.yaml

        Returns:
            List of initialized ValidationFrame instances
        """
        from warden.validation.infrastructure.frame_registry import FrameRegistry

        if frame_config is None:
            frame_config = {}

        # Use FrameRegistry to discover ALL frames (built-in + custom)
        registry = FrameRegistry()
        all_frames = registry.discover_all()

        logger.info("frame_discovery_complete", total=len(registry.registered_frames))

        frames = []

        # Load each requested frame by name
        for frame_name in frame_names:
            # Normalize frame name (remove hyphens for lookup)
            normalized_name = frame_name.replace('-', '').replace('_', '').lower()

            # Try to find frame in registry
            frame_class = None
            for fid, cls in registry.registered_frames.items():
                if fid == normalized_name:
                    frame_class = cls
                    break

            # Special case: 'architectural' should map to 'architecturalconsistency'
            if not frame_class and normalized_name == 'architectural':
                frame_class = registry.registered_frames.get('architecturalconsistency')

            # Also check metadata for original ID match (for custom frames)
            if not frame_class and frame_name in [meta.id for meta in registry.frame_metadata.values()]:
                for fid, meta in registry.frame_metadata.items():
                    if meta.id == frame_name:
                        frame_class = registry.registered_frames.get(fid)
                        break

            if frame_class:
                # Get frame-specific config
                config = frame_config.get(frame_name, {})

                # Instantiate frame with config
                try:
                    frames.append(frame_class(config=config))
                    logger.info("frame_loaded", frame_name=frame_name, frame_class=frame_class.__name__)
                except Exception as e:
                    logger.error("frame_instantiation_failed", frame_name=frame_name, error=str(e))
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

            # Validate file exists and is a file (not directory)
            path = Path(file_path)
            if not path.exists():
                raise IPCError(
                    code=ErrorCode.FILE_NOT_FOUND,
                    message=f"File not found: {file_path}",
                    data={"file_path": file_path},
                )

            if not path.is_file():
                raise IPCError(
                    code=ErrorCode.INVALID_PARAMS,
                    message=f"Path is not a file: {file_path}",
                    data={"file_path": file_path, "is_directory": path.is_dir()},
                )

            # Create code file
            code_file = CodeFile(
                path=str(path.absolute()),
                content=path.read_text(encoding="utf-8"),
                language=self._detect_language(path),
            )

            # Execute pipeline with persistent orchestrator (now returns tuple)
            result, context = await self.orchestrator.execute([code_file])

            # Convert to serializable dict and include context summary
            serialized_result = self._serialize_pipeline_result(result)
            serialized_result["context_summary"] = context.get_summary()

            # Add LLM usage information
            llm_info = {
                "llm_enabled": self.orchestrator.llm_service is not None,
                "llm_provider": self.llm_config.default_provider.value if self.llm_config else "none",
                "phases_with_llm": []
            }

            # Check which phases used LLM from context
            if hasattr(context, 'phase_results'):
                for phase_name, phase_data in context.phase_results.items():
                    if isinstance(phase_data, dict):
                        # Check if phase used LLM (typically phases that took longer)
                        if phase_name in ['PRE_ANALYSIS', 'ANALYSIS', 'CLASSIFICATION']:
                            llm_info["phases_with_llm"].append(phase_name)

            # Add LLM analysis details if available
            if hasattr(context, 'quality_metrics') and context.quality_metrics:
                llm_info["llm_quality_score"] = getattr(context.quality_metrics, 'overall_score', None)
                llm_info["llm_confidence"] = getattr(context, 'quality_confidence', None)

            if hasattr(context, 'classification_reasoning'):
                llm_info["llm_reasoning"] = context.classification_reasoning[:200] if context.classification_reasoning else None

            serialized_result["llm_analysis"] = llm_info

            return serialized_result

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

            # Validate file exists and is a file (not directory)
            path = Path(file_path)
            if not path.exists():
                raise IPCError(
                    code=ErrorCode.FILE_NOT_FOUND,
                    message=f"File not found: {file_path}",
                    data={"file_path": file_path},
                )

            # If it's a directory, find the first code file
            if path.is_dir():
                code_extensions = ['.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.cs', '.go', '.rs', '.cpp', '.c', '.h']
                first_file = None
                for ext in code_extensions:
                    files = list(path.glob(f"*{ext}"))
                    # Skip files in .warden directory
                    files = [f for f in files if '.warden' not in f.parts and f.is_file()]
                    if files:
                        first_file = files[0]
                        break

                if first_file:
                    logger.info("directory_provided_using_first_file", directory=str(path), file=str(first_file))
                    path = first_file
                else:
                    raise IPCError(
                        code=ErrorCode.INVALID_PARAMS,
                        message=f"No code files found in directory: {file_path}",
                        data={"file_path": file_path, "is_directory": True},
                    )
            elif not path.is_file():
                raise IPCError(
                    code=ErrorCode.INVALID_PARAMS,
                    message=f"Path is neither a file nor a directory: {file_path}",
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
                    result, context = await self.orchestrator.execute([code_file])
                    # Enqueue final result with context
                    serialized_result = self._serialize_pipeline_result(result)
                    serialized_result["context_summary"] = context.get_summary()
                    await progress_queue.put({"type": "result", "data": serialized_result})
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

        if not self.orchestrator:
            raise IPCError(
                code=ErrorCode.INTERNAL_ERROR,
                message="Pipeline orchestrator not initialized",
                data={"hint": "Check config loading in bridge initialization"},
            )

        try:
            logger.info("scan_called", path=path)

            import time
            start_time = time.time()

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
                    # Find all files with this extension, filtering out directories
                    for file_path in scan_path.rglob(f"*{ext}"):
                        # Skip files in .warden directory and its subdirectories
                        if '.warden' in file_path.parts:
                            continue
                        # Skip hidden directories and __pycache__
                        if any(part.startswith('.') or part == '__pycache__' for part in file_path.parts):
                            continue
                        # Only add if it's actually a file, not a directory
                        if file_path.is_file():
                            files_to_scan.append(file_path)

            logger.info("scan_files_found", count=len(files_to_scan), path=path)

            # Limit to first 10 files for performance
            files_to_scan = files_to_scan[:10]

            # Collect all issues from scanning
            all_issues = []
            files_scanned = 0

            # Scan each file
            for file_path in files_to_scan:
                try:
                    # Skip if not a file (extra safety check)
                    if not file_path.is_file():
                        logger.warning("skipping_non_file", path=str(file_path))
                        continue

                    # Create code file
                    code_file = CodeFile(
                        path=str(file_path.absolute()),
                        content=file_path.read_text(encoding="utf-8"),
                        language=self._detect_language(file_path),
                    )

                    # Execute pipeline on this file
                    result, context = await self.orchestrator.execute([code_file])
                    files_scanned += 1

                    # Extract issues from frame results
                    for frame_result in result.frame_results:
                        for finding in frame_result.findings:
                            all_issues.append({
                                "id": f"{frame_result.frame_id}_{len(all_issues)}",
                                "filePath": str(file_path),
                                "line": getattr(finding, "line_number", getattr(finding, "line", 0)),
                                "column": getattr(finding, "column", 0),
                                "severity": getattr(finding, "severity", "medium").lower(),
                                "message": getattr(finding, "message", str(finding)),
                                "rule": getattr(finding, "code", "unknown"),
                                "frame": frame_result.frame_id,
                            })

                except Exception as e:
                    logger.warning("scan_file_failed", file=str(file_path), error=str(e))
                    continue

            # Calculate summary
            summary = {
                "critical": sum(1 for i in all_issues if i["severity"] == "critical"),
                "high": sum(1 for i in all_issues if i["severity"] == "high"),
                "medium": sum(1 for i in all_issues if i["severity"] == "medium"),
                "low": sum(1 for i in all_issues if i["severity"] == "low"),
            }

            duration_ms = int((time.time() - start_time) * 1000)

            # Add LLM information
            llm_info = {
                "llm_enabled": self.orchestrator.llm_service is not None,
                "llm_provider": self.llm_config.default_provider.value if self.llm_config and self.orchestrator.llm_service else "none",
                "phases_with_llm": ["PRE_ANALYSIS", "ANALYSIS", "CLASSIFICATION"] if self.orchestrator.llm_service else []
            }

            return {
                "success": True,
                "filesScanned": files_scanned,
                "issues": all_issues,
                "duration": duration_ms,
                "summary": summary,
                "llm_analysis": llm_info,
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

    def _serialize_pipeline_result(self, result: PipelineResult) -> Dict[str, Any]:
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
