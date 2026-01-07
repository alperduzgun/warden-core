"""
Tool Executor Service

Application service for tool execution.
Routes tool calls to appropriate executors.
"""

from pathlib import Path
from typing import Any, Dict

from warden.mcp.domain.models import MCPToolResult
from warden.mcp.domain.errors import MCPToolNotFoundError, MCPToolExecutionError
from warden.mcp.infrastructure.tool_registry import ToolRegistry
from warden.mcp.infrastructure.warden_adapter import WardenBridgeAdapter
from warden.mcp.infrastructure.file_resource_repo import FileResourceRepository

# Optional logging
try:
    from warden.shared.infrastructure.logging import get_logger
    logger = get_logger(__name__)
except ImportError:
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)


class ToolExecutorService:
    """
    Application service for tool execution.

    Coordinates tool lookup, routing, and execution.
    """

    def __init__(self, project_root: Path) -> None:
        """
        Initialize tool executor.

        Args:
            project_root: Project root directory
        """
        self.project_root = project_root
        self._registry = ToolRegistry()
        self._bridge_adapter = WardenBridgeAdapter(project_root)
        self._resource_repo = FileResourceRepository(project_root)

    @property
    def bridge_available(self) -> bool:
        """Check if bridge is available."""
        return self._bridge_adapter.is_available

    async def execute(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Execute a tool by name.

        Args:
            tool_name: Name of tool to execute
            arguments: Tool arguments

        Returns:
            Tool result in MCP format
        """
        tool = self._registry.get(tool_name)
        if not tool:
            raise MCPToolNotFoundError(tool_name)

        try:
            # Route to appropriate executor
            if tool.requires_bridge:
                if not self._bridge_adapter.is_available:
                    return MCPToolResult.error("Warden bridge not available").to_dict()
                result = await self._bridge_adapter.execute(tool, arguments)
            else:
                result = await self._execute_builtin(tool_name, arguments)

            return result.to_dict()

        except MCPToolExecutionError as e:
            logger.error("tool_execution_failed", tool=tool_name, error=str(e))
            return MCPToolResult.error(str(e)).to_dict()
        except Exception as e:
            logger.error("tool_execution_error", tool=tool_name, error=str(e))
            return MCPToolResult.error(f"Tool execution error: {e}").to_dict()

    async def _execute_builtin(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> MCPToolResult:
        """
        Execute built-in (non-bridge) tools.

        Args:
            tool_name: Tool name
            arguments: Tool arguments

        Returns:
            Tool result
        """
        if tool_name == "warden_status":
            return await self._tool_status()
        elif tool_name == "warden_list_reports":
            return await self._tool_list_reports()
        else:
            raise MCPToolExecutionError(tool_name, "Unknown built-in tool")

    async def _tool_status(self) -> MCPToolResult:
        """Get Warden status."""
        status_file = self.project_root / ".warden" / "ai_status.md"

        if status_file.exists():
            content = status_file.read_text(encoding="utf-8")
            return MCPToolResult.success(content)
        else:
            return MCPToolResult.success(
                "Warden status file not found. Run 'warden scan' first."
            )

    async def _tool_list_reports(self) -> MCPToolResult:
        """List all available reports."""
        reports = self._resource_repo.list_all_reports()

        if not reports:
            return MCPToolResult.success(
                "No reports found. Run 'warden scan' to generate reports."
            )

        text = "Available Warden Reports:\n\n"
        for report in reports:
            size_kb = report["size"] / 1024
            text += f"- {report['name']} ({size_kb:.1f} KB)\n"
            text += f"  Path: {report['path']}\n"
            text += f"  Type: {report['mime_type']}\n\n"

        return MCPToolResult.success(text)
