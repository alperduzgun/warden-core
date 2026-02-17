"""
CI Adapter

MCP adapter for CI/CD workflow management tools.
Provides tools for AI agents to manage CI configurations.

Chaos Engineering Principles:
- Fail Fast: Validate inputs immediately
- Idempotent: Safe to call multiple times
- Observable: Structured logging and error reporting
- Defensive: Sanitize all inputs, handle all errors
"""

from __future__ import annotations

from typing import Any

from warden.mcp.domain.enums import ToolCategory
from warden.mcp.domain.models import MCPToolDefinition, MCPToolResult
from warden.mcp.infrastructure.adapters.base_adapter import BaseWardenAdapter
from warden.services.ci_manager import (
    CIManager,
    CIManagerError,
    CIProvider,
    FileOperationError,
    SecurityError,
    TemplateError,
    ValidationError,
)

try:
    from warden.shared.infrastructure.logging import get_logger

    logger = get_logger(__name__)
except ImportError:
    import logging

    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)


class CIAdapter(BaseWardenAdapter):
    """
    Adapter for CI/CD management tools.

    Provides AI agents with tools to:
    - Initialize CI workflows
    - Update workflows from templates
    - Sync with current configuration
    - Check workflow status

    All operations are idempotent and safe to retry.
    """

    SUPPORTED_TOOLS = frozenset(
        {
            "warden_ci_init",
            "warden_ci_update",
            "warden_ci_sync",
            "warden_ci_get_status",
        }
    )
    TOOL_CATEGORY = ToolCategory.CONFIG

    def get_tool_definitions(self) -> list[MCPToolDefinition]:
        """Get CI tool definitions."""
        return [
            self._create_tool_definition(
                name="warden_ci_init",
                description=(
                    "Initialize CI/CD workflows for GitHub Actions or GitLab CI. "
                    "Creates workflow files from templates. Idempotent: existing files "
                    "are skipped unless force=true."
                ),
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
                        "description": "Overwrite existing workflow files (default: false)",
                        "default": False,
                    },
                },
                required=["provider"],
            ),
            self._create_tool_definition(
                name="warden_ci_update",
                description=(
                    "Update CI workflows from latest templates. "
                    "Preserves custom sections marked with WARDEN-CUSTOM comments. "
                    "Use dry_run=true to preview changes."
                ),
                properties={
                    "preserve_custom": {
                        "type": "boolean",
                        "description": "Preserve custom sections (default: true)",
                        "default": True,
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "Preview changes without applying (default: false)",
                        "default": False,
                    },
                },
            ),
            self._create_tool_definition(
                name="warden_ci_sync",
                description=(
                    "Sync CI workflows with current Warden configuration. "
                    "Updates LLM provider and environment variables without "
                    "changing workflow structure."
                ),
                properties={},
            ),
            self._create_tool_definition(
                name="warden_ci_get_status",
                description=(
                    "Get current CI workflow status including provider, "
                    "version info, update availability, and custom sections."
                ),
                properties={},
            ),
        ]

    async def _execute_tool_async(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> MCPToolResult:
        """Execute CI tool with proper error handling."""
        logger.info(
            "ci_adapter_execute",
            tool=tool_name,
            arguments=list(arguments.keys()),
        )

        try:
            if tool_name == "warden_ci_init":
                return await self._ci_init_async(arguments)
            elif tool_name == "warden_ci_update":
                return await self._ci_update_async(arguments)
            elif tool_name == "warden_ci_sync":
                return await self._ci_sync_async()
            elif tool_name == "warden_ci_get_status":
                return await self._ci_get_status_async()
            else:
                logger.warning("ci_adapter_unknown_tool", tool=tool_name)
                return MCPToolResult.error(f"Unknown tool: {tool_name}")

        except CIManagerError as e:
            logger.error("ci_adapter_manager_error", tool=tool_name, error=str(e))
            return MCPToolResult.error(f"CI Manager Error: {e}")
        except Exception as e:
            logger.error("ci_adapter_unexpected_error", tool=tool_name, error=str(e))
            return MCPToolResult.error(f"Unexpected error: {e}")

    def _get_ci_manager(self) -> CIManager:
        """
        Get CI manager instance with validation.

        Raises:
            ValidationError: If project root is invalid
        """
        return CIManager(project_root=self.project_root)

    async def _ci_init_async(self, arguments: dict[str, Any]) -> MCPToolResult:
        """
        Initialize CI workflows.

        Args:
            arguments: Tool arguments (provider, branch, force)

        Returns:
            MCPToolResult with creation status
        """
        provider_str = arguments.get("provider", "")
        branch = arguments.get("branch", "main")
        force = arguments.get("force", False)

        # Validate provider (fail fast)
        if not provider_str:
            return MCPToolResult.error("Missing required argument: provider")

        if not isinstance(provider_str, str):
            return MCPToolResult.error("Provider must be a string")

        try:
            provider = CIProvider.from_string(provider_str)
        except ValidationError as e:
            return MCPToolResult.error(str(e))

        # Validate branch
        if not isinstance(branch, str):
            return MCPToolResult.error("Branch must be a string")

        # Validate force
        if not isinstance(force, bool):
            force = bool(force)

        logger.info(
            "ci_adapter_init_started",
            provider=provider.value,
            branch=branch,
            force=force,
        )

        try:
            manager = self._get_ci_manager()
            result = manager.init(
                provider=provider,
                branch=branch,
                force=force,
            )

            logger.info(
                "ci_adapter_init_completed",
                success=result.get("success"),
                created=len(result.get("created", [])),
                errors=len(result.get("errors", [])),
            )

            if result.get("success"):
                return MCPToolResult.json_result(
                    {
                        "status": "success",
                        "provider": provider.value,
                        "created": result.get("created", []),
                        "skipped": result.get("skipped", []),
                        "message": f"CI workflows initialized for {provider.value}",
                    }
                )
            else:
                return MCPToolResult.json_result(
                    {
                        "status": "partial",
                        "provider": provider.value,
                        "created": result.get("created", []),
                        "skipped": result.get("skipped", []),
                        "errors": result.get("errors", []),
                    }
                )

        except (ValidationError, SecurityError) as e:
            return MCPToolResult.error(str(e))
        except (TemplateError, FileOperationError) as e:
            return MCPToolResult.error(f"File operation failed: {e}")

    async def _ci_update_async(self, arguments: dict[str, Any]) -> MCPToolResult:
        """
        Update CI workflows from templates.

        Args:
            arguments: Tool arguments (preserve_custom, dry_run)

        Returns:
            MCPToolResult with update status
        """
        preserve_custom = arguments.get("preserve_custom", True)
        dry_run = arguments.get("dry_run", False)

        # Coerce to bool
        if not isinstance(preserve_custom, bool):
            preserve_custom = bool(preserve_custom)
        if not isinstance(dry_run, bool):
            dry_run = bool(dry_run)

        logger.info(
            "ci_adapter_update_started",
            preserve_custom=preserve_custom,
            dry_run=dry_run,
        )

        try:
            manager = self._get_ci_manager()
            result = manager.update(
                preserve_custom=preserve_custom,
                dry_run=dry_run,
            )

            logger.info(
                "ci_adapter_update_completed",
                success=result.get("success"),
                updated=len(result.get("updated", [])),
                errors=len(result.get("errors", [])),
                dry_run=dry_run,
            )

            if "error" in result:
                return MCPToolResult.error(result["error"])

            return MCPToolResult.json_result(
                {
                    "status": "success" if result.get("success") else "partial",
                    "dry_run": dry_run,
                    "updated": result.get("updated", []),
                    "unchanged": result.get("unchanged", []),
                    "errors": result.get("errors", []),
                    "message": "Dry run complete" if dry_run else "CI workflows updated",
                }
            )

        except (ValidationError, SecurityError) as e:
            return MCPToolResult.error(str(e))
        except (TemplateError, FileOperationError) as e:
            return MCPToolResult.error(f"File operation failed: {e}")

    async def _ci_sync_async(self) -> MCPToolResult:
        """
        Sync CI workflows with configuration.

        Returns:
            MCPToolResult with sync status
        """
        logger.info("ci_adapter_sync_started")

        try:
            manager = self._get_ci_manager()
            result = manager.sync()

            logger.info(
                "ci_adapter_sync_completed",
                success=result.get("success"),
                synced=len(result.get("synced", [])),
                errors=len(result.get("errors", [])),
            )

            if "error" in result:
                return MCPToolResult.error(result["error"])

            return MCPToolResult.json_result(
                {
                    "status": "success" if result.get("success") else "partial",
                    "synced": result.get("synced", []),
                    "errors": result.get("errors", []),
                    "message": "CI workflows synced with configuration",
                }
            )

        except (ValidationError, SecurityError) as e:
            return MCPToolResult.error(str(e))
        except FileOperationError as e:
            return MCPToolResult.error(f"File operation failed: {e}")

    async def _ci_get_status_async(self) -> MCPToolResult:
        """
        Get CI workflow status.

        Returns:
            MCPToolResult with status information
        """
        logger.info("ci_adapter_status_started")

        try:
            manager = self._get_ci_manager()
            status_data = manager.to_dict()

            logger.info(
                "ci_adapter_status_completed",
                is_configured=status_data.get("is_configured"),
                workflow_count=len(status_data.get("workflows", {})),
            )

            return MCPToolResult.json_result(
                {
                    "status": "configured" if status_data.get("is_configured") else "not_configured",
                    **status_data,
                }
            )

        except ValidationError as e:
            return MCPToolResult.error(str(e))
