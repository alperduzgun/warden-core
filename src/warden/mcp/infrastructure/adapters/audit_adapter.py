"""
Audit Context Adapter

MCP adapter for code graph intelligence and audit context tools.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from warden.mcp.domain.enums import ToolCategory
from warden.mcp.domain.models import MCPToolDefinition, MCPToolResult
from warden.mcp.infrastructure.adapters.base_adapter import BaseWardenAdapter

# Lazy import types — used at runtime only inside methods
_QUERY_TYPES = frozenset(
    {
        "search",
        "who_uses",
        "who_inherits",
        "who_implements",
        "dependency_chain",
        "callers",
        "callees",
    }
)

_SYMBOL_KINDS = frozenset(
    {
        "class",
        "function",
        "method",
        "mixin",
        "interface",
        "module",
    }
)

# Result caps
_MAX_EDGES = 50
_MAX_NODES = 20
_MAX_CHAINS = 20
_MAX_GRAPH_SEARCH = 50
_DEFAULT_GRAPH_SEARCH_LIMIT = 20
_MAX_DEPTH = 10
_DEFAULT_DEPTH = 5


class AuditAdapter(BaseWardenAdapter):
    """
    Adapter for audit context tools.

    Tools:
        - warden_get_audit_context: Get code graph + gap report summary
        - warden_query_symbol: Query a specific symbol in the code graph
        - warden_graph_search: Fuzzy/prefix search across the code graph
    """

    SUPPORTED_TOOLS = frozenset(
        {
            "warden_get_audit_context",
            "warden_query_symbol",
            "warden_graph_search",
        }
    )
    TOOL_CATEGORY = ToolCategory.ANALYSIS

    def __init__(self, project_root: Path, bridge: Any | None = None) -> None:
        super().__init__(project_root, bridge)
        self._code_graph_cache: Any | None = None  # CodeGraph instance

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
                    "Query a symbol in the code graph. Supports multiple query types: "
                    "search (default), who_uses, who_inherits, who_implements, "
                    "dependency_chain, callers, callees."
                ),
                properties={
                    "name": {
                        "type": "string",
                        "description": (
                            "Symbol name or FQN (e.g., 'SecurityFrame' or 'src/warden/foo.py::SecurityFrame')"
                        ),
                    },
                    "query_type": {
                        "type": "string",
                        "description": (
                            "Query mode: search (default), who_uses, who_inherits, "
                            "who_implements, dependency_chain, callers, callees"
                        ),
                        "enum": list(_QUERY_TYPES),
                        "default": "search",
                    },
                    "include_tests": {
                        "type": "boolean",
                        "description": "Include test files in results (default: false)",
                        "default": False,
                    },
                    "max_depth": {
                        "type": "integer",
                        "description": "Max depth for dependency_chain (default: 5, max: 10)",
                        "default": _DEFAULT_DEPTH,
                    },
                },
                required=["name"],
                requires_bridge=False,
            ),
            self._create_tool_definition(
                name="warden_graph_search",
                description=(
                    "Fuzzy/prefix search across the code graph symbols. Returns matching symbols sorted by relevance."
                ),
                properties={
                    "query": {
                        "type": "string",
                        "description": "Partial symbol name to search for",
                    },
                    "kind": {
                        "type": "string",
                        "description": "Filter by symbol kind",
                        "enum": list(_SYMBOL_KINDS),
                    },
                    "limit": {
                        "type": "integer",
                        "description": f"Max results (default: {_DEFAULT_GRAPH_SEARCH_LIMIT}, max: {_MAX_GRAPH_SEARCH})",
                        "default": _DEFAULT_GRAPH_SEARCH_LIMIT,
                    },
                },
                required=["query"],
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
        elif tool_name == "warden_graph_search":
            return await self._graph_search_async(arguments)
        return MCPToolResult.error(f"Unknown tool: {tool_name}")

    # ------------------------------------------------------------------
    # CodeGraph loading
    # ------------------------------------------------------------------

    def _load_code_graph(self) -> Any:
        """Load and cache CodeGraph from intelligence directory.

        Returns:
            CodeGraph domain model instance.

        Raises:
            FileNotFoundError: If code_graph.json does not exist.
        """
        if self._code_graph_cache is not None:
            return self._code_graph_cache

        cg_path = self.project_root / ".warden" / "intelligence" / "code_graph.json"
        if not cg_path.exists():
            raise FileNotFoundError("Code graph not found. Run 'warden refresh --force' first.")

        data = json.loads(cg_path.read_text(encoding="utf-8"))

        from warden.analysis.domain.code_graph import CodeGraph

        self._code_graph_cache = CodeGraph.model_validate(data)
        return self._code_graph_cache

    def _resolve_symbol(self, code_graph: Any, name: str) -> tuple[str | None, list[Any]]:
        """Resolve a symbol name to FQN and matching nodes.

        If name contains '::' it is treated as an exact FQN lookup.
        Otherwise searches by short name.

        Returns:
            (fqn_or_none, list_of_matching_nodes)
        """
        if "::" in name:
            node = code_graph.nodes.get(name)
            if node:
                return name, [node]
            return None, []

        matches = code_graph.get_symbols_by_name(name)
        if matches:
            return matches[0].fqn, matches
        return None, []

    # ------------------------------------------------------------------
    # warden_get_audit_context
    # ------------------------------------------------------------------

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

            code_graph, gap_report, dep_graph, chain_val = _load_intelligence(self.project_root)

            if not code_graph and not gap_report and not dep_graph and not chain_val:
                return MCPToolResult.error("No intelligence data found. Run 'warden refresh --force' first.")

            if fmt == "markdown":
                output = _render_markdown(
                    code_graph,
                    gap_report,
                    dep_graph,
                    full=full,
                    chain_validation=chain_val,
                    project_root=self.project_root,
                )
                return MCPToolResult(content=[{"type": "text", "text": output}])

            output = _render_json(code_graph, gap_report, dep_graph, full=full, chain_validation=chain_val)
            return MCPToolResult.json_result(json.loads(output))

        except Exception as e:
            return MCPToolResult.error(f"Failed to get audit context: {e}")

    # ------------------------------------------------------------------
    # warden_query_symbol
    # ------------------------------------------------------------------

    async def _query_symbol_async(self, arguments: dict[str, Any]) -> MCPToolResult:
        """Query a symbol by name in the code graph."""
        name = arguments.get("name", "")
        if not name:
            return MCPToolResult.error("Missing required parameter: name")

        query_type = arguments.get("query_type", "search")
        if query_type not in _QUERY_TYPES:
            return MCPToolResult.error(
                f"Invalid query_type '{query_type}'. Must be one of: {', '.join(sorted(_QUERY_TYPES))}"
            )

        try:
            code_graph = self._load_code_graph()
        except FileNotFoundError as e:
            return MCPToolResult.error(str(e))
        except Exception as e:
            return MCPToolResult.error(f"Symbol query failed: {e}")

        fqn, matches = self._resolve_symbol(code_graph, name)

        if query_type == "search":
            return self._result_search(name, fqn, matches, code_graph, arguments)

        # All other query types require at least one resolved symbol
        if not fqn:
            return MCPToolResult.json_result(
                {
                    "symbol": name,
                    "fqn": None,
                    "query_type": query_type,
                    "found": False,
                    "count": 0,
                    "results": [],
                }
            )

        include_tests = arguments.get("include_tests", False)
        max_depth = min(arguments.get("max_depth", _DEFAULT_DEPTH), _MAX_DEPTH)

        if query_type == "who_uses":
            return self._result_who_uses(name, fqn, code_graph, include_tests)
        elif query_type == "who_inherits":
            return self._result_who_inherits(name, fqn, code_graph)
        elif query_type == "who_implements":
            return self._result_who_implements(name, fqn, code_graph)
        elif query_type == "dependency_chain":
            return self._result_dependency_chain(name, fqn, code_graph, max_depth)
        elif query_type == "callers":
            return self._result_callers(name, fqn, code_graph, include_tests)
        elif query_type == "callees":
            return self._result_callees(name, fqn, code_graph)

        return MCPToolResult.error(f"Unhandled query_type: {query_type}")

    def _result_search(
        self,
        name: str,
        _fqn: str | None,
        matches: list[Any],
        code_graph: Any,
        _arguments: dict[str, Any],
    ) -> MCPToolResult:
        """Original search behavior: find symbol + related edges."""
        if not matches:
            return MCPToolResult.json_result(
                {
                    "symbol": name,
                    "query_type": "search",
                    "found": False,
                    "matches": [],
                }
            )

        serialized_matches = [
            {"fqn": m.fqn, **m.model_dump(by_alias=False, exclude={"fqn"})} for m in matches[:_MAX_NODES]
        ]

        match_fqns = {m.fqn for m in matches}
        related_edges = [
            e.model_dump(by_alias=False) for e in code_graph.edges if e.source in match_fqns or e.target in match_fqns
        ][:_MAX_EDGES]

        # Check LSP confirmation
        lsp_confirmed = None
        cv_path = self.project_root / ".warden" / "intelligence" / "chain_validation.json"
        if cv_path.exists():
            try:
                cv_data = json.loads(cv_path.read_text(encoding="utf-8"))
                dead_symbols = cv_data.get("dead_symbols", [])
                if cv_data.get("lsp_available", False):
                    lsp_confirmed = name not in dead_symbols
            except (json.JSONDecodeError, OSError):
                pass

        result_data: dict[str, Any] = {
            "symbol": name,
            "query_type": "search",
            "found": True,
            "matches": serialized_matches,
            "edges": related_edges,
        }
        if lsp_confirmed is not None:
            result_data["lsp_confirmed"] = lsp_confirmed

        return MCPToolResult.json_result(result_data)

    def _result_who_uses(self, name: str, fqn: str, code_graph: Any, include_tests: bool) -> MCPToolResult:
        """Return edges where target == fqn."""
        edges = code_graph.who_uses(fqn, include_tests=include_tests)
        serialized = [e.model_dump(by_alias=False) for e in edges[:_MAX_EDGES]]
        return MCPToolResult.json_result(
            {
                "symbol": name,
                "fqn": fqn,
                "query_type": "who_uses",
                "found": True,
                "count": len(serialized),
                "results": serialized,
            }
        )

    def _result_who_inherits(self, name: str, fqn: str, code_graph: Any) -> MCPToolResult:
        """Return nodes that inherit from fqn."""
        nodes = code_graph.who_inherits(fqn)
        serialized = [{"fqn": n.fqn, **n.model_dump(by_alias=False, exclude={"fqn"})} for n in nodes[:_MAX_NODES]]
        return MCPToolResult.json_result(
            {
                "symbol": name,
                "fqn": fqn,
                "query_type": "who_inherits",
                "found": True,
                "count": len(serialized),
                "results": serialized,
            }
        )

    def _result_who_implements(self, name: str, fqn: str, code_graph: Any) -> MCPToolResult:
        """Return nodes that implement fqn."""
        nodes = code_graph.who_implements(fqn)
        serialized = [{"fqn": n.fqn, **n.model_dump(by_alias=False, exclude={"fqn"})} for n in nodes[:_MAX_NODES]]
        return MCPToolResult.json_result(
            {
                "symbol": name,
                "fqn": fqn,
                "query_type": "who_implements",
                "found": True,
                "count": len(serialized),
                "results": serialized,
            }
        )

    def _result_dependency_chain(self, name: str, fqn: str, code_graph: Any, max_depth: int) -> MCPToolResult:
        """Return dependency chains from fqn."""
        chains = code_graph.get_dependency_chain(fqn, max_depth=max_depth)
        serialized = [[e.model_dump(by_alias=False) for e in chain] for chain in chains[:_MAX_CHAINS]]
        return MCPToolResult.json_result(
            {
                "symbol": name,
                "fqn": fqn,
                "query_type": "dependency_chain",
                "found": True,
                "count": len(serialized),
                "max_depth": max_depth,
                "results": serialized,
            }
        )

    def _result_callers(self, name: str, fqn: str, code_graph: Any, include_tests: bool) -> MCPToolResult:
        """Return who_uses edges filtered to CALLS relation only."""
        from warden.analysis.domain.code_graph import EdgeRelation

        edges = code_graph.who_uses(fqn, include_tests=include_tests)
        call_edges = [e for e in edges if e.relation == EdgeRelation.CALLS]
        serialized = [e.model_dump(by_alias=False) for e in call_edges[:_MAX_EDGES]]
        return MCPToolResult.json_result(
            {
                "symbol": name,
                "fqn": fqn,
                "query_type": "callers",
                "found": True,
                "count": len(serialized),
                "results": serialized,
            }
        )

    def _result_callees(self, name: str, fqn: str, code_graph: Any) -> MCPToolResult:
        """Return outgoing CALLS edges from fqn."""
        from warden.analysis.domain.code_graph import EdgeRelation

        callees = [e for e in code_graph.edges if e.source == fqn and e.relation == EdgeRelation.CALLS]
        serialized = [e.model_dump(by_alias=False) for e in callees[:_MAX_EDGES]]
        return MCPToolResult.json_result(
            {
                "symbol": name,
                "fqn": fqn,
                "query_type": "callees",
                "found": True,
                "count": len(serialized),
                "results": serialized,
            }
        )

    # ------------------------------------------------------------------
    # warden_graph_search
    # ------------------------------------------------------------------

    async def _graph_search_async(self, arguments: dict[str, Any]) -> MCPToolResult:
        """Fuzzy/prefix search across all symbols in the code graph."""
        query = arguments.get("query", "")
        if not query:
            return MCPToolResult.error("Missing required parameter: query")

        kind_filter = arguments.get("kind")
        if kind_filter and kind_filter not in _SYMBOL_KINDS:
            return MCPToolResult.error(
                f"Invalid kind '{kind_filter}'. Must be one of: {', '.join(sorted(_SYMBOL_KINDS))}"
            )

        limit = min(arguments.get("limit", _DEFAULT_GRAPH_SEARCH_LIMIT), _MAX_GRAPH_SEARCH)

        try:
            code_graph = self._load_code_graph()
        except FileNotFoundError as e:
            return MCPToolResult.error(str(e))
        except Exception as e:
            return MCPToolResult.error(f"Graph search failed: {e}")

        # Collect candidates with match scores
        query_lower = query.lower()
        scored: list[tuple[int, int, Any]] = []  # (score, name_len, node)

        for node in code_graph.nodes.values():
            if kind_filter and node.kind.value != kind_filter:
                continue

            name = node.name
            name_lower = name.lower()

            # Score: 0 = exact, 1 = case-insensitive exact, 2 = prefix, 3 = substring
            if name == query:
                score = 0
            elif name_lower == query_lower:
                score = 1
            elif name_lower.startswith(query_lower):
                score = 2
            elif query_lower in name_lower:
                score = 3
            else:
                continue

            scored.append((score, len(name), node))

        scored.sort(key=lambda x: (x[0], x[1]))
        results = [
            {"fqn": item[2].fqn, **item[2].model_dump(by_alias=False, exclude={"fqn"})} for item in scored[:limit]
        ]

        return MCPToolResult.json_result(
            {
                "query": query,
                "kind": kind_filter,
                "found": len(results) > 0,
                "count": len(results),
                "results": results,
            }
        )
