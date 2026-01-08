"""
Warden MCP Server Entry Point

Launches the MCP (Model Context Protocol) server for AI assistant integration.

Usage:
    python -m warden.mcp.entry
    warden serve mcp

The MCP server communicates over STDIO using JSON-RPC 2.0 protocol,
allowing AI assistants like Claude to access Warden reports and tools.
"""

import asyncio
import signal
import sys
from pathlib import Path
from typing import Optional

# Try to import logging
try:
    from warden.shared.infrastructure.logging import get_logger, configure_logging
    # Initial configuration for MCP to ensure logs go to stderr early
    configure_logging(stream=sys.stderr)
    logger = get_logger(__name__)
except ImportError:
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stderr,  # Log to stderr to not interfere with STDIO
    )
    logger = logging.getLogger(__name__)


async def main(project_root: Optional[Path] = None) -> None:
    """
    Start the MCP server.

    Args:
        project_root: Project root directory (default: cwd)
    """
    from warden.mcp.server import MCPServer

    root = project_root or Path.cwd()
    server = MCPServer(project_root=root)

    # Setup signal handlers for graceful shutdown
    loop = asyncio.get_event_loop()

    def signal_handler():
        logger.info("mcp_server_shutdown_signal")
        asyncio.create_task(server.stop())

    # Register signal handlers (Unix only)
    if sys.platform != "win32":
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, signal_handler)

    try:
        logger.info(
            "mcp_server_starting",
            project_root=str(root),
            pid=str(os.getpid()) if "os" in dir() else "unknown",
        )
        await server.start()
    except KeyboardInterrupt:
        logger.info("mcp_server_keyboard_interrupt")
    except Exception as e:
        logger.error("mcp_server_error", error=str(e))
        raise
    finally:
        await server.stop()
        logger.info("mcp_server_stopped")


def run(project_root: Optional[str] = None) -> None:
    """
    Synchronous entry point for CLI.

    Args:
        project_root: Project root directory path
    """
    import os

    root = Path(project_root) if project_root else Path.cwd()
    asyncio.run(main(root))


if __name__ == "__main__":
    import os
    run()
