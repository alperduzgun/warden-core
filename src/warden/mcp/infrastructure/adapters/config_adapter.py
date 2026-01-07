"""
Configuration Adapter

MCP adapter for configuration management tools.
Maps to gRPC ConfigurationMixin functionality.
"""

from pathlib import Path
from typing import Any, Dict, List

from warden.mcp.infrastructure.adapters.base_adapter import BaseWardenAdapter
from warden.mcp.domain.models import MCPToolDefinition, MCPToolResult
from warden.mcp.domain.enums import ToolCategory


class ConfigAdapter(BaseWardenAdapter):
    """
    Adapter for configuration tools.

    Tools:
        - warden_get_available_frames: List validation frames
        - warden_get_available_providers: List LLM providers
        - warden_get_configuration: Get full configuration
        - warden_update_configuration: Update settings
        - warden_update_frame_status: Enable/disable frame
    """

    SUPPORTED_TOOLS = frozenset({
        "warden_get_available_frames",
        "warden_get_available_providers",
        "warden_get_configuration",
        "warden_update_configuration",
        "warden_update_frame_status",
    })
    TOOL_CATEGORY = ToolCategory.CONFIG

    def get_tool_definitions(self) -> List[MCPToolDefinition]:
        """Get configuration tool definitions."""
        return [
            self._create_tool_definition(
                name="warden_get_available_frames",
                description="List all available validation frames with their status",
                properties={},
            ),
            self._create_tool_definition(
                name="warden_get_available_providers",
                description="List all available LLM providers and their status",
                properties={},
            ),
            self._create_tool_definition(
                name="warden_get_configuration",
                description="Get full Warden configuration including frames, providers, and settings",
                properties={},
            ),
            self._create_tool_definition(
                name="warden_update_configuration",
                description="Update Warden configuration settings",
                properties={
                    "settings": {
                        "type": "object",
                        "description": "Configuration settings to update",
                        "additionalProperties": True,
                    },
                },
                required=["settings"],
            ),
            self._create_tool_definition(
                name="warden_update_frame_status",
                description="Enable or disable a validation frame",
                properties={
                    "frame_id": {
                        "type": "string",
                        "description": "Frame identifier (e.g., 'security', 'chaos')",
                    },
                    "enabled": {
                        "type": "boolean",
                        "description": "Whether to enable (true) or disable (false) the frame",
                    },
                },
                required=["frame_id", "enabled"],
            ),
        ]

    async def _execute_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> MCPToolResult:
        """Execute configuration tool."""
        if tool_name == "warden_get_available_frames":
            return await self._get_available_frames()
        elif tool_name == "warden_get_available_providers":
            return await self._get_available_providers()
        elif tool_name == "warden_get_configuration":
            return await self._get_configuration()
        elif tool_name == "warden_update_configuration":
            return await self._update_configuration(arguments)
        elif tool_name == "warden_update_frame_status":
            return await self._update_frame_status(arguments)
        else:
            return MCPToolResult.error(f"Unknown tool: {tool_name}")

    async def _get_available_frames(self) -> MCPToolResult:
        """Get available validation frames."""
        if not self.bridge:
            return MCPToolResult.error("Warden bridge not available")

        try:
            frames = await self.bridge.get_available_frames()
            return MCPToolResult.json_result({
                "frames": frames,
                "total_count": len(frames),
            })
        except Exception as e:
            return MCPToolResult.error(f"Failed to get frames: {e}")

    async def _get_available_providers(self) -> MCPToolResult:
        """Get available LLM providers."""
        if not self.bridge:
            return MCPToolResult.error("Warden bridge not available")

        try:
            providers = await self.bridge.get_available_providers()
            return MCPToolResult.json_result({
                "providers": providers,
                "total_count": len(providers),
            })
        except Exception as e:
            return MCPToolResult.error(f"Failed to get providers: {e}")

    async def _get_configuration(self) -> MCPToolResult:
        """Get full Warden configuration."""
        if not self.bridge:
            return MCPToolResult.error("Warden bridge not available")

        try:
            config = await self.bridge.get_config()
            return MCPToolResult.json_result(config)
        except Exception as e:
            return MCPToolResult.error(f"Failed to get configuration: {e}")

    async def _update_configuration(self, arguments: Dict[str, Any]) -> MCPToolResult:
        """Update configuration settings."""
        settings = arguments.get("settings", {})

        if not self.bridge:
            return MCPToolResult.error("Warden bridge not available")

        try:
            # Check if bridge has update method
            if hasattr(self.bridge, "update_config"):
                result = await self.bridge.update_config(settings)
                return MCPToolResult.json_result(result)
            else:
                return MCPToolResult.error("Configuration update not supported")
        except Exception as e:
            return MCPToolResult.error(f"Failed to update configuration: {e}")

    async def _update_frame_status(self, arguments: Dict[str, Any]) -> MCPToolResult:
        """Update frame enabled status."""
        frame_id = arguments.get("frame_id")
        enabled = arguments.get("enabled")

        if not frame_id:
            return MCPToolResult.error("Missing required parameter: frame_id")
        if enabled is None:
            return MCPToolResult.error("Missing required parameter: enabled")

        if not self.bridge:
            return MCPToolResult.error("Warden bridge not available")

        try:
            result = await self.bridge.update_frame_status(frame_id, enabled)
            return MCPToolResult.json_result(result)
        except Exception as e:
            return MCPToolResult.error(f"Failed to update frame status: {e}")
