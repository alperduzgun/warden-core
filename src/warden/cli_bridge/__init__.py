"""
Warden CLI Bridge - IPC bridge for Ink-based CLI

Provides JSON-RPC based IPC communication between Python backend and Node.js Ink CLI.

Features graceful degradation when Warden validation framework is not available.
"""

# Protocol classes are always available (no dependencies)
from warden.cli_bridge.protocol import (
    IPCRequest,
    IPCResponse,
    IPCError,
    ErrorCode,
)

# Minimal bridge is always available (no dependencies)
from warden.cli_bridge.bridge_minimal import MinimalWardenBridge

# Try to import full bridge and server (requires Warden dependencies)
try:
    from warden.cli_bridge.bridge import WardenBridge
    from warden.cli_bridge.server import IPCServer
    WARDEN_BRIDGE_AVAILABLE = True
except ImportError:
    WARDEN_BRIDGE_AVAILABLE = False
    # Use minimal bridge as fallback
    WardenBridge = MinimalWardenBridge
    IPCServer = None

# Export list depends on what's available
__all__ = [
    # Always available
    "IPCRequest",
    "IPCResponse",
    "IPCError",
    "ErrorCode",
    "MinimalWardenBridge",
    "WARDEN_BRIDGE_AVAILABLE",
    # May be minimal implementation
    "WardenBridge",
]

# Add server if available
if IPCServer is not None:
    __all__.append("IPCServer")
