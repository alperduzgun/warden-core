"""
Tool Registry

Infrastructure for tool discovery and registration.
Following project's registry pattern (see FrameRegistry).

Extended to support:
- Batch registration from adapters
- Multi-adapter tool discovery
- Dynamic tool registration at runtime
- Tool tiering (CORE / EXTENDED / INTERNAL)
"""

from typing import TYPE_CHECKING

from warden.mcp.domain.enums import ToolCategory, ToolTier
from warden.mcp.domain.models import MCPToolDefinition

if TYPE_CHECKING:
    from warden.mcp.infrastructure.adapters.base_adapter import BaseWardenAdapter


# =========================================================================
# Core Tools Definition
# =========================================================================
# The 8 essential tools exposed by default in tools/list.
# These cover the primary scan -> findings -> fix workflow.
# All other tools are EXTENDED (hidden until warden_expand_tools is called).
#
# Mapping to issue #204 shorthand:
#   scan           -> warden_scan
#   scan_file      -> warden_execute_pipeline  (single-file pipeline)
#   get_findings   -> warden_get_all_issues
#   get_config     -> warden_get_config
#   explain_finding -> warden_analyze_results
#   suggest_fix    -> warden_fix
#   get_status     -> warden_status
#   list_frames    -> warden_list_frames
CORE_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "warden_scan",
        "warden_execute_pipeline",
        "warden_get_all_issues",
        "warden_get_config",
        "warden_analyze_results",
        "warden_fix",
        "warden_status",
        "warden_list_frames",
    }
)

# The meta-tool is always CORE-tier so agents can expand on demand.
META_TOOL_NAME = "warden_expand_tools"

# Internal tools (diagnostics, not exposed in tools/list).
INTERNAL_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "warden_health_check",
        "warden_get_server_status",
    }
)


def _assign_tier(name: str) -> ToolTier:
    """
    Determine the tier for a tool based on its name.

    Priority:
    1. INTERNAL if in INTERNAL_TOOL_NAMES
    2. CORE if in CORE_TOOL_NAMES or is the meta-tool
    3. EXTENDED otherwise
    """
    if name in INTERNAL_TOOL_NAMES:
        return ToolTier.INTERNAL
    if name in CORE_TOOL_NAMES or name == META_TOOL_NAME:
        return ToolTier.CORE
    return ToolTier.EXTENDED


class ToolRegistry:
    """
    Registry for MCP tool definitions.

    Manages tool discovery, registration, and lookup.
    Follows the project's registry pattern used in FrameRegistry.

    Supports tier-based filtering so tools/list can return a
    manageable subset of tools by default.
    """

    def __init__(self) -> None:
        """Initialize registry with built-in tools."""
        self._tools: dict[str, MCPToolDefinition] = {}
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
                tier=ToolTier.CORE,
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
                tier=ToolTier.EXTENDED,
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
                tier=ToolTier.CORE,
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
                tier=ToolTier.CORE,
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
                tier=ToolTier.CORE,
            ),
        ]

        for tool in builtin:
            self.register(tool)

    def register(self, tool: MCPToolDefinition) -> None:
        """
        Register a tool.

        Automatically assigns a tier based on CORE_TOOL_NAMES / INTERNAL_TOOL_NAMES
        if the tool does not already have a CORE or INTERNAL tier explicitly set.
        This ensures adapter-registered tools get correct tiers without requiring
        every adapter to know about tiering.

        Args:
            tool: Tool definition to register
        """
        # Auto-assign tier based on the canonical name lists.
        # Tools explicitly set to CORE/INTERNAL by their adapter are respected;
        # anything still at the default EXTENDED gets re-evaluated.
        tool.tier = _assign_tier(tool.name)
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

    def get(self, name: str) -> MCPToolDefinition | None:
        """
        Get tool by name.

        Args:
            name: Tool name

        Returns:
            Tool definition if found, None otherwise
        """
        return self._tools.get(name)

    def list_all(self, bridge_available: bool = True) -> list[MCPToolDefinition]:
        """
        List all available tools (regardless of tier).

        Args:
            bridge_available: If False, exclude bridge-dependent tools

        Returns:
            List of tool definitions
        """
        if bridge_available:
            return list(self._tools.values())
        return [t for t in self._tools.values() if not t.requires_bridge]

    def list_by_tier(
        self,
        tier: ToolTier,
        bridge_available: bool = True,
    ) -> list[MCPToolDefinition]:
        """
        List tools at or above the given tier level.

        Tier hierarchy: CORE < EXTENDED < INTERNAL
        - CORE: returns only CORE tools
        - EXTENDED: returns CORE + EXTENDED tools
        - INTERNAL: returns all tools

        Args:
            tier: Maximum tier to include
            bridge_available: If False, exclude bridge-dependent tools

        Returns:
            List of tool definitions matching the tier filter
        """
        tier_sets: dict[ToolTier, set[ToolTier]] = {
            ToolTier.CORE: {ToolTier.CORE},
            ToolTier.EXTENDED: {ToolTier.CORE, ToolTier.EXTENDED},
            ToolTier.INTERNAL: {ToolTier.CORE, ToolTier.EXTENDED, ToolTier.INTERNAL},
        }
        allowed = tier_sets.get(tier, {ToolTier.CORE})

        tools = [t for t in self._tools.values() if t.tier in allowed]
        if not bridge_available:
            tools = [t for t in tools if not t.requires_bridge]
        return tools

    def list_by_category(self, category: ToolCategory) -> list[MCPToolDefinition]:
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

    def register_batch(self, tools: list[MCPToolDefinition]) -> int:
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

    def register_from_adapters(self, adapters: list["BaseWardenAdapter"]) -> int:
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
