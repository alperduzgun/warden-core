"""
Warden Bridge Adapter

Infrastructure adapter for WardenBridge integration.
Translates MCP tool calls to WardenBridge operations.
"""

from pathlib import Path
from typing import Any, Dict, Optional

from warden.mcp.ports.tool_executor import IToolExecutor
from warden.mcp.domain.models import MCPToolDefinition, MCPToolResult
from warden.mcp.domain.errors import MCPToolExecutionError
from warden.shared.utils.path_utils import sanitize_path

# Optional imports for bridge functionality
try:
    from warden.cli_bridge.bridge import WardenBridge
    BRIDGE_AVAILABLE = True
except ImportError:
    BRIDGE_AVAILABLE = False

# Optional logging
try:
    from warden.shared.infrastructure.logging import get_logger
    logger = get_logger(__name__)
except ImportError:
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)


class WardenBridgeAdapter(IToolExecutor):
    """
    Adapter for WardenBridge integration.

    Implements IToolExecutor to handle bridge-based tools
    (scan, config, frames).
    """

    SUPPORTED_TOOLS = frozenset({
        "warden_scan",
        "warden_get_config",
        "warden_list_frames",
    })

    def __init__(self, project_root: Path) -> None:
        """
        Initialize bridge adapter.

        Args:
            project_root: Project root directory
        """
        self.project_root = project_root
        self._bridge: Optional[Any] = None

        if BRIDGE_AVAILABLE:
            try:
                self._bridge = WardenBridge(project_root=project_root)
                logger.info("warden_bridge_initialized", project_root=str(project_root))
            except Exception as e:
                logger.warning("warden_bridge_init_failed", error=str(e))

    @property
    def is_available(self) -> bool:
        """Check if bridge is available."""
        return self._bridge is not None

    def supports(self, tool_name: str) -> bool:
        """Check if this executor supports the given tool."""
        return tool_name in self.SUPPORTED_TOOLS

    async def execute_async(
        self,
        tool: MCPToolDefinition,
        arguments: Dict[str, Any],
    ) -> MCPToolResult:
        """
        Execute a bridge-based tool.

        Args:
            tool: Tool definition
            arguments: Tool arguments

        Returns:
            Tool execution result
        """
        if not self.is_available:
            raise MCPToolExecutionError(tool.name, "Warden bridge not available")

        try:
            if tool.name == "warden_scan":
                return await self._execute_scan_async(arguments)
            elif tool.name == "warden_get_config":
                return await self._execute_get_config_async()
            elif tool.name == "warden_list_frames":
                return await self._execute_list_frames_async()
            else:
                raise MCPToolExecutionError(tool.name, "Unknown bridge tool")
        except MCPToolExecutionError:
            raise
        except Exception as e:
            logger.error("bridge_tool_error", tool=tool.name, error=str(e))
            raise MCPToolExecutionError(tool.name, str(e))

    async def _execute_scan_async(self, arguments: Dict[str, Any]) -> MCPToolResult:
        """Execute warden_scan tool."""
        path = arguments.get("path", str(self.project_root))
        frames = arguments.get("frames")

        try:
            safe_path = sanitize_path(path, self.project_root)
            result = await self._bridge.execute_pipeline_async(
                file_path=str(safe_path),
                frames=frames,
            )
            return MCPToolResult.json_result(result)
        except ValueError as e:
            raise MCPToolExecutionError("warden_scan", f"Path validation failed: {e}")

    async def _execute_get_config_async(self) -> MCPToolResult:
        """Execute warden_get_config tool."""
        config = await self._bridge.get_config_async()
        return MCPToolResult.json_result(config)

    async def _execute_list_frames_async(self) -> MCPToolResult:
        """Execute warden_list_frames tool."""
        frames = await self._bridge.get_available_frames_async()
        return MCPToolResult.json_result(frames)
