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

from warden.analysis.domain.code_graph import SymbolEdge, SymbolIntent, SymbolNode


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
        """BFS impact analysis starting from ``target_fqn``.

        Returns list of paths (each path is a list of edges).
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
