"""
Tool Registry

Infrastructure for tool discovery and registration.
Following project's registry pattern (see FrameRegistry).

Extended to support:
- Batch registration from adapters
- Multi-adapter tool discovery
- Dynamic tool registration at runtime
"""

from typing import TYPE_CHECKING, Dict, List, Optional

from warden.mcp.domain.models import MCPToolDefinition
from warden.mcp.domain.enums import ToolCategory

if TYPE_CHECKING:
    from warden.mcp.infrastructure.adapters.base_adapter import BaseWardenAdapter


class ToolRegistry:
    """
    Registry for MCP tool definitions.

    Manages tool discovery, registration, and lookup.
    Follows the project's registry pattern used in FrameRegistry.
    """

    def __init__(self) -> None:
        """Initialize registry with built-in tools."""
        self._tools: Dict[str, MCPToolDefinition] = {}
        self._register_builtin_tools()

    def _register_builtin_tools(self) -> None:
        """Register built-in Warden tools."""
        builtin = [
            # Status tools (no bridge required)
            MCPToolDefinition(
                name="warden_status",
                description="Get Warden security status for the current project",
                category=ToolCategory.STATUS,
                input_schema={
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
                requires_bridge=False,
            ),
            MCPToolDefinition(
                name="warden_list_reports",
                description="List all available Warden reports",
                category=ToolCategory.REPORT,
                input_schema={
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
                requires_bridge=False,
            ),
            # Bridge tools (require WardenBridge)
            MCPToolDefinition(
                name="warden_scan",
                description="Run Warden security scan on the project",
                category=ToolCategory.SCAN,
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path to scan (default: project root)",
                        },
                        "frames": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Specific frames to run (default: all enabled)",
                        },
                    },
                    "required": [],
                },
                requires_bridge=True,
            ),
            MCPToolDefinition(
                name="warden_get_config",
                description="Get current Warden configuration",
                category=ToolCategory.CONFIG,
                input_schema={
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
                requires_bridge=True,
            ),
            MCPToolDefinition(
                name="warden_list_frames",
                description="List available validation frames",
                category=ToolCategory.CONFIG,
                input_schema={
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
                requires_bridge=True,
            ),
        ]

        for tool in builtin:
            self.register(tool)

    def register(self, tool: MCPToolDefinition) -> None:
        """
        Register a tool.

        Args:
            tool: Tool definition to register
        """
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> bool:
        """
        Unregister a tool.

        Args:
            name: Tool name to unregister

        Returns:
            True if tool was removed, False if not found
        """
        if name in self._tools:
            del self._tools[name]
            return True
        return False

    def get(self, name: str) -> Optional[MCPToolDefinition]:
        """
        Get tool by name.

        Args:
            name: Tool name

        Returns:
            Tool definition if found, None otherwise
        """
        return self._tools.get(name)

    def list_all(self, bridge_available: bool = True) -> List[MCPToolDefinition]:
        """
        List all available tools.

        Args:
            bridge_available: If False, exclude bridge-dependent tools

        Returns:
            List of tool definitions
        """
        if bridge_available:
            return list(self._tools.values())
        return [t for t in self._tools.values() if not t.requires_bridge]

    def list_by_category(self, category: ToolCategory) -> List[MCPToolDefinition]:
        """
        List tools by category.

        Args:
            category: Category to filter by

        Returns:
            List of tools in the category
        """
        return [t for t in self._tools.values() if t.category == category]

    def __contains__(self, name: str) -> bool:
        """Check if tool is registered."""
        return name in self._tools

    def __len__(self) -> int:
        """Get number of registered tools."""
        return len(self._tools)

    # =========================================================================
    # Batch Registration Methods
    # =========================================================================

    def register_batch(self, tools: List[MCPToolDefinition]) -> int:
        """
        Register multiple tools at once.

        Args:
            tools: List of tool definitions to register

        Returns:
            Number of tools registered
        """
        count = 0
        for tool in tools:
            self.register(tool)
            count += 1
        return count

    def register_from_adapter(self, adapter: "BaseWardenAdapter") -> int:
        """
        Register all tools from an adapter.

        Args:
            adapter: Adapter instance to get tools from

        Returns:
            Number of tools registered
        """
        tools = adapter.get_tool_definitions()
        return self.register_batch(tools)

    def register_from_adapters(self, adapters: List["BaseWardenAdapter"]) -> int:
        """
        Register tools from multiple adapters.

        Args:
            adapters: List of adapter instances

        Returns:
            Total number of tools registered
        """
        total = 0
        for adapter in adapters:
            total += self.register_from_adapter(adapter)
        return total

    def clear(self) -> None:
        """Clear all registered tools."""
        self._tools.clear()

    def reset_to_builtin(self) -> None:
        """Reset registry to only built-in tools."""
        self.clear()
        self._register_builtin_tools()
