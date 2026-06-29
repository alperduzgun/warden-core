"""
Audit Context Adapter

MCP adapter for code graph intelligence and audit context tools.
Reads the symbol graph from the durable GraphStore DB (.warden/graph.db)
and gap/dep/chain data from .warden/intelligence/*.json.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from warden.analysis.domain.code_graph import EdgeRelation
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
        from warden.analysis.services.graph_store_factory import default_db_path

        self._db_path = default_db_path(project_root)

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
    # GraphStore helpers
    # ------------------------------------------------------------------

    def _open_store(self):
        """Open the SQLite GraphStore for the project.

        Returns:
            GraphStore instance.

        Raises:
            FileNotFoundError: If the graph DB does not exist.
        """
        if not self._db_path.exists():
            raise FileNotFoundError("Code graph not found. Run 'warden graph build' first.")
        from warden.analysis.services.graph_store_factory import get_graph_store

        return get_graph_store("sqlite", path=str(self._db_path))

    @staticmethod
    def _serialize_node(n):
        return {"fqn": n.fqn, **n.model_dump(by_alias=False, exclude={"fqn"})}

    @staticmethod
    def _serialize_edge(e):
        return e.model_dump(by_alias=False)

    def _resolve_symbol(self, store, name: str) -> tuple[str | None, list[Any]]:
        """Resolve a symbol name to FQN and matching nodes.

        If name contains '::' it is treated as an exact FQN lookup.
        Otherwise searches by short name.

        Returns:
            (fqn_or_none, list_of_matching_nodes)
        """
        if "::" in name:
            node = store.get_node(name)
            if node:
                return name, [node]
            return None, []

        matches = store.search(name, limit=_MAX_NODES)
        filtered = [m for m in matches if m.name == name]
        if filtered:
            return filtered[0].fqn, filtered
        return None, []

    # ------------------------------------------------------------------
    # warden_get_audit_context
    # ------------------------------------------------------------------

    async def _get_audit_context_async(self, arguments: dict[str, Any]) -> MCPToolResult:
        """Get audit context from the GraphStore DB and intelligence JSON files."""
        fmt = arguments.get("format", "json")
        full = arguments.get("full", False)

        try:
            from warden.analysis.services.graph_store_factory import get_graph_store
            from warden.cli.commands.audit_context import _load_json, _render_json, _render_markdown

            intel_dir = self.project_root / ".warden" / "intelligence"
            gap_report = _load_json(intel_dir / "gap_report.json")
            dep_graph = _load_json(intel_dir / "dependency_graph.json")
            chain_val = _load_json(intel_dir / "chain_validation.json")

            code_graph: dict[str, Any] = {}
            if self._db_path.exists():
                store = get_graph_store("sqlite", path=str(self._db_path))
                try:
                    export = store.export_json()
                    status = store.status()
                    nodes_list = export.get("nodes", [])
                    nodes = {n["fqn"]: n for n in nodes_list}
                    edges = export.get("edges", [])
                    code_graph = {
                        "nodes": nodes,
                        "edges": edges,
                        "stats": {
                            "total_nodes": status["node_count"],
                            "total_edges": status["edge_count"],
                            "classes": sum(1 for n in nodes_list if n.get("kind") == "class"),
                            "functions": sum(1 for n in nodes_list if n.get("kind") in ("function", "method")),
                            "test_nodes": sum(1 for n in nodes_list if n.get("is_test")),
                        },
                    }
                finally:
                    store.close()

            if not code_graph and not gap_report and not dep_graph and not chain_val:
                return MCPToolResult.error("No intelligence data found. Run 'warden graph build' first.")

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
            with self._open_store() as store:
                return await self._query_with_store(store, name, query_type, arguments)
        except FileNotFoundError as e:
            return MCPToolResult.error(str(e))
        except Exception as e:
            return MCPToolResult.error(f"Symbol query failed: {e}")

    async def _query_with_store(self, store, name: str, query_type: str, arguments: dict[str, Any]) -> MCPToolResult:
        """Execute symbol query against an open store."""
        fqn, matches = self._resolve_symbol(store, name)

        if query_type == "search":
            return self._result_search_with_store(name, fqn, matches, store, arguments)

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
            return self._result_who_uses(name, fqn, store, include_tests)
        elif query_type == "who_inherits":
            return self._result_who_inherits(name, fqn, store)
        elif query_type == "who_implements":
            return self._result_who_implements(name, fqn, store)
        elif query_type == "dependency_chain":
            return self._result_dependency_chain(name, fqn, store, max_depth)
        elif query_type == "callers":
            return self._result_callers(name, fqn, store, include_tests)
        elif query_type == "callees":
            return self._result_callees(name, fqn, store)

        return MCPToolResult.error(f"Unhandled query_type: {query_type}")

    def _result_search_with_store(
        self,
        name: str,
        _fqn: str | None,
        matches: list[Any],
        store: Any,
        _arguments: dict[str, Any],
    ) -> MCPToolResult:
        """Search for a symbol and include related edges."""
        if not matches:
            return MCPToolResult.json_result(
                {
                    "symbol": name,
                    "query_type": "search",
                    "found": False,
                    "matches": [],
                }
            )

        serialized_matches = [self._serialize_node(m) for m in matches[:_MAX_NODES]]

        related_edges: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for m in matches:
            for e in store.who_uses(m.fqn):
                key = (e.source, e.target, e.relation.value)
                if key not in seen:
                    seen.add(key)
                    related_edges.append(self._serialize_edge(e))
            for e in store.edges_from(m.fqn):
                key = (e.source, e.target, e.relation.value)
                if key not in seen:
                    seen.add(key)
                    related_edges.append(self._serialize_edge(e))
            if len(related_edges) >= _MAX_EDGES:
                break
        related_edges = related_edges[:_MAX_EDGES]

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

    def _result_who_uses(self, name: str, fqn: str, store: Any, include_tests: bool) -> MCPToolResult:
        """Return edges where target == fqn."""
        edges = store.who_uses(fqn, include_tests=include_tests)
        serialized = [self._serialize_edge(e) for e in edges[:_MAX_EDGES]]
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

    def _result_who_inherits(self, name: str, fqn: str, store: Any) -> MCPToolResult:
        """Return nodes that inherit from fqn."""
        nodes = store.who_inherits(fqn)
        serialized = [self._serialize_node(n) for n in nodes[:_MAX_NODES]]
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

    def _result_who_implements(self, name: str, fqn: str, store: Any) -> MCPToolResult:
        """Return nodes that implement fqn."""
        nodes = store.who_implements(fqn)
        serialized = [self._serialize_node(n) for n in nodes[:_MAX_NODES]]
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

    def _result_dependency_chain(self, name: str, fqn: str, store: Any, max_depth: int) -> MCPToolResult:
        """Return dependency chains from fqn."""
        chains = store.impact(fqn, max_depth=max_depth)
        serialized = [[self._serialize_edge(e) for e in chain] for chain in chains[:_MAX_CHAINS]]
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

    def _result_callers(self, name: str, fqn: str, store: Any, include_tests: bool) -> MCPToolResult:
        """Return who_uses edges filtered to CALLS relation only."""
        edges = store.who_uses(fqn, include_tests=include_tests)
        call_edges = [e for e in edges if e.relation == EdgeRelation.CALLS]
        serialized = [self._serialize_edge(e) for e in call_edges[:_MAX_EDGES]]
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

    def _result_callees(self, name: str, fqn: str, store: Any) -> MCPToolResult:
        """Return outgoing CALLS edges from fqn."""
        edges = store.edges_from(fqn, relation=EdgeRelation.CALLS)
        serialized = [self._serialize_edge(e) for e in edges[:_MAX_EDGES]]
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
            with self._open_store() as store:
                candidates = store.search(query, kind=kind_filter, limit=_MAX_GRAPH_SEARCH)
        except FileNotFoundError as e:
            return MCPToolResult.error(str(e))
        except Exception as e:
            return MCPToolResult.error(f"Graph search failed: {e}")

        query_lower = query.lower()
        scored: list[tuple[int, int, Any]] = []

        for node in candidates:
            name = node.name
            name_lower = name.lower()

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
        results = [self._serialize_node(item[2]) for item in scored[:limit]]

        return MCPToolResult.json_result(
            {
                "query": query,
                "kind": kind_filter,
                "found": len(results) > 0,
                "count": len(results),
                "results": results,
            }
        )
