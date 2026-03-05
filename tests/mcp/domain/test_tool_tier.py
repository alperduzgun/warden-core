"""
Tests for ToolTier enum and tier assignment logic.
"""

import pytest

from warden.mcp.domain.enums import ToolCategory, ToolTier
from warden.mcp.domain.models import MCPToolDefinition


class TestToolTierEnum:
    """Tests for the ToolTier enum values."""

    def test_core_tier_value(self):
        assert ToolTier.CORE.value == "core"

    def test_extended_tier_value(self):
        assert ToolTier.EXTENDED.value == "extended"

    def test_internal_tier_value(self):
        assert ToolTier.INTERNAL.value == "internal"

    def test_tier_is_string_enum(self):
        assert isinstance(ToolTier.CORE, str)
        assert ToolTier.CORE == "core"

    def test_all_tiers_defined(self):
        tiers = list(ToolTier)
        assert len(tiers) == 3
        assert ToolTier.CORE in tiers
        assert ToolTier.EXTENDED in tiers
        assert ToolTier.INTERNAL in tiers


class TestMCPToolDefinitionTier:
    """Tests for the tier field on MCPToolDefinition."""

    def test_default_tier_is_extended(self):
        tool = MCPToolDefinition(
            name="test_tool",
            description="A test tool",
            category=ToolCategory.STATUS,
        )
        assert tool.tier == ToolTier.EXTENDED

    def test_explicit_core_tier(self):
        tool = MCPToolDefinition(
            name="test_tool",
            description="A test tool",
            category=ToolCategory.STATUS,
            tier=ToolTier.CORE,
        )
        assert tool.tier == ToolTier.CORE

    def test_explicit_internal_tier(self):
        tool = MCPToolDefinition(
            name="test_tool",
            description="A test tool",
            category=ToolCategory.STATUS,
            tier=ToolTier.INTERNAL,
        )
        assert tool.tier == ToolTier.INTERNAL

    def test_tier_does_not_affect_mcp_format(self):
        """Tier is an internal concept - not exposed in the MCP protocol format."""
        tool = MCPToolDefinition(
            name="test_tool",
            description="A test tool",
            category=ToolCategory.STATUS,
            tier=ToolTier.CORE,
        )
        mcp_format = tool.to_mcp_format()
        assert "tier" not in mcp_format
        assert mcp_format["name"] == "test_tool"
        assert mcp_format["description"] == "A test tool"


class TestToolCategoryMeta:
    """Tests for the META tool category."""

    def test_meta_category_exists(self):
        assert ToolCategory.META.value == "meta"
