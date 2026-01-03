"""
Warden IPC Server Entry Point
============================

Launched via: python -m warden.services.ipc_entry
"""

import asyncio
import logging
import sys
import os
import signal
from pathlib import Path

# Absolute imports from within the package
from warden.cli_bridge.server import IPCServer
from warden.cli_bridge.bridge import WardenBridge

# Project root calculation:
# src/warden/services/ipc_entry.py -> src/warden/services -> src/warden -> src -> ROOT
project_root = Path(__file__).parents[3]

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

# PID file location
PID_FILE = project_root / ".warden" / "backend.pid"
SOCKET_PATH = "/tmp/warden-ipc.sock"


def check_single_instance():
    """Ensure only one backend instance is running."""
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            # Check if process is still running
            os.kill(pid, 0)  # Signal 0 just checks if process exists
            logger.warning(f"⚠️  Backend already running (PID: {pid})")
            logger.warning("   Use 'pkill -f warden.services.ipc_entry' to kill it first")
            sys.exit(1)
        except (ProcessLookupError, ValueError):
            # Process doesn't exist, remove stale PID file
            logger.info(f"🧹 Cleaning stale PID file")
            PID_FILE.unlink()

    # Create .warden directory if it doesn't exist
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Write current PID
    PID_FILE.write_text(str(os.getpid()))
    logger.info(f"📝 PID file created: {PID_FILE}")


def cleanup():
    """Clean up PID file and socket on exit."""
    if PID_FILE.exists():
        PID_FILE.unlink()
        logger.info("🧹 PID file removed")

    if os.path.exists(SOCKET_PATH):
        os.unlink(SOCKET_PATH)
        logger.info("🧹 Socket removed")


def signal_handler(signum, frame):
    """Handle termination signals gracefully."""
    logger.info(f"\n⚠️  Received signal {signum}, shutting down...")
    cleanup()
    sys.exit(0)


async def main():
    """Start the IPC server."""
    logger.info("Starting Warden IPC Server (Service Mode)...")

    # Check single instance
    check_single_instance()

    # Register signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    logger.info(f"Project root: {project_root}")
    bridge = WardenBridge(project_root=project_root)

    # Create server instance with initialized bridge
    server = IPCServer(
        bridge=bridge,
        transport="socket",
        socket_path=SOCKET_PATH
    )

    try:
        # Start server
        logger.info(f"✅ IPC Server starting on {SOCKET_PATH}")
        logger.info(f"📋 Pipeline config: {bridge.active_config_name}")
        logger.info(f"⚙️  Orchestrator ready: {bridge.orchestrator is not None}")
        if bridge.orchestrator:
            logger.info(f"🎯 Loaded {len(bridge.orchestrator.frames)} validation frames")
        logger.info("Press Ctrl+C to stop")

        await server.start()

    except KeyboardInterrupt:
        logger.info("\n⚠️  Shutting down server...")
        await server.stop()
        cleanup()
        logger.info("✅ Server stopped")

    except Exception as e:
        logger.error(f"❌ Server error: {e}")
        cleanup()
        raise


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        cleanup()
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        cleanup()
        sys.exit(1)
