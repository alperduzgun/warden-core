"""
Warden gRPC Server

Async gRPC server wrapping WardenBridge for C# Panel communication.
"""

import asyncio
import time
import psutil
from pathlib import Path
from typing import Optional, AsyncIterator
from datetime import datetime

import grpc
from grpc import aio

# Import generated protobuf code (will be generated)
try:
    from warden.grpc.generated import warden_pb2, warden_pb2_grpc
except ImportError:
    # Fallback for development before code generation
    warden_pb2 = None
    warden_pb2_grpc = None

# gRPC Reflection (for Postman auto-discovery)
try:
    from grpc_reflection.v1alpha import reflection
except ImportError:
    reflection = None

# Import Warden components
from warden.cli_bridge.bridge import WardenBridge

# Optional: structured logging
try:
    from warden.shared.infrastructure.logging import get_logger
    logger = get_logger(__name__)
except ImportError:
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)


class WardenServicer(warden_pb2_grpc.WardenServiceServicer if warden_pb2_grpc else object):
    """
    gRPC service implementation wrapping WardenBridge.

    All methods delegate to the bridge for actual business logic.
    """

    def __init__(self, bridge: Optional[WardenBridge] = None, project_root: Optional[Path] = None):
        """
        Initialize servicer.

        Args:
            bridge: Existing WardenBridge instance (creates new if None)
            project_root: Project root path for bridge initialization
        """
        self.bridge = bridge or WardenBridge(project_root=project_root or Path.cwd())
        self.start_time = datetime.now()
        self.total_scans = 0
        self.total_findings = 0
        logger.info("grpc_servicer_initialized")

    # ─────────────────────────────────────────────────────────────────────
    # Pipeline Operations
    # ─────────────────────────────────────────────────────────────────────

    async def ExecutePipeline(self, request, context) -> "warden_pb2.PipelineResult":
        """Execute full validation pipeline."""
        logger.info("grpc_execute_pipeline", path=request.path, frames=list(request.frames))

        start_time = time.time()

        try:
            # Convert proto request to bridge params
            frames = list(request.frames) if request.frames else None

            # Execute via bridge
            result = await self.bridge.execute_pipeline(
                path=request.path,
                frames=frames
            )

            duration_ms = int((time.time() - start_time) * 1000)
            self.total_scans += 1

            # Convert to proto response
            response = warden_pb2.PipelineResult(
                success=result.get("success", False),
                run_id=result.get("run_id", ""),
                total_findings=result.get("total_findings", 0),
                critical_count=result.get("critical_count", 0),
                high_count=result.get("high_count", 0),
                medium_count=result.get("medium_count", 0),
                low_count=result.get("low_count", 0),
                duration_ms=duration_ms,
                frames_executed=result.get("frames_executed", []),
                error_message=result.get("error", "")
            )

            # Add findings
            for finding in result.get("findings", []):
                response.findings.append(self._convert_finding(finding))

            # Add fortifications
            for fort in result.get("fortifications", []):
                response.fortifications.append(self._convert_fortification(fort))

            # Add cleanings
            for clean in result.get("cleanings", []):
                response.cleanings.append(self._convert_cleaning(clean))

            self.total_findings += response.total_findings
            logger.info("grpc_pipeline_complete",
                       findings=response.total_findings,
                       duration_ms=duration_ms)

            return response

        except Exception as e:
            logger.error("grpc_pipeline_error", error=str(e))
            return warden_pb2.PipelineResult(
                success=False,
                error_message=str(e)
            )

    async def ExecutePipelineStream(self, request, context) -> AsyncIterator["warden_pb2.PipelineEvent"]:
        """Execute pipeline with streaming progress events."""
        logger.info("grpc_execute_pipeline_stream", path=request.path)

        try:
            # Send start event
            yield warden_pb2.PipelineEvent(
                event_type="pipeline_start",
                message=f"Starting pipeline for {request.path}",
                timestamp_ms=int(time.time() * 1000)
            )

            # Convert proto request to bridge params
            frames = list(request.frames) if request.frames else None

            # Execute via bridge with streaming
            async for event in self.bridge.execute_pipeline_stream(
                path=request.path,
                frames=frames
            ):
                # Convert bridge event to proto event
                proto_event = warden_pb2.PipelineEvent(
                    event_type=event.get("type", "progress"),
                    stage=event.get("stage", ""),
                    progress=event.get("progress", 0.0),
                    message=event.get("message", ""),
                    timestamp_ms=int(time.time() * 1000)
                )

                # Add finding if present
                if "finding" in event:
                    proto_event.finding.CopyFrom(self._convert_finding(event["finding"]))

                yield proto_event

            # Send complete event
            yield warden_pb2.PipelineEvent(
                event_type="pipeline_complete",
                progress=1.0,
                message="Pipeline completed",
                timestamp_ms=int(time.time() * 1000)
            )

        except Exception as e:
            logger.error("grpc_stream_error", error=str(e))
            yield warden_pb2.PipelineEvent(
                event_type="error",
                message=str(e),
                timestamp_ms=int(time.time() * 1000)
            )

    # ─────────────────────────────────────────────────────────────────────
    # LLM Operations
    # ─────────────────────────────────────────────────────────────────────

    async def AnalyzeWithLlm(self, request, context) -> "warden_pb2.LlmAnalyzeResult":
        """Analyze code with LLM."""
        logger.info("grpc_analyze_llm", provider=request.provider or "default")

        start_time = time.time()

        try:
            # Collect streaming response
            chunks = []
            provider_used = ""

            async for chunk in self.bridge.analyze_with_llm(
                code=request.code,
                prompt=request.prompt,
                provider=request.provider or None
            ):
                if chunk.get("type") == "chunk":
                    chunks.append(chunk.get("content", ""))
                elif chunk.get("type") == "complete":
                    provider_used = chunk.get("provider", "")

            duration_ms = int((time.time() - start_time) * 1000)

            return warden_pb2.LlmAnalyzeResult(
                success=True,
                response="".join(chunks),
                provider_used=provider_used,
                duration_ms=duration_ms
            )

        except Exception as e:
            logger.error("grpc_llm_error", error=str(e))
            return warden_pb2.LlmAnalyzeResult(
                success=False,
                error=warden_pb2.LlmError(
                    code="LLM_ERROR",
                    message=str(e)
                )
            )

    async def ClassifyCode(self, request, context) -> "warden_pb2.ClassifyResult":
        """Classify code to determine recommended frames."""
        logger.info("grpc_classify_code")

        try:
            result = await self.bridge.classify_code(
                code=request.code,
                file_path=request.file_path or None
            )

            return warden_pb2.ClassifyResult(
                has_async_operations=result.get("has_async_operations", False),
                has_user_input=result.get("has_user_input", False),
                has_database_operations=result.get("has_database_operations", False),
                has_network_calls=result.get("has_network_calls", False),
                has_file_operations=result.get("has_file_operations", False),
                has_authentication=result.get("has_authentication", False),
                has_cryptography=result.get("has_cryptography", False),
                detected_frameworks=result.get("detected_frameworks", []),
                recommended_frames=result.get("recommended_frames", []),
                confidence=result.get("confidence", 0.0)
            )

        except Exception as e:
            logger.error("grpc_classify_error", error=str(e))
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return warden_pb2.ClassifyResult()

    # ─────────────────────────────────────────────────────────────────────
    # Configuration
    # ─────────────────────────────────────────────────────────────────────

    async def GetAvailableFrames(self, request, context) -> "warden_pb2.FrameList":
        """Get available validation frames."""
        logger.info("grpc_get_frames")

        try:
            result = await self.bridge.get_available_frames()

            # Handle both dict and list formats from bridge
            frames = result if isinstance(result, list) else result.get("frames", [])

            response = warden_pb2.FrameList()
            for frame in frames:
                # Handle priority as int or string
                priority = frame.get("priority", 0)
                if isinstance(priority, str):
                    priority_map = {"critical": 1, "high": 2, "medium": 3, "low": 4, "info": 5}
                    priority = priority_map.get(priority.lower(), 0)

                response.frames.append(warden_pb2.Frame(
                    id=frame.get("id", ""),
                    name=frame.get("name", ""),
                    description=frame.get("description", ""),
                    priority=priority,
                    is_blocker=frame.get("is_blocker", False),
                    enabled=frame.get("enabled", True),
                    tags=frame.get("tags", [])
                ))

            return response

        except Exception as e:
            logger.error("grpc_frames_error", error=str(e))
            return warden_pb2.FrameList()

    async def GetAvailableProviders(self, request, context) -> "warden_pb2.ProviderList":
        """Get available LLM providers."""
        logger.info("grpc_get_providers")

        try:
            result = await self.bridge.get_available_providers()

            # Handle both dict and list formats from bridge
            if isinstance(result, list):
                providers = result
                default_provider = ""
            else:
                providers = result.get("providers", [])
                default_provider = result.get("default", "")

            response = warden_pb2.ProviderList(default_provider=default_provider)

            for provider in providers:
                response.providers.append(warden_pb2.Provider(
                    id=provider.get("id", provider.get("name", "")),
                    name=provider.get("name", ""),
                    available=provider.get("available", True),
                    is_default=provider.get("is_default", False),
                    status=provider.get("status", "ready")
                ))

            return response

        except Exception as e:
            logger.error("grpc_providers_error", error=str(e))
            return warden_pb2.ProviderList()

    async def GetConfiguration(self, request, context) -> "warden_pb2.ConfigurationResponse":
        """Get full configuration."""
        logger.info("grpc_get_config")

        try:
            config = await self.bridge.get_config()
            frames = await self.bridge.get_available_frames()
            providers_result = await self.bridge.get_available_providers()

            response = warden_pb2.ConfigurationResponse(
                project_root=str(self.bridge.project_root),
                config_file=config.get("config_file", ""),
                active_profile=config.get("active_profile", "default")
            )

            # Add frames - handle both dict and list formats
            frames_list = frames if isinstance(frames, list) else frames.get("frames", [])
            for frame in frames_list:
                # Handle priority as int or string
                priority = frame.get("priority", 0)
                if isinstance(priority, str):
                    priority_map = {"critical": 1, "high": 2, "medium": 3, "low": 4, "info": 5}
                    priority = priority_map.get(priority.lower(), 0)

                response.available_frames.frames.append(warden_pb2.Frame(
                    id=frame.get("id", ""),
                    name=frame.get("name", ""),
                    description=frame.get("description", ""),
                    priority=priority,
                    is_blocker=frame.get("is_blocker", False),
                    enabled=frame.get("enabled", True)
                ))

            # Add providers - handle both dict and list formats
            providers = providers_result if isinstance(providers_result, list) else providers_result.get("providers", [])
            for provider in providers:
                response.available_providers.providers.append(warden_pb2.Provider(
                    id=provider.get("id", provider.get("name", "")),
                    name=provider.get("name", ""),
                    available=provider.get("available", True),
                    is_default=provider.get("is_default", False)
                ))

            return response

        except Exception as e:
            logger.error("grpc_config_error", error=str(e))
            return warden_pb2.ConfigurationResponse()

    # ─────────────────────────────────────────────────────────────────────
    # Health & Status
    # ─────────────────────────────────────────────────────────────────────

    async def HealthCheck(self, request, context) -> "warden_pb2.HealthResponse":
        """Health check."""
        uptime = (datetime.now() - self.start_time).total_seconds()

        # Check components
        components = {
            "bridge": self.bridge is not None,
            "orchestrator": self.bridge.orchestrator is not None if self.bridge else False
        }

        # Check LLM availability
        try:
            providers = await self.bridge.get_available_providers()
            components["llm"] = any(p.get("available") for p in providers.get("providers", []))
        except Exception:
            components["llm"] = False

        return warden_pb2.HealthResponse(
            healthy=all(components.values()),
            version="1.0.0",
            uptime_seconds=int(uptime),
            components=components
        )

    async def GetStatus(self, request, context) -> "warden_pb2.StatusResponse":
        """Get server status."""
        process = psutil.Process()

        return warden_pb2.StatusResponse(
            running=True,
            active_pipelines=0,  # TODO: Track active pipelines
            total_scans=self.total_scans,
            total_findings=self.total_findings,
            memory_mb=int(process.memory_info().rss / 1024 / 1024),
            cpu_percent=process.cpu_percent()
        )

    # ─────────────────────────────────────────────────────────────────────
    # Helper Methods
    # ─────────────────────────────────────────────────────────────────────

    def _convert_finding(self, finding: dict) -> "warden_pb2.Finding":
        """Convert dict finding to proto Finding."""
        severity_map = {
            "critical": warden_pb2.CRITICAL,
            "high": warden_pb2.HIGH,
            "medium": warden_pb2.MEDIUM,
            "low": warden_pb2.LOW,
            "info": warden_pb2.INFO
        }

        return warden_pb2.Finding(
            id=finding.get("id", ""),
            title=finding.get("title", ""),
            description=finding.get("description", ""),
            severity=severity_map.get(finding.get("severity", "").lower(), warden_pb2.SEVERITY_UNSPECIFIED),
            file_path=finding.get("file_path", ""),
            line_number=finding.get("line_number", 0),
            column_number=finding.get("column_number", 0),
            code_snippet=finding.get("code_snippet", ""),
            suggestion=finding.get("suggestion", ""),
            frame_id=finding.get("frame_id", ""),
            cwe_id=finding.get("cwe_id", ""),
            owasp_category=finding.get("owasp_category", "")
        )

    def _convert_fortification(self, fort: dict) -> "warden_pb2.Fortification":
        """Convert dict fortification to proto Fortification."""
        return warden_pb2.Fortification(
            id=fort.get("id", ""),
            title=fort.get("title", ""),
            description=fort.get("description", ""),
            file_path=fort.get("file_path", ""),
            line_number=fort.get("line_number", 0),
            original_code=fort.get("original_code", ""),
            suggested_code=fort.get("suggested_code", ""),
            rationale=fort.get("rationale", "")
        )

    def _convert_cleaning(self, clean: dict) -> "warden_pb2.Cleaning":
        """Convert dict cleaning to proto Cleaning."""
        return warden_pb2.Cleaning(
            id=clean.get("id", ""),
            title=clean.get("title", ""),
            description=clean.get("description", ""),
            file_path=clean.get("file_path", ""),
            line_number=clean.get("line_number", 0),
            detail=clean.get("detail", "")
        )


