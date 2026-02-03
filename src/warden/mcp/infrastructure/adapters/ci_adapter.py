"""
CI Adapter

MCP adapter for CI/CD workflow management tools.
Provides tools for AI agents to manage CI configurations.
"""

from typing import Any, Dict, List

from warden.mcp.infrastructure.adapters.base_adapter import BaseWardenAdapter
from warden.mcp.domain.models import MCPToolDefinition, MCPToolResult
from warden.mcp.domain.enums import ToolCategory

from warden.services.ci_manager import CIManager, CIProvider


class CIAdapter(BaseWardenAdapter):
    """
    Adapter for CI/CD management tools.

    Tools:
        - warden_ci_init: Initialize CI workflows
        - warden_ci_update: Update workflows from templates
        - warden_ci_sync: Sync with current configuration
        - warden_ci_get_status: Get CI workflow status
    """

    SUPPORTED_TOOLS = frozenset({
        "warden_ci_init",
        "warden_ci_update",
        "warden_ci_sync",
        "warden_ci_get_status",
    })
    TOOL_CATEGORY = ToolCategory.CONFIG

    def get_tool_definitions(self) -> List[MCPToolDefinition]:
        """Get CI tool definitions."""
        return [
            self._create_tool_definition(
                name="warden_ci_init",
                description="Initialize CI/CD workflows for GitHub Actions or GitLab CI. Creates workflow files from templates.",
                properties={
                    "provider": {
                        "type": "string",
                        "description": "CI provider: 'github' or 'gitlab'",
                        "enum": ["github", "gitlab"],
                    },
                    "branch": {
                        "type": "string",
                        "description": "Default branch name (default: 'main')",
                        "default": "main",
                    },
                    "force": {
                        "type": "boolean",
                        "description": "Overwrite existing workflow files",
                        "default": False,
                    },
                },
                required=["provider"],
            ),
            self._create_tool_definition(
                name="warden_ci_update",
                description="Update CI workflows from latest templates. Preserves custom sections marked with WARDEN-CUSTOM comments.",
                properties={
                    "preserve_custom": {
                        "type": "boolean",
                        "description": "Preserve custom sections in workflow files (default: true)",
                        "default": True,
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "Show what would be updated without making changes",
                        "default": False,
                    },
                },
            ),
            self._create_tool_definition(
                name="warden_ci_sync",
                description="Sync CI workflows with current Warden configuration. Updates LLM provider and environment variables.",
                properties={},
            ),
            self._create_tool_definition(
                name="warden_ci_get_status",
                description="Get current CI workflow status including version info, update availability, and custom sections.",
                properties={},
            ),
        ]

    async def _execute_tool_async(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> MCPToolResult:
        """Execute CI tool."""
        if tool_name == "warden_ci_init":
            return await self._ci_init_async(arguments)
        elif tool_name == "warden_ci_update":
            return await self._ci_update_async(arguments)
        elif tool_name == "warden_ci_sync":
            return await self._ci_sync_async()
        elif tool_name == "warden_ci_get_status":
            return await self._ci_get_status_async()
        else:
            return MCPToolResult.error(f"Unknown tool: {tool_name}")

    def _get_ci_manager(self) -> CIManager:
        """Get CI manager instance."""
        return CIManager(project_root=self.project_root)

    async def _ci_init_async(self, arguments: Dict[str, Any]) -> MCPToolResult:
        """
        Initialize CI workflows.

        Args:
            arguments: Tool arguments (provider, branch, force)

        Returns:
            MCPToolResult with creation status
        """
        provider_str = arguments.get("provider", "").lower()
        branch = arguments.get("branch", "main")
        force = arguments.get("force", False)

        # Validate provider
        try:
            provider = CIProvider(provider_str)
        except ValueError:
            return MCPToolResult.error(
                f"Invalid provider: {provider_str}. Must be 'github' or 'gitlab'."
            )

        try:
            manager = self._get_ci_manager()
            result = manager.init(
                provider=provider,
                branch=branch,
                force=force,
            )

            if result.get("success"):
                return MCPToolResult.json_result({
                    "status": "success",
                    "provider": provider.value,
                    "created": result.get("created", []),
                    "skipped": result.get("skipped", []),
                    "message": f"CI workflows initialized for {provider.value}",
                })
            else:
                return MCPToolResult.json_result({
                    "status": "partial",
                    "provider": provider.value,
                    "created": result.get("created", []),
                    "errors": result.get("errors", []),
                })

        except Exception as e:
            return MCPToolResult.error(f"Failed to initialize CI: {e}")

    async def _ci_update_async(self, arguments: Dict[str, Any]) -> MCPToolResult:
        """
        Update CI workflows from templates.

        Args:
            arguments: Tool arguments (preserve_custom, dry_run)

        Returns:
            MCPToolResult with update status
        """
        preserve_custom = arguments.get("preserve_custom", True)
        dry_run = arguments.get("dry_run", False)

        try:
            manager = self._get_ci_manager()
            result = manager.update(
                preserve_custom=preserve_custom,
                dry_run=dry_run,
            )

            if "error" in result:
                return MCPToolResult.error(result["error"])

            return MCPToolResult.json_result({
                "status": "success" if result.get("success") else "partial",
                "dry_run": dry_run,
                "updated": result.get("updated", []),
                "unchanged": result.get("unchanged", []),
                "errors": result.get("errors", []),
                "message": "Dry run complete" if dry_run else "CI workflows updated",
            })

        except Exception as e:
            return MCPToolResult.error(f"Failed to update CI: {e}")

    async def _ci_sync_async(self) -> MCPToolResult:
        """
        Sync CI workflows with configuration.

        Returns:
            MCPToolResult with sync status
        """
        try:
            manager = self._get_ci_manager()
            result = manager.sync()

            if "error" in result:
                return MCPToolResult.error(result["error"])

            return MCPToolResult.json_result({
                "status": "success" if result.get("success") else "partial",
                "synced": result.get("synced", []),
                "errors": result.get("errors", []),
                "message": "CI workflows synced with configuration",
            })

        except Exception as e:
            return MCPToolResult.error(f"Failed to sync CI: {e}")

    async def _ci_get_status_async(self) -> MCPToolResult:
        """
        Get CI workflow status.

        Returns:
            MCPToolResult with status information
        """
        try:
            manager = self._get_ci_manager()
            status_data = manager.to_dict()

            return MCPToolResult.json_result({
                "status": "configured" if status_data.get("is_configured") else "not_configured",
                **status_data,
            })

        except Exception as e:
            return MCPToolResult.error(f"Failed to get CI status: {e}")
