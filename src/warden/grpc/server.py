"""
Warden gRPC Server

Async gRPC server wrapping WardenBridge for C# Panel communication.
Total: 51 endpoints
"""

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Optional

# Lazy import grpc (optional dependency)
try:
    from grpc import aio
    GRPC_AVAILABLE = True
except ImportError:
    aio = None  # type: ignore
    GRPC_AVAILABLE = False

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
        await server.start_async()
        await server.wait_for_termination_async()
    """

    def __init__(
        self,
        port: int = 50051,
        project_root: Path | None = None,
        bridge: WardenBridge | None = None,
        tls_cert_path: Path | None = None,
        tls_key_path: Path | None = None,
        tls_ca_path: Path | None = None
    ):
        """
        Initialize gRPC server.

        Args:
            port: Port to listen on (default: 50051)
            project_root: Project root for WardenBridge
            bridge: Existing bridge instance (optional)
            tls_cert_path: Path to TLS certificate file (optional, enables TLS)
            tls_key_path: Path to TLS private key file (optional, required with cert)
            tls_ca_path: Path to TLS CA certificate for client auth (optional)

        Raises:
            RuntimeError: If grpcio not installed
        """
        if not GRPC_AVAILABLE:
            raise RuntimeError(
                "gRPC dependencies not installed. "
                "Install with: pip install warden-core[grpc]"
            )

        self.port = port
        self.project_root = project_root or Path.cwd()
        self.bridge = bridge
        self.tls_cert_path = tls_cert_path
        self.tls_key_path = tls_key_path
        self.tls_ca_path = tls_ca_path
        self.server: aio.Server | None = None  # type: ignore
        self.servicer: WardenServicer | None = None

        tls_enabled = bool(tls_cert_path and tls_key_path)
        logger.info("grpc_server_init", port=port, endpoints=51, tls_enabled=tls_enabled)

    def _configure_transport(self, listen_addr: str) -> bool:
        """
        Configure server transport (TLS or insecure).

        Args:
            listen_addr: Address to bind to

        Returns:
            True if TLS is enabled, False if insecure

        Raises:
            FileNotFoundError: If certificate or key files not found
            RuntimeError: If TLS configuration is invalid
        """
        if not self.server:
            raise RuntimeError("Server not initialized")

        # If both cert and key paths provided, enable TLS
        if self.tls_cert_path and self.tls_key_path:
            try:
                # Read certificate
                cert_path = Path(self.tls_cert_path)
                if not cert_path.exists():
                    raise FileNotFoundError(f"TLS certificate not found: {cert_path}")
                with open(cert_path, 'rb') as f:
                    cert_data = f.read()

                # Read private key
                key_path = Path(self.tls_key_path)
                if not key_path.exists():
                    raise FileNotFoundError(f"TLS private key not found: {key_path}")
                with open(key_path, 'rb') as f:
                    key_data = f.read()

                # Read CA certificate if provided (for client authentication)
                ca_data = None
                ca_path = None
                require_client_auth = False
                if self.tls_ca_path:
                    ca_path = Path(self.tls_ca_path)
                    if not ca_path.exists():
                        raise FileNotFoundError(f"TLS CA certificate not found: {ca_path}")
                    with open(ca_path, 'rb') as f:
                        ca_data = f.read()
                    require_client_auth = True

                # Create SSL server credentials
                import grpc
                credentials = grpc.ssl_server_credentials(
                    [(key_data, cert_data)],
                    root_certificates=ca_data,
                    require_client_auth=require_client_auth
                )

                # Add secure port
                self.server.add_secure_port(listen_addr, credentials)

                logger.info(
                    "grpc_tls_configured",
                    cert_path=str(cert_path),
                    key_path=str(key_path),
                    ca_path=str(ca_path) if ca_path else None,
                    client_auth_required=require_client_auth
                )
                return True

            except FileNotFoundError as e:
                logger.error("grpc_tls_cert_not_found", error=str(e))
                raise
            except Exception as e:
                logger.error("grpc_tls_config_failed", error=str(e))
                raise RuntimeError(f"Failed to configure TLS: {e}") from e

        # Fall back to insecure mode
        elif self.tls_cert_path or self.tls_key_path:
            # Only one of cert/key provided - invalid configuration
            raise RuntimeError(
                "Both tls_cert_path and tls_key_path must be provided together"
            )

        # No TLS configuration - use insecure mode
        self.server.add_insecure_port(listen_addr)
        logger.info("grpc_insecure_mode", address=listen_addr)
        return False

    async def start_async(self) -> None:
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

        # Configure TLS or insecure mode
        listen_addr = f"[::]:{self.port}"
        tls_enabled = self._configure_transport(listen_addr)

        await self.server.start_async()
        logger.info(
            "grpc_server_started",
            address=listen_addr,
            endpoints=51,
            tls_enabled=tls_enabled
        )

    async def stop_async(self, grace: float = 5.0) -> None:
        """Stop the gRPC server gracefully."""
        if self.server:
            await self.server.stop_async(grace)
            logger.info("grpc_server_stopped")

    async def wait_for_termination_async(self) -> None:
        """Wait for server termination."""
        if self.server:
            await self.server.wait_for_termination_async()


async def main_async():
    """Main entry point for standalone server."""
    import argparse

    parser = argparse.ArgumentParser(description="Warden gRPC Server")
    parser.add_argument("--port", type=int, default=50051, help="Port to listen on")
    parser.add_argument("--project", type=str, default=".", help="Project root path")
    parser.add_argument(
        "--tls-cert",
        type=str,
        help="Path to TLS certificate file (enables TLS)"
    )
    parser.add_argument(
        "--tls-key",
        type=str,
        help="Path to TLS private key file (required with --tls-cert)"
    )
    parser.add_argument(
        "--tls-ca",
        type=str,
        help="Path to TLS CA certificate for client authentication (optional)"
    )
    args = parser.parse_args()

    # Convert TLS paths to Path objects if provided
    tls_cert_path = Path(args.tls_cert) if args.tls_cert else None
    tls_key_path = Path(args.tls_key) if args.tls_key else None
    tls_ca_path = Path(args.tls_ca) if args.tls_ca else None

    server = GrpcServer(
        port=args.port,
        project_root=Path(args.project),
        tls_cert_path=tls_cert_path,
        tls_key_path=tls_key_path,
        tls_ca_path=tls_ca_path
    )

    await server.start_async()

    tls_status = "with TLS" if (tls_cert_path and tls_key_path) else "insecure mode"
    print(f"Warden gRPC Server running on port {args.port} ({tls_status})")
    print("51 endpoints available")
    print("Press Ctrl+C to stop")

    try:
        await server.wait_for_termination_async()
    except KeyboardInterrupt:
        await server.stop_async()


if __name__ == "__main__":
    asyncio.run(main_async())
