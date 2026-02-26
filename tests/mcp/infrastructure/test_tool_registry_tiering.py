"""
Tests for ToolRegistry tier-based filtering.
"""

import pytest

from warden.mcp.domain.enums import ToolCategory, ToolTier
from warden.mcp.domain.models import MCPToolDefinition
from warden.mcp.infrastructure.tool_registry import (
    CORE_TOOL_NAMES,
    INTERNAL_TOOL_NAMES,
    META_TOOL_NAME,
    ToolRegistry,
    _assign_tier,
)


class TestAssignTier:
    """Tests for the _assign_tier helper function."""

    def test_core_tool_gets_core_tier(self):
        assert _assign_tier("warden_scan") == ToolTier.CORE

    def test_all_core_tools_get_core_tier(self):
        for name in CORE_TOOL_NAMES:
            assert _assign_tier(name) == ToolTier.CORE, f"{name} should be CORE"

    def test_meta_tool_gets_core_tier(self):
        assert _assign_tier(META_TOOL_NAME) == ToolTier.CORE

    def test_internal_tool_gets_internal_tier(self):
        for name in INTERNAL_TOOL_NAMES:
            assert _assign_tier(name) == ToolTier.INTERNAL, f"{name} should be INTERNAL"

    def test_unknown_tool_gets_extended_tier(self):
        assert _assign_tier("warden_some_random_tool") == ToolTier.EXTENDED

    def test_empty_name_gets_extended_tier(self):
        assert _assign_tier("") == ToolTier.EXTENDED


class TestCoreToolNames:
    """Tests for the CORE_TOOL_NAMES constant."""

    def test_exactly_8_core_tools(self):
        assert len(CORE_TOOL_NAMES) == 8

    def test_expected_core_tools_present(self):
        expected = {
            "warden_scan",
            "warden_execute_pipeline",
            "warden_get_all_issues",
            "warden_get_config",
            "warden_analyze_results",
            "warden_fix",
            "warden_status",
            "warden_list_frames",
        }
        assert CORE_TOOL_NAMES == expected


class TestToolRegistryTiering:
    """Tests for tier-based filtering in ToolRegistry."""

    @pytest.fixture
    def registry(self):
        """Create a registry with mixed-tier tools."""
        reg = ToolRegistry()
        reg.clear()

        # Register a CORE tool
        reg.register(
            MCPToolDefinition(
                name="warden_scan",
                description="Run scan",
                category=ToolCategory.SCAN,
                requires_bridge=True,
            )
        )
        # Register another CORE tool
        reg.register(
            MCPToolDefinition(
                name="warden_status",
                description="Get status",
                category=ToolCategory.STATUS,
                requires_bridge=False,
            )
        )
        # Register an EXTENDED tool
        reg.register(
            MCPToolDefinition(
                name="warden_search_code",
                description="Search code",
                category=ToolCategory.SEARCH,
                requires_bridge=True,
            )
        )
        # Register an INTERNAL tool
        reg.register(
            MCPToolDefinition(
                name="warden_health_check",
                description="Health check",
                category=ToolCategory.STATUS,
                requires_bridge=False,
            )
        )
        return reg

    def test_list_by_tier_core_returns_only_core(self, registry):
        tools = registry.list_by_tier(ToolTier.CORE)
        names = {t.name for t in tools}
        assert names == {"warden_scan", "warden_status"}

    def test_list_by_tier_extended_returns_core_and_extended(self, registry):
        tools = registry.list_by_tier(ToolTier.EXTENDED)
        names = {t.name for t in tools}
        assert names == {"warden_scan", "warden_status", "warden_search_code"}

    def test_list_by_tier_internal_returns_all(self, registry):
        tools = registry.list_by_tier(ToolTier.INTERNAL)
        names = {t.name for t in tools}
        assert names == {"warden_scan", "warden_status", "warden_search_code", "warden_health_check"}

    def test_list_by_tier_respects_bridge_available(self, registry):
        tools = registry.list_by_tier(ToolTier.CORE, bridge_available=False)
        names = {t.name for t in tools}
        # warden_scan requires bridge, should be excluded
        assert names == {"warden_status"}

    def test_list_by_tier_extended_respects_bridge_available(self, registry):
        tools = registry.list_by_tier(ToolTier.EXTENDED, bridge_available=False)
        names = {t.name for t in tools}
        # Only non-bridge tools
        assert names == {"warden_status"}

    def test_list_all_returns_everything(self, registry):
        tools = registry.list_all()
        assert len(tools) == 4

    def test_register_auto_assigns_core_tier(self):
        """Registering a CORE-named tool auto-assigns CORE tier."""
        reg = ToolRegistry()
        reg.clear()
        tool = MCPToolDefinition(
            name="warden_fix",
            description="Fix",
            category=ToolCategory.FORTIFICATION,
            tier=ToolTier.EXTENDED,  # adapter default
        )
        reg.register(tool)
        registered = reg.get("warden_fix")
        assert registered is not None
        assert registered.tier == ToolTier.CORE

    def test_register_auto_assigns_internal_tier(self):
        """Registering an INTERNAL-named tool auto-assigns INTERNAL tier."""
        reg = ToolRegistry()
        reg.clear()
        tool = MCPToolDefinition(
            name="warden_health_check",
            description="Health",
            category=ToolCategory.STATUS,
            tier=ToolTier.EXTENDED,  # adapter default
        )
        reg.register(tool)
        registered = reg.get("warden_health_check")
        assert registered is not None
        assert registered.tier == ToolTier.INTERNAL

    def test_register_leaves_extended_for_unknown_tools(self):
        """Unknown tool names stay at EXTENDED tier."""
        reg = ToolRegistry()
        reg.clear()
        tool = MCPToolDefinition(
            name="warden_custom_tool",
            description="Custom",
            category=ToolCategory.STATUS,
        )
        reg.register(tool)
        registered = reg.get("warden_custom_tool")
        assert registered is not None
        assert registered.tier == ToolTier.EXTENDED


class TestToolRegistryBuiltinTiers:
    """Tests for built-in tools having correct tiers."""

    def test_builtin_warden_status_is_core(self):
        reg = ToolRegistry()
        tool = reg.get("warden_status")
        assert tool is not None
        assert tool.tier == ToolTier.CORE

    def test_builtin_warden_scan_is_core(self):
        reg = ToolRegistry()
        tool = reg.get("warden_scan")
        assert tool is not None
        assert tool.tier == ToolTier.CORE

    def test_builtin_warden_get_config_is_core(self):
        reg = ToolRegistry()
        tool = reg.get("warden_get_config")
        assert tool is not None
        assert tool.tier == ToolTier.CORE

    def test_builtin_warden_list_frames_is_core(self):
        reg = ToolRegistry()
        tool = reg.get("warden_list_frames")
        assert tool is not None
        assert tool.tier == ToolTier.CORE

    def test_builtin_warden_list_reports_is_extended(self):
        reg = ToolRegistry()
        tool = reg.get("warden_list_reports")
        assert tool is not None
        assert tool.tier == ToolTier.EXTENDED

    def test_core_tier_returns_only_core_builtins(self):
        reg = ToolRegistry()
        core_tools = reg.list_by_tier(ToolTier.CORE)
        core_names = {t.name for t in core_tools}
        # warden_list_reports is EXTENDED, should not be in CORE list
        assert "warden_list_reports" not in core_names
        # CORE builtins should be present
        assert "warden_status" in core_names
        assert "warden_scan" in core_names
