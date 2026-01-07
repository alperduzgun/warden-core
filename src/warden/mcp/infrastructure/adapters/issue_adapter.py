"""
Issue Management Adapter

MCP adapter for issue tracking and management tools.
Maps to gRPC IssueManagementMixin functionality.
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import hashlib
import uuid

from warden.mcp.infrastructure.adapters.base_adapter import BaseWardenAdapter
from warden.mcp.domain.models import MCPToolDefinition, MCPToolResult
from warden.mcp.domain.enums import ToolCategory


class IssueAdapter(BaseWardenAdapter):
    """
    Adapter for issue management tools.

    Tools:
        - warden_get_all_issues: Get all issues with filtering
        - warden_get_open_issues: Get open issues only
        - warden_get_issue_by_hash: Get specific issue
        - warden_resolve_issue: Mark as resolved
        - warden_suppress_issue: Mark as suppressed
        - warden_reopen_issue: Reopen issue
        - warden_get_issue_history: Get history
        - warden_get_issue_stats: Get statistics
    """

    SUPPORTED_TOOLS = frozenset({
        "warden_get_all_issues",
        "warden_get_open_issues",
        "warden_get_issue_by_hash",
        "warden_resolve_issue",
        "warden_suppress_issue",
        "warden_reopen_issue",
        "warden_get_issue_history",
        "warden_get_issue_stats",
    })
    TOOL_CATEGORY = ToolCategory.ISSUE

    def __init__(self, project_root: Path, bridge: Any = None) -> None:
        """Initialize issue adapter with state."""
        super().__init__(project_root, bridge)
        # In-memory issue state (mirrors gRPC servicer pattern)
        self._issues: Dict[str, Dict[str, Any]] = {}
        self._history: List[Dict[str, Any]] = []

    def get_tool_definitions(self) -> List[MCPToolDefinition]:
        """Get issue management tool definitions."""
        return [
            self._create_tool_definition(
                name="warden_get_all_issues",
                description="Get all issues with optional filtering by state, severity, frame, or file",
                properties={
                    "states": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["open", "resolved", "suppressed"]},
                        "description": "Filter by issue states",
                    },
                    "severities": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["critical", "high", "medium", "low", "info"]},
                        "description": "Filter by severities",
                    },
                    "frame_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Filter by frame IDs",
                    },
                    "file_path_pattern": {
                        "type": "string",
                        "description": "Filter by file path pattern (glob)",
                    },
                    "offset": {"type": "integer", "description": "Pagination offset", "default": 0},
                    "limit": {"type": "integer", "description": "Max results", "default": 100},
                },
            ),
            self._create_tool_definition(
                name="warden_get_open_issues",
                description="Get all open (unresolved) issues",
                properties={
                    "severities": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Filter by severities",
                    },
                    "frame_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Filter by frame IDs",
                    },
                },
            ),
            self._create_tool_definition(
                name="warden_get_issue_by_hash",
                description="Get a specific issue by its content hash",
                properties={
                    "hash": {"type": "string", "description": "Issue content hash"},
                },
                required=["hash"],
            ),
            self._create_tool_definition(
                name="warden_resolve_issue",
                description="Mark an issue as resolved",
                properties={
                    "issue_id": {"type": "string", "description": "Issue ID to resolve"},
                    "actor": {"type": "string", "description": "Who resolved the issue"},
                    "comment": {"type": "string", "description": "Resolution comment"},
                },
                required=["issue_id", "actor"],
            ),
            self._create_tool_definition(
                name="warden_suppress_issue",
                description="Mark an issue as suppressed (false positive)",
                properties={
                    "issue_id": {"type": "string", "description": "Issue ID to suppress"},
                    "actor": {"type": "string", "description": "Who suppressed the issue"},
                    "comment": {"type": "string", "description": "Suppression justification"},
                },
                required=["issue_id", "actor", "comment"],
            ),
            self._create_tool_definition(
                name="warden_reopen_issue",
                description="Reopen a resolved or suppressed issue",
                properties={
                    "issue_id": {"type": "string", "description": "Issue ID to reopen"},
                    "actor": {"type": "string", "description": "Who reopened the issue"},
                    "comment": {"type": "string", "description": "Reopen comment"},
                },
                required=["issue_id", "actor"],
            ),
            self._create_tool_definition(
                name="warden_get_issue_history",
                description="Get issue state change history",
                properties={},
            ),
            self._create_tool_definition(
                name="warden_get_issue_stats",
                description="Get issue statistics (counts by state, severity, frame)",
                properties={},
            ),
        ]

    async def _execute_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> MCPToolResult:
        """Execute issue management tool."""
        handlers = {
            "warden_get_all_issues": self._get_all_issues,
            "warden_get_open_issues": self._get_open_issues,
            "warden_get_issue_by_hash": self._get_issue_by_hash,
            "warden_resolve_issue": self._resolve_issue,
            "warden_suppress_issue": self._suppress_issue,
            "warden_reopen_issue": self._reopen_issue,
            "warden_get_issue_history": self._get_issue_history,
            "warden_get_issue_stats": self._get_issue_stats,
        }

        handler = handlers.get(tool_name)
        if handler:
            return await handler(arguments)
        return MCPToolResult.error(f"Unknown tool: {tool_name}")

    async def _get_all_issues(self, arguments: Dict[str, Any]) -> MCPToolResult:
        """Get all issues with filtering."""
        states = arguments.get("states", [])
        severities = arguments.get("severities", [])
        frame_ids = arguments.get("frame_ids", [])
        file_pattern = arguments.get("file_path_pattern", "")
        offset = arguments.get("offset", 0)
        limit = arguments.get("limit", 100)

        # Filter issues
        filtered = []
        for issue in self._issues.values():
            if states and issue.get("state") not in states:
                continue
            if severities and issue.get("severity") not in severities:
                continue
            if frame_ids and issue.get("frame_id") not in frame_ids:
                continue
            if file_pattern and file_pattern not in issue.get("file_path", ""):
                continue
            filtered.append(issue)

        # Paginate
        total = len(filtered)
        paginated = filtered[offset:offset + limit]

        return MCPToolResult.json_result({
            "total_count": total,
            "filtered_count": len(paginated),
            "issues": paginated,
        })

    async def _get_open_issues(self, arguments: Dict[str, Any]) -> MCPToolResult:
        """Get open issues only."""
        arguments["states"] = ["open"]
        return await self._get_all_issues(arguments)

    async def _get_issue_by_hash(self, arguments: Dict[str, Any]) -> MCPToolResult:
        """Get issue by content hash."""
        hash_value = arguments.get("hash")
        if not hash_value:
            return MCPToolResult.error("Missing required parameter: hash")

        for issue in self._issues.values():
            if issue.get("hash") == hash_value:
                return MCPToolResult.json_result(issue)

        return MCPToolResult.error(f"Issue not found: {hash_value}")

    async def _resolve_issue(self, arguments: Dict[str, Any]) -> MCPToolResult:
        """Resolve an issue."""
        issue_id = arguments.get("issue_id")
        actor = arguments.get("actor")
        comment = arguments.get("comment", "")

        if not issue_id:
            return MCPToolResult.error("Missing required parameter: issue_id")
        if not actor:
            return MCPToolResult.error("Missing required parameter: actor")

        if issue_id not in self._issues:
            return MCPToolResult.error(f"Issue not found: {issue_id}")

        # Update state
        self._issues[issue_id]["state"] = "resolved"
        self._issues[issue_id]["resolved_by"] = actor
        self._issues[issue_id]["resolved_at"] = datetime.utcnow().isoformat()

        # Record history
        self._history.append({
            "issue_id": issue_id,
            "action": "resolved",
            "actor": actor,
            "comment": comment,
            "timestamp": datetime.utcnow().isoformat(),
        })

        return MCPToolResult.json_result({
            "success": True,
            "issue": self._issues[issue_id],
        })

    async def _suppress_issue(self, arguments: Dict[str, Any]) -> MCPToolResult:
        """Suppress an issue."""
        issue_id = arguments.get("issue_id")
        actor = arguments.get("actor")
        comment = arguments.get("comment", "")

        if not issue_id:
            return MCPToolResult.error("Missing required parameter: issue_id")
        if not actor:
            return MCPToolResult.error("Missing required parameter: actor")

        if issue_id not in self._issues:
            return MCPToolResult.error(f"Issue not found: {issue_id}")

        # Update state
        self._issues[issue_id]["state"] = "suppressed"
        self._issues[issue_id]["suppressed_by"] = actor
        self._issues[issue_id]["suppressed_at"] = datetime.utcnow().isoformat()
        self._issues[issue_id]["suppression_reason"] = comment

        # Record history
        self._history.append({
            "issue_id": issue_id,
            "action": "suppressed",
            "actor": actor,
            "comment": comment,
            "timestamp": datetime.utcnow().isoformat(),
        })

        return MCPToolResult.json_result({
            "success": True,
            "issue": self._issues[issue_id],
        })

    async def _reopen_issue(self, arguments: Dict[str, Any]) -> MCPToolResult:
        """Reopen an issue."""
        issue_id = arguments.get("issue_id")
        actor = arguments.get("actor")
        comment = arguments.get("comment", "")

        if not issue_id:
            return MCPToolResult.error("Missing required parameter: issue_id")
        if not actor:
            return MCPToolResult.error("Missing required parameter: actor")

        if issue_id not in self._issues:
            return MCPToolResult.error(f"Issue not found: {issue_id}")

        # Update state
        self._issues[issue_id]["state"] = "open"
        self._issues[issue_id]["reopened_by"] = actor
        self._issues[issue_id]["reopened_at"] = datetime.utcnow().isoformat()

        # Record history
        self._history.append({
            "issue_id": issue_id,
            "action": "reopened",
            "actor": actor,
            "comment": comment,
            "timestamp": datetime.utcnow().isoformat(),
        })

        return MCPToolResult.json_result({
            "success": True,
            "issue": self._issues[issue_id],
        })

    async def _get_issue_history(self, arguments: Dict[str, Any]) -> MCPToolResult:
        """Get issue history."""
        return MCPToolResult.json_result({
            "history": self._history,
            "total_count": len(self._history),
        })

    async def _get_issue_stats(self, arguments: Dict[str, Any]) -> MCPToolResult:
        """Get issue statistics."""
        stats = {
            "total": len(self._issues),
            "by_state": {"open": 0, "resolved": 0, "suppressed": 0},
            "by_severity": {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0},
            "by_frame": {},
        }

        for issue in self._issues.values():
            state = issue.get("state", "open")
            severity = issue.get("severity", "medium")
            frame = issue.get("frame_id", "unknown")

            stats["by_state"][state] = stats["by_state"].get(state, 0) + 1
            stats["by_severity"][severity] = stats["by_severity"].get(severity, 0) + 1
            stats["by_frame"][frame] = stats["by_frame"].get(frame, 0) + 1

        return MCPToolResult.json_result(stats)

    def add_issue(self, issue: Dict[str, Any]) -> str:
        """Add an issue to the tracker (for pipeline integration)."""
        issue_id = str(uuid.uuid4())
        content = f"{issue.get('file_path', '')}:{issue.get('line', 0)}:{issue.get('message', '')}"
        issue_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

        self._issues[issue_id] = {
            "id": issue_id,
            "hash": issue_hash,
            "state": "open",
            "created_at": datetime.utcnow().isoformat(),
            **issue,
        }

        return issue_id
