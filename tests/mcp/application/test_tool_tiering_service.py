"""
Tests for MCPService tool tiering (tools/list filtering and warden_expand_tools).
"""

import json

import pytest

from warden.mcp.domain.enums import ToolCategory, ToolTier
from warden.mcp.domain.models import MCPToolDefinition, MCPToolResult


class TestMCPServiceToolTiering:
    """Tests for tool tier management in MCPService."""

    @pytest.fixture
    def service(self, tmp_path):
        """Create an MCPService instance with mocked transport."""
        from unittest.mock import AsyncMock, MagicMock

        from warden.mcp.application.mcp_service import MCPService

        transport = MagicMock()
        transport.is_open = True
        transport.read_message = AsyncMock(return_value=None)
        transport.write_message = AsyncMock()
        transport.close = AsyncMock()

        svc = MCPService(transport=transport, project_root=tmp_path)
        return svc

    def test_default_tier_is_core(self, service):
        """Service starts with CORE tier active."""
        assert service.active_tier == ToolTier.CORE

    def test_expand_tools_meta_tool_registered(self, service):
        """The warden_expand_tools meta-tool is registered."""
        tool = service.tool_executor.registry.get("warden_expand_tools")
        assert tool is not None
        assert tool.tier == ToolTier.CORE
        assert tool.category == ToolCategory.META
        assert tool.requires_bridge is False

    def test_expand_tools_to_extended(self, service):
        """Calling warden_expand_tools with tier=extended changes the active tier."""
        result = service._handle_expand_tools({"tier": "extended"})
        assert result["isError"] is False

        content = json.loads(result["content"][0]["text"])
        assert content["success"] is True
        assert content["previous_tier"] == "core"
        assert content["active_tier"] == "extended"
        assert service.active_tier == ToolTier.EXTENDED

    def test_expand_tools_back_to_core(self, service):
        """Can return from extended back to core."""
        service._handle_expand_tools({"tier": "extended"})
        assert service.active_tier == ToolTier.EXTENDED

        result = service._handle_expand_tools({"tier": "core"})
        content = json.loads(result["content"][0]["text"])
        assert content["success"] is True
        assert content["previous_tier"] == "extended"
        assert content["active_tier"] == "core"
        assert service.active_tier == ToolTier.CORE

    def test_expand_tools_invalid_tier(self, service):
        """Invalid tier value returns an error."""
        result = service._handle_expand_tools({"tier": "super"})
        assert result["isError"] is True

    def test_expand_tools_empty_tier(self, service):
        """Empty tier value returns an error."""
        result = service._handle_expand_tools({})
        assert result["isError"] is True

    def test_expand_tools_returns_tool_count(self, service):
        """Expand tools response includes visible and total tool counts."""
        result = service._handle_expand_tools({"tier": "extended"})
        content = json.loads(result["content"][0]["text"])
        assert "visible_tools" in content
        assert "total_tools" in content
        assert content["visible_tools"] >= content["visible_tools"]

    def test_expand_tools_returns_tool_names(self, service):
        """Expand tools response includes a list of visible tool names."""
        result = service._handle_expand_tools({"tier": "core"})
        content = json.loads(result["content"][0]["text"])
        assert "tools" in content
        assert isinstance(content["tools"], list)
        # warden_expand_tools itself should be in the core list
        assert "warden_expand_tools" in content["tools"]


class TestMCPServiceToolsListTiering:
    """Tests for tools/list respecting the active tier."""

    @pytest.fixture
    def service(self, tmp_path):
        """Create an MCPService with some registered tools."""
        from unittest.mock import AsyncMock, MagicMock

        from warden.mcp.application.mcp_service import MCPService

        transport = MagicMock()
        transport.is_open = True
        transport.read_message = AsyncMock(return_value=None)
        transport.write_message = AsyncMock()
        transport.close = AsyncMock()

        svc = MCPService(transport=transport, project_root=tmp_path)

        # Register an extended tool directly
        svc.tool_executor.registry.register(
            MCPToolDefinition(
                name="warden_search_code",
                description="Search code",
                category=ToolCategory.SEARCH,
                requires_bridge=False,
                tier=ToolTier.EXTENDED,
            )
        )

        return svc

    @pytest.mark.asyncio
    async def test_tools_list_at_core_tier(self, service):
        """At CORE tier, tools/list does not return EXTENDED tools."""
        from warden.mcp.domain.models import MCPSession

        session = MCPSession(session_id="test")
        result = await service._handle_tools_list_async(None, session)

        tool_names = {t["name"] for t in result["tools"]}
        assert "warden_search_code" not in tool_names
        # Core tools should be present
        assert "warden_status" in tool_names
        assert "warden_expand_tools" in tool_names

    @pytest.mark.asyncio
    async def test_tools_list_at_extended_tier(self, service):
        """At EXTENDED tier, tools/list returns both CORE and EXTENDED tools."""
        from warden.mcp.domain.models import MCPSession

        service._active_tier = ToolTier.EXTENDED
        session = MCPSession(session_id="test")
        result = await service._handle_tools_list_async(None, session)

        tool_names = {t["name"] for t in result["tools"]}
        assert "warden_search_code" in tool_names
        assert "warden_status" in tool_names
        assert "warden_expand_tools" in tool_names

    @pytest.mark.asyncio
    async def test_internal_tools_never_in_tools_list(self, service):
        """INTERNAL tools are never shown in tools/list at any tier."""
        from warden.mcp.domain.models import MCPSession

        # Register an internal tool
        service.tool_executor.registry.register(
            MCPToolDefinition(
                name="warden_health_check",
                description="Health check",
                category=ToolCategory.STATUS,
                requires_bridge=False,
                tier=ToolTier.INTERNAL,
            )
        )

        session = MCPSession(session_id="test")

        # Check at CORE
        result = await service._handle_tools_list_async(None, session)
        tool_names = {t["name"] for t in result["tools"]}
        assert "warden_health_check" not in tool_names

        # Check at EXTENDED
        service._active_tier = ToolTier.EXTENDED
        result = await service._handle_tools_list_async(None, session)
        tool_names = {t["name"] for t in result["tools"]}
        assert "warden_health_check" not in tool_names


class TestExpandToolsE2E:
    """End-to-end test via the message handler."""

    @pytest.fixture
    def service(self, tmp_path):
        from unittest.mock import AsyncMock, MagicMock

        from warden.mcp.application.mcp_service import MCPService

        transport = MagicMock()
        transport.is_open = True
        transport.read_message = AsyncMock(return_value=None)
        transport.write_message = AsyncMock()
        transport.close = AsyncMock()

        return MCPService(transport=transport, project_root=tmp_path)

    @pytest.mark.asyncio
    async def test_tools_call_expand_tools_via_message(self, service):
        """Test calling warden_expand_tools through the message handler."""
        from warden.mcp.domain.models import MCPSession

        session = MCPSession(session_id="test")
        session.mark_initialized()

        params = {
            "name": "warden_expand_tools",
            "arguments": {"tier": "extended"},
        }
        result = await service._handle_tools_call_async(params, session)

        content = json.loads(result["content"][0]["text"])
        assert content["success"] is True
        assert content["active_tier"] == "extended"
        assert service.active_tier == ToolTier.EXTENDED
