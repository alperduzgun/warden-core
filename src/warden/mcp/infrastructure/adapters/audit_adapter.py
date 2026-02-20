"""
Audit Context Adapter

MCP adapter for code graph intelligence and audit context tools.
"""

from __future__ import annotations

import json
from typing import Any

from warden.mcp.domain.enums import ToolCategory
from warden.mcp.domain.models import MCPToolDefinition, MCPToolResult
from warden.mcp.infrastructure.adapters.base_adapter import BaseWardenAdapter


class AuditAdapter(BaseWardenAdapter):
    """
    Adapter for audit context tools.

    Tools:
        - warden_get_audit_context: Get code graph + gap report summary
        - warden_query_symbol: Query a specific symbol in the code graph
    """

    SUPPORTED_TOOLS = frozenset(
        {
            "warden_get_audit_context",
            "warden_query_symbol",
        }
    )
    TOOL_CATEGORY = ToolCategory.ANALYSIS

    def get_tool_definitions(self) -> list[MCPToolDefinition]:
        """Get audit tool definitions."""
        return [
            self._create_tool_definition(
                name="warden_get_audit_context",
                description=(
                    "Get audit context from code graph intelligence. "
                    "Returns code graph stats, gap analysis, and dependency info. "
                    "Use format='markdown' for LLM-friendly output."
                ),
                properties={
                    "format": {
                        "type": "string",
                        "description": "Output format: 'json' (default) or 'markdown'",
                        "enum": ["json", "markdown"],
                        "default": "json",
                    },
                    "full": {
                        "type": "boolean",
                        "description": "Include detailed symbol lists (default: false)",
                        "default": False,
                    },
                },
                requires_bridge=False,
            ),
            self._create_tool_definition(
                name="warden_query_symbol",
                description=(
                    "Query a symbol by name in the code graph. "
                    "Returns symbol info, edges, and usage data."
                ),
                properties={
                    "name": {
                        "type": "string",
                        "description": "Symbol name to search for (e.g., 'SecurityFrame')",
                    },
                },
                required=["name"],
                requires_bridge=False,
            ),
        ]

    async def _execute_tool_async(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> MCPToolResult:
        """Execute audit tool."""
        if tool_name == "warden_get_audit_context":
            return await self._get_audit_context_async(arguments)
        elif tool_name == "warden_query_symbol":
            return await self._query_symbol_async(arguments)
        return MCPToolResult.error(f"Unknown tool: {tool_name}")

    async def _get_audit_context_async(self, arguments: dict[str, Any]) -> MCPToolResult:
        """Get audit context from intelligence files."""
        fmt = arguments.get("format", "json")
        full = arguments.get("full", False)

        try:
            from warden.cli.commands.audit_context import (
                _load_intelligence,
                _render_json,
                _render_markdown,
            )

            code_graph, gap_report, dep_graph = _load_intelligence(self.project_root)

            if not code_graph and not gap_report and not dep_graph:
                return MCPToolResult.error(
                    "No intelligence data found. Run 'warden refresh --force' first."
                )

            if fmt == "markdown":
                output = _render_markdown(code_graph, gap_report, dep_graph, full=full)
                return MCPToolResult(content=[{"type": "text", "text": output}])

            output = _render_json(code_graph, gap_report, dep_graph, full=full)
            return MCPToolResult.json_result(json.loads(output))

        except Exception as e:
            return MCPToolResult.error(f"Failed to get audit context: {e}")

    async def _query_symbol_async(self, arguments: dict[str, Any]) -> MCPToolResult:
        """Query a symbol by name in the code graph."""
        name = arguments.get("name", "")
        if not name:
            return MCPToolResult.error("Missing required parameter: name")

        try:
            intel_dir = self.project_root / ".warden" / "intelligence"
            cg_path = intel_dir / "code_graph.json"

            if not cg_path.exists():
                return MCPToolResult.error(
                    "Code graph not found. Run 'warden refresh --force' first."
                )

            data = json.loads(cg_path.read_text(encoding="utf-8"))
            nodes = data.get("nodes", {})
            edges = data.get("edges", [])

            # Find matching symbols
            matches = []
            for fqn, node in nodes.items():
                if isinstance(node, dict) and node.get("name") == name:
                    matches.append({"fqn": fqn, **node})

            if not matches:
                return MCPToolResult.json_result({
                    "symbol": name,
                    "found": False,
                    "matches": [],
                })

            # Find edges for matched symbols
            match_fqns = {m["fqn"] for m in matches}
            related_edges = [
                e for e in edges
                if isinstance(e, dict) and (e.get("source") in match_fqns or e.get("target") in match_fqns)
            ]

            return MCPToolResult.json_result({
                "symbol": name,
                "found": True,
                "matches": matches,
                "edges": related_edges[:50],
            })

        except Exception as e:
            return MCPToolResult.error(f"Symbol query failed: {e}")
