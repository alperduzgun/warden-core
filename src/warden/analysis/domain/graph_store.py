"""
GraphStore Abstract Base Class.

The contract that insulates consumers from backend swaps.
All persistence backends (SQLite #686, Kuzu future) implement this interface.

Domain models (CodeGraph, SymbolNode, SymbolEdge) remain as the in-memory
build intermediate — persistence moves behind this ABC.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from warden.analysis.domain.code_graph import EdgeRelation, SymbolEdge, SymbolIntent, SymbolNode

# Edge relations that form the dependency graph for cycle detection.
# Calls are intentionally excluded — a call cycle is not an import cycle.
CYCLE_RELATIONS: frozenset[EdgeRelation] = frozenset(
    {EdgeRelation.INHERITS, EdgeRelation.IMPLEMENTS, EdgeRelation.IMPORTS}
)


def detect_cycles(adjacency: dict[str, list[str]]) -> list[list[str]]:
    """Detect dependency cycles in *adjacency* via DFS.

    Shared by every :class:`GraphStore` backend so the in-memory and SQLite
    implementations return byte-identical results. The algorithm is a direct
    port of :meth:`warden.analysis.domain.code_graph.CodeGraph.find_circular_deps`:
    a recursion stack tracks the active path and a cycle is recorded the first
    time a back-edge into the stack is found.

    Args:
        adjacency: Mapping of source FQN to the list of target FQNs it depends
            on. Insertion order determines traversal order (and therefore the
            order of the returned cycles).

    Returns:
        A list of cycles. Each cycle is a list of FQNs whose first element is
        repeated as the last to close the loop.
    """
    cycles: list[list[str]] = []
    visited: set[str] = set()
    rec_stack: set[str] = set()

    def _dfs(node: str, path: list[str]) -> None:
        visited.add(node)
        rec_stack.add(node)
        path.append(node)

        for neighbor in adjacency.get(node, []):
            if neighbor not in visited:
                _dfs(neighbor, path)
            elif neighbor in rec_stack:
                cycle_start = path.index(neighbor)
                cycle = path[cycle_start:] + [neighbor]
                if cycle not in cycles:
                    cycles.append(cycle)

        path.pop()
        rec_stack.discard(node)

    for node_fqn in adjacency:
        if node_fqn not in visited:
            _dfs(node_fqn, [])

    return cycles


class GraphStore(ABC):
    """
    Abstract interface for symbol graph persistence.

    Implementations must be context-manager compatible (support ``with``).
    All backends should honour the same method signatures so consumers
    can swap via :func:`get_graph_store` without code changes.
    """

    # ── write path ────────────────────────────────────────────────────

    @abstractmethod
    def upsert_file(self, file_path: str, *, content_hash: str = "") -> None:
        """Register or update a file entry in the store.

        Args:
            file_path: Relative path from project root.
            content_hash: Optional content hash for change detection.
        """

    @abstractmethod
    def upsert_symbols(self, symbols: list[SymbolNode]) -> None:
        """Bulk-insert or update symbol nodes.

        Args:
            symbols: List of SymbolNode domain objects.
        """

    @abstractmethod
    def upsert_edges(self, edges: list[SymbolEdge]) -> None:
        """Bulk-insert or update symbol edges.

        Args:
            edges: List of SymbolEdge domain objects.
        """

    @abstractmethod
    def delete_file(self, file_path: str) -> None:
        """Remove a file and all associated symbols/edges.

        Args:
            file_path: Relative path from project root.
        """

    # ── read path (graph queries) ─────────────────────────────────────

    @abstractmethod
    def who_uses(self, symbol_fqn: str, *, include_tests: bool = False) -> list[SymbolEdge]:
        """Find all edges whose *target* matches ``symbol_fqn``.

        Args:
            symbol_fqn: Fully-qualified name of the symbol to search for.
            include_tests: If False, exclude edges originating from test files.

        Returns:
            List of SymbolEdge objects pointing to this symbol.
        """

    @abstractmethod
    def callers(self, symbol_fqn: str) -> list[SymbolNode]:
        """Return symbols that *call* ``symbol_fqn`` (CALLS edges)."""

    @abstractmethod
    def callees(self, symbol_fqn: str) -> list[SymbolNode]:
        """Return symbols that ``symbol_fqn`` *calls* (CALLS edges)."""

    @abstractmethod
    def impact(self, target_fqn: str, *, max_depth: int = 5) -> list[list[SymbolEdge]]:
        """Depth-capped impact analysis starting from ``target_fqn``.

        Walks outgoing edges and returns every dependency chain (each chain is
        an ordered list of edges) reachable within ``max_depth`` hops. Cycles
        are cut once a node repeats on a path.

        Returns list of paths (each path is a list of edges).
        """

    @abstractmethod
    def find_orphan_symbols(self) -> list[SymbolNode]:
        """Return symbols with zero edges (neither a source nor a target).

        Mirrors :meth:`warden.analysis.domain.code_graph.CodeGraph.find_orphan_symbols`.
        """

    @abstractmethod
    def find_circular_deps(self) -> list[list[str]]:
        """Detect circular dependency cycles via DFS.

        Only ``inherits``/``implements``/``imports`` edges form the dependency
        graph (calls are excluded). Each cycle is returned as a list of FQNs
        where the first element is repeated as the last to close the loop.
        Mirrors :meth:`warden.analysis.domain.code_graph.CodeGraph.find_circular_deps`.
        """

    @abstractmethod
    def get_node(self, fqn: str) -> SymbolNode | None:
        """Fetch a single symbol by fully-qualified name.

        Args:
            fqn: Fully-qualified name of the symbol.

        Returns:
            SymbolNode if found, None otherwise.
        """

    @abstractmethod
    def who_inherits(self, fqn: str) -> list[SymbolNode]:
        """Return symbols that *inherit from* ``fqn`` (INHERITS edges → source nodes).

        Args:
            fqn: Fully-qualified name of the parent symbol.

        Returns:
            List of SymbolNode objects that inherit from this symbol.
        """

    @abstractmethod
    def who_implements(self, fqn: str) -> list[SymbolNode]:
        """Return symbols that *implement* ``fqn`` (IMPLEMENTS edges → source nodes).

        Args:
            fqn: Fully-qualified name of the mixin/interface.

        Returns:
            List of SymbolNode objects that implement this symbol.
        """

    @abstractmethod
    def edges_from(self, fqn: str, *, relation: EdgeRelation | None = None) -> list[SymbolEdge]:
        """Return all edges originating from ``fqn``, optionally filtered by relation.

        Args:
            fqn: Fully-qualified name of the source symbol.
            relation: Optional relation type to filter by.

        Returns:
            List of SymbolEdge objects originating from this symbol.
        """

    @abstractmethod
    def search(self, query: str, *, kind: str | None = None, limit: int = 50) -> list[SymbolNode]:
        """Search symbols by name or FQN substring.

        Args:
            query: Search string (matched against name and FQN).
            kind: Optional SymbolKind filter (e.g. "class", "function").
            limit: Maximum results to return.

        Returns:
            List of matching SymbolNode objects.
        """

    # ── intent / centrality (Layer A, #690) ───────────────────────────
    # Concrete defaults so backends without persistence (or reserved slots)
    # need no changes; durable backends override these.

    def compute_fan_in(self) -> dict[str, int]:
        """Return ``{target_fqn: incoming_edge_count}`` (symbol centrality)."""
        return {}

    def upsert_intents(self, intents: list[SymbolIntent]) -> None:
        """Persist deterministic Layer-A intent rows. Default: no-op."""
        return None

    # ── introspection ─────────────────────────────────────────────────

    @abstractmethod
    def status(self) -> dict[str, Any]:
        """Return backend status and statistics.

        Must include at least: ``backend``, ``node_count``, ``edge_count``.
        """

    @abstractmethod
    def export_json(self) -> dict[str, Any]:
        """Export the full graph as a JSON-serialisable dict.

        Returns a dict with ``nodes`` and ``edges`` lists matching
        the CodeGraph wire format.
        """

    # ── lifecycle ─────────────────────────────────────────────────────

    @abstractmethod
    def close(self) -> None:
        """Release backend resources (connections, file handles, etc.)."""

    # ── context-manager support ───────────────────────────────────────

    def __enter__(self) -> GraphStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
