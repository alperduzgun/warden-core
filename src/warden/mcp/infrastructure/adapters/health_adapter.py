"""
Health Adapter

MCP adapter for health and status tools.
Maps to gRPC HealthStatusMixin functionality.
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from warden.mcp.infrastructure.adapters.base_adapter import BaseWardenAdapter
from warden.mcp.domain.models import MCPToolDefinition, MCPToolResult
from warden.mcp.domain.enums import ToolCategory


class HealthAdapter(BaseWardenAdapter):
    """
    Adapter for health and status tools.

    Tools:
        - warden_health_check: Basic health check
        - warden_get_server_status: Detailed server status
    """

    SUPPORTED_TOOLS = frozenset({
        "warden_health_check",
        "warden_get_server_status",
    })
    TOOL_CATEGORY = ToolCategory.STATUS

    def __init__(self, project_root: Path, bridge: Any = None) -> None:
        """Initialize health adapter with start time tracking."""
        super().__init__(project_root, bridge)
        self._start_time = datetime.now()

    def get_tool_definitions(self) -> List[MCPToolDefinition]:
        """Get health tool definitions."""
        return [
            self._create_tool_definition(
                name="warden_health_check",
                description="Check if Warden service is healthy and responsive",
                properties={},
            ),
            self._create_tool_definition(
                name="warden_get_server_status",
                description="Get detailed server status including uptime, memory, and component status",
                properties={},
            ),
        ]

    async def _execute_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> MCPToolResult:
        """Execute health tool."""
        if tool_name == "warden_health_check":
            return await self._health_check()
        elif tool_name == "warden_get_server_status":
            return await self._get_server_status()
        else:
            return MCPToolResult.error(f"Unknown tool: {tool_name}")

    async def _health_check(self) -> MCPToolResult:
        """Perform health check."""
        uptime = (datetime.now() - self._start_time).total_seconds()

        # Check component availability
        components = {
            "bridge": self.bridge is not None,
            "project_root": self.project_root.exists(),
        }

        # Check if bridge has orchestrator
        if self.bridge:
            components["orchestrator"] = getattr(self.bridge, "orchestrator", None) is not None
            components["llm"] = getattr(self.bridge, "llm_config", None) is not None

        all_healthy = all(components.values())

        return MCPToolResult.json_result({
            "healthy": all_healthy,
            "status": "ok" if all_healthy else "degraded",
            "version": self._get_version(),
            "uptime_seconds": round(uptime, 2),
            "components": components,
            "timestamp": datetime.utcnow().isoformat(),
        })

    async def _get_server_status(self) -> MCPToolResult:
        """Get detailed server status."""
        import os
        import sys

        uptime = (datetime.now() - self._start_time).total_seconds()

        # Get memory usage if available
        memory_mb = None
        try:
            import resource
            rusage = resource.getrusage(resource.RUSAGE_SELF)
            memory_mb = rusage.ru_maxrss / 1024  # Convert to MB on macOS
            if sys.platform == "linux":
                memory_mb = rusage.ru_maxrss / 1024  # Already in KB on Linux
        except Exception:
            pass

        # Get Python info
        python_info = {
            "version": sys.version,
            "platform": sys.platform,
            "executable": sys.executable,
        }

        # Get project info
        project_info = {
            "root": str(self.project_root),
            "exists": self.project_root.exists(),
            "warden_dir": (self.project_root / ".warden").exists(),
        }

        # Get bridge status
        bridge_status = {
            "available": self.bridge is not None,
            "orchestrator": False,
            "llm": False,
            "config_name": None,
        }

        if self.bridge:
            bridge_status["orchestrator"] = getattr(self.bridge, "orchestrator", None) is not None
            bridge_status["llm"] = getattr(self.bridge, "llm_config", None) is not None
            bridge_status["config_name"] = getattr(self.bridge, "active_config_name", None)

        return MCPToolResult.json_result({
            "running": True,
            "uptime_seconds": round(uptime, 2),
            "memory_mb": memory_mb,
            "python": python_info,
            "project": project_info,
            "bridge": bridge_status,
            "version": self._get_version(),
            "timestamp": datetime.utcnow().isoformat(),
        })

    def _get_version(self) -> str:
        """Get Warden version."""
        try:
            from warden._version import __version__
            return __version__
        except ImportError:
            return "unknown"
