#!/usr/bin/env python3
"""Start Warden IPC server for CLI bridge communication."""

import asyncio
import logging
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.warden.cli_bridge.server import IPCServer

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


async def main():
    """Start the IPC server."""
    logger.info("Starting Warden IPC Server...")

    # Create bridge with project root (so it can find .warden/config.yaml)
    from src.warden.cli_bridge.bridge import WardenBridge

    logger.info(f"Project root: {project_root}")
    bridge = WardenBridge(project_root=project_root)

    # Create server instance with initialized bridge
    server = IPCServer(
        bridge=bridge,
        transport="socket",
        socket_path="/tmp/warden-ipc.sock"
    )

    try:
        # Start server
        logger.info("✅ IPC Server starting on /tmp/warden-ipc.sock")
        logger.info(f"📋 Pipeline config: {bridge.active_config_name}")
        logger.info(f"⚙️  Orchestrator ready: {bridge.orchestrator is not None}")
        if bridge.orchestrator:
            logger.info(f"🎯 Loaded {len(bridge.orchestrator.frames)} validation frames")
        logger.info("Press Ctrl+C to stop")

        await server.start()

    except KeyboardInterrupt:
        logger.info("\n⚠️  Shutting down server...")
        await server.stop()
        logger.info("✅ Server stopped")

    except Exception as e:
        logger.error(f"❌ Server error: {e}")
        raise


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
