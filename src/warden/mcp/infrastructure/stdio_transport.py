"""
STDIO Transport Implementation

STDIO-based MCP transport for CLI integration.
Reads JSON-RPC messages from stdin, writes to stdout.
"""

import asyncio
import sys
from typing import Optional

from warden.mcp.ports.transport import ITransport
from warden.mcp.domain.errors import MCPTransportError

# Optional logging import
try:
    from warden.shared.infrastructure.logging import get_logger
    logger = get_logger(__name__)
except ImportError:
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)


class STDIOTransport(ITransport):
    """
    STDIO-based MCP transport.

    Reads JSON-RPC messages from stdin line by line,
    writes responses to stdout.
    """

    def __init__(self) -> None:
        """Initialize STDIO transport."""
        self._is_open = True
        self._read_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()

    async def read_message(self) -> Optional[str]:
        """
        Read a line from stdin asynchronously.

        Returns:
            Message string, or None on EOF
        """
        if not self._is_open:
            return None

        async with self._read_lock:
            loop = asyncio.get_event_loop()
            try:
                line = await loop.run_in_executor(None, sys.stdin.readline)
                if not line:
                    return None
                return line.strip()
            except Exception as e:
                logger.error("stdio_read_error", error=str(e))
                raise MCPTransportError(f"Failed to read from stdin: {e}")

    async def write_message(self, data: str) -> None:
        """
        Write a line to stdout.

        Args:
            data: Message string to write
        """
        if not self._is_open:
            return

        async with self._write_lock:
            try:
                sys.stdout.write(data + "\n")
                sys.stdout.flush()
            except Exception as e:
                logger.error("stdio_write_error", error=str(e))
                raise MCPTransportError(f"Failed to write to stdout: {e}")

    async def close(self) -> None:
        """Close transport."""
        self._is_open = False
        logger.debug("stdio_transport_closed")

    @property
    def is_open(self) -> bool:
        """Check if transport is open."""
        return self._is_open
