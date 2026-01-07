"""
MCP Server - Backward Compatible Facade

This module maintains the original MCPServer API while delegating
to the new DDD-structured components.

BACKWARD COMPATIBLE: All original imports and usage patterns work unchanged.
"""

from pathlib import Path
from typing import Optional

from warden.mcp.application.mcp_service import MCPService
from warden.mcp.infrastructure.stdio_transport import STDIOTransport
from warden.mcp.resources import MCPResourceManager
from warden.mcp.protocol import MCPProtocol

# Optional logging
try:
    from warden.shared.infrastructure.logging import get_logger
    logger = get_logger(__name__)
except ImportError:
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)


# MCP Protocol version (kept for backward compatibility)
PROTOCOL_VERSION = "2024-11-05"


class MCPServer:
    """
    MCP Server with STDIO transport.

    BACKWARD COMPATIBLE: Maintains original API signature.
    Internally delegates to MCPService (DDD architecture).

    Implements the Model Context Protocol for AI assistant integration,
    exposing Warden reports as resources and validation capabilities as tools.
    """

    def __init__(
        self,
        project_root: Optional[Path] = None,
    ):
        """
        Initialize MCP server.

        Args:
            project_root: Project root directory (default: cwd)
        """
        self.project_root = project_root or Path.cwd()

        # Create transport and service
        self._transport = STDIOTransport()
        self._service = MCPService(
            transport=self._transport,
            project_root=self.project_root,
        )

        # Backward compatible attributes
        self._running = False
        self._initialized = False

        # Expose for backward compatibility
        self.protocol = MCPProtocol()
        self.resource_manager = MCPResourceManager(self.project_root)

    async def start(self) -> None:
        """
        Start the MCP server on STDIO.

        Reads JSON-RPC messages from stdin, processes them,
        and writes responses to stdout.
        """
        self._running = True
        logger.info("mcp_server_starting", project_root=str(self.project_root))

        try:
            await self._service.start()
        finally:
            self._running = False

    async def stop(self) -> None:
        """Stop the MCP server gracefully."""
        self._running = False
        await self._transport.close()

    @property
    def is_running(self) -> bool:
        """Check if server is running."""
        return self._running

    @property
    def is_initialized(self) -> bool:
        """Check if client has initialized."""
        return self._service.session_manager.is_initialized()
