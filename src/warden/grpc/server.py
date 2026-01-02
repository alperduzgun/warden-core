"""
Warden gRPC Server

Async gRPC server wrapping WardenBridge for C# Panel communication.
Total: 51 endpoints
"""

import asyncio
from pathlib import Path
from typing import Optional

from grpc import aio

# Import generated protobuf code
try:
    from warden.grpc.generated import warden_pb2, warden_pb2_grpc
except ImportError:
    warden_pb2 = None
    warden_pb2_grpc = None

# gRPC Reflection (for Postman auto-discovery)
try:
    from grpc_reflection.v1alpha import reflection
except ImportError:
    reflection = None

# Import Warden components
from warden.cli_bridge.bridge import WardenBridge

# Import modular servicer
from warden.grpc.servicer import WardenServicer

# Optional: structured logging
try:
    from warden.shared.infrastructure.logging import get_logger
    logger = get_logger(__name__)
except ImportError:
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)


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
        logger.info("grpc_server_init", port=port, endpoints=51)

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
        logger.info("grpc_server_started", address=listen_addr, endpoints=51)

    async def stop(self, grace: float = 5.0) -> None:
        """Stop the gRPC server gracefully."""
        if self.server:
            await self.server.stop(grace)
            logger.info("grpc_server_stopped")

    async def wait_for_termination(self) -> None:
        """Wait for server termination."""
        if self.server:
            await self.server.wait_for_termination()


async def main():
    """Main entry point for standalone server."""
    import argparse

    parser = argparse.ArgumentParser(description="Warden gRPC Server")
    parser.add_argument("--port", type=int, default=50051, help="Port to listen on")
    parser.add_argument("--project", type=str, default=".", help="Project root path")
    args = parser.parse_args()

    server = GrpcServer(
        port=args.port,
        project_root=Path(args.project)
    )

    await server.start()
    print(f"Warden gRPC Server running on port {args.port} with 51 endpoints")
    print("Press Ctrl+C to stop")

    try:
        await server.wait_for_termination()
    except KeyboardInterrupt:
        await server.stop()


if __name__ == "__main__":
    asyncio.run(main())
