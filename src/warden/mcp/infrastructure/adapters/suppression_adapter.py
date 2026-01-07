"""
Suppression Adapter

MCP adapter for issue suppression management.
Maps to gRPC SuppressionMixin functionality.
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid

from warden.mcp.infrastructure.adapters.base_adapter import BaseWardenAdapter
from warden.mcp.domain.models import MCPToolDefinition, MCPToolResult
from warden.mcp.domain.enums import ToolCategory


class SuppressionAdapter(BaseWardenAdapter):
    """
    Adapter for suppression management tools.

    Tools:
        - warden_add_suppression: Add suppression rule
        - warden_remove_suppression: Remove rule
        - warden_get_suppressions: List all rules
        - warden_check_suppression: Check if suppressed
    """

    SUPPORTED_TOOLS = frozenset({
        "warden_add_suppression",
        "warden_remove_suppression",
        "warden_get_suppressions",
        "warden_check_suppression",
    })
    TOOL_CATEGORY = ToolCategory.SUPPRESSION

    def __init__(self, project_root: Path, bridge: Any = None) -> None:
        """Initialize suppression adapter with state."""
        super().__init__(project_root, bridge)
        # In-memory suppression state
        self._suppressions: Dict[str, Dict[str, Any]] = {}

    def get_tool_definitions(self) -> List[MCPToolDefinition]:
        """Get suppression tool definitions."""
        return [
            self._create_tool_definition(
                name="warden_add_suppression",
                description="Add a suppression rule to ignore specific issues",
                properties={
                    "rule_id": {
                        "type": "string",
                        "description": "Rule/check ID to suppress (e.g., 'SQL_INJECTION')",
                    },
                    "file_path": {
                        "type": "string",
                        "description": "Specific file path (optional, leave empty for global)",
                    },
                    "line_number": {
                        "type": "integer",
                        "description": "Specific line number (optional)",
                    },
                    "justification": {
                        "type": "string",
                        "description": "Reason for suppression",
                    },
                    "created_by": {
                        "type": "string",
                        "description": "Who created the suppression",
                    },
                    "expires_at": {
                        "type": "string",
                        "description": "Expiration date (ISO format, optional)",
                    },
                    "is_global": {
                        "type": "boolean",
                        "description": "Apply to all files",
                        "default": False,
                    },
                },
                required=["rule_id", "justification", "created_by"],
            ),
            self._create_tool_definition(
                name="warden_remove_suppression",
                description="Remove a suppression rule",
                properties={
                    "suppression_id": {
                        "type": "string",
                        "description": "Suppression rule ID to remove",
                    },
                },
                required=["suppression_id"],
            ),
            self._create_tool_definition(
                name="warden_get_suppressions",
                description="Get all suppression rules",
                properties={},
            ),
            self._create_tool_definition(
                name="warden_check_suppression",
                description="Check if a specific issue is suppressed",
                properties={
                    "rule_id": {
                        "type": "string",
                        "description": "Rule/check ID",
                    },
                    "file_path": {
                        "type": "string",
                        "description": "File path",
                    },
                    "line_number": {
                        "type": "integer",
                        "description": "Line number (optional)",
                    },
                },
                required=["rule_id", "file_path"],
            ),
        ]

    async def _execute_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> MCPToolResult:
        """Execute suppression tool."""
        handlers = {
            "warden_add_suppression": self._add_suppression,
            "warden_remove_suppression": self._remove_suppression,
            "warden_get_suppressions": self._get_suppressions,
            "warden_check_suppression": self._check_suppression,
        }

        handler = handlers.get(tool_name)
        if handler:
            return await handler(arguments)
        return MCPToolResult.error(f"Unknown tool: {tool_name}")

    async def _add_suppression(self, arguments: Dict[str, Any]) -> MCPToolResult:
        """Add a suppression rule."""
        rule_id = arguments.get("rule_id")
        justification = arguments.get("justification")
        created_by = arguments.get("created_by")

        if not rule_id:
            return MCPToolResult.error("Missing required parameter: rule_id")
        if not justification:
            return MCPToolResult.error("Missing required parameter: justification")
        if not created_by:
            return MCPToolResult.error("Missing required parameter: created_by")

        suppression_id = str(uuid.uuid4())
        suppression = {
            "id": suppression_id,
            "rule_id": rule_id,
            "file_path": arguments.get("file_path"),
            "line_number": arguments.get("line_number"),
            "justification": justification,
            "created_by": created_by,
            "created_at": datetime.utcnow().isoformat(),
            "expires_at": arguments.get("expires_at"),
            "is_global": arguments.get("is_global", False),
            "enabled": True,
        }

        self._suppressions[suppression_id] = suppression

        return MCPToolResult.json_result({
            "success": True,
            "suppression": suppression,
        })

    async def _remove_suppression(self, arguments: Dict[str, Any]) -> MCPToolResult:
        """Remove a suppression rule."""
        suppression_id = arguments.get("suppression_id")

        if not suppression_id:
            return MCPToolResult.error("Missing required parameter: suppression_id")

        if suppression_id not in self._suppressions:
            return MCPToolResult.error(f"Suppression not found: {suppression_id}")

        del self._suppressions[suppression_id]

        return MCPToolResult.json_result({
            "success": True,
            "message": f"Suppression {suppression_id} removed",
        })

    async def _get_suppressions(self, arguments: Dict[str, Any]) -> MCPToolResult:
        """Get all suppression rules."""
        return MCPToolResult.json_result({
            "suppressions": list(self._suppressions.values()),
            "total_count": len(self._suppressions),
        })

    async def _check_suppression(self, arguments: Dict[str, Any]) -> MCPToolResult:
        """Check if an issue is suppressed."""
        rule_id = arguments.get("rule_id")
        file_path = arguments.get("file_path")
        line_number = arguments.get("line_number")

        if not rule_id:
            return MCPToolResult.error("Missing required parameter: rule_id")
        if not file_path:
            return MCPToolResult.error("Missing required parameter: file_path")

        # Check for matching suppression
        for supp in self._suppressions.values():
            if not supp.get("enabled", True):
                continue

            # Check expiration
            if supp.get("expires_at"):
                try:
                    expires = datetime.fromisoformat(supp["expires_at"])
                    if datetime.utcnow() > expires:
                        continue
                except ValueError:
                    pass

            # Check rule match
            if supp["rule_id"] != rule_id:
                continue

            # Check global suppression
            if supp.get("is_global"):
                return MCPToolResult.json_result({
                    "is_suppressed": True,
                    "suppression": supp,
                    "reason": "Global suppression",
                })

            # Check file match
            if supp.get("file_path") and supp["file_path"] != file_path:
                continue

            # Check line match (if specified)
            if supp.get("line_number") and line_number:
                if supp["line_number"] != line_number:
                    continue

            return MCPToolResult.json_result({
                "is_suppressed": True,
                "suppression": supp,
                "reason": supp.get("justification", "Suppressed"),
            })

        return MCPToolResult.json_result({
            "is_suppressed": False,
            "suppression": None,
            "reason": None,
        })