class GrpcServer:
    """
    Async gRPC server for Warden.

    Usage:
        server = GrpcServer(port=50051)
        await server.start()
        await server.wait_for_termination()
    """

    def __init__(
        self,
        port: int = 50051,
        project_root: Optional[Path] = None,
        bridge: Optional[WardenBridge] = None
    ):
        """
        Initialize gRPC server.

        Args:
            port: Port to listen on (default: 50051)
            project_root: Project root for WardenBridge
            bridge: Existing bridge instance (optional)
        """
        self.port = port
        self.project_root = project_root or Path.cwd()
        self.bridge = bridge
        self.server: Optional[aio.Server] = None
        self.servicer: Optional[WardenServicer] = None
        logger.info("grpc_server_init", port=port)

    async def start(self) -> None:
        """Start the gRPC server."""
        if warden_pb2_grpc is None:
            raise RuntimeError(
                "gRPC code not generated. Run: python scripts/generate_grpc.py"
            )

        self.server = aio.server()

        # Create servicer with bridge
        self.servicer = WardenServicer(
            bridge=self.bridge,
            project_root=self.project_root
        )

        # Register servicer
        warden_pb2_grpc.add_WardenServiceServicer_to_server(
            self.servicer,
            self.server
        )

        # Enable gRPC Reflection for Postman auto-discovery
        if reflection is not None and warden_pb2 is not None:
            SERVICE_NAMES = (
                warden_pb2.DESCRIPTOR.services_by_name['WardenService'].full_name,
                reflection.SERVICE_NAME,
            )
            reflection.enable_server_reflection(SERVICE_NAMES, self.server)
            logger.info("grpc_reflection_enabled")

        # Add insecure port (TODO: add TLS support)
        listen_addr = f"[::]:{self.port}"
        self.server.add_insecure_port(listen_addr)

        await self.server.start()
        logger.info("grpc_server_started", address=listen_addr)

    async def stop(self, grace: float = 5.0) -> None:
        """Stop the gRPC server gracefully."""
        if self.server:
            await self.server.stop(grace)
            logger.info("grpc_server_stopped")

    async def wait_for_termination(self) -> None:
        """Wait for server termination."""
        if self.server:
            await self.server.wait_for_termination()
