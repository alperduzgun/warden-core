"""
In-memory GraphStore implementation.

Pure-Python test double backed by dicts.  Serves as both the default
backend for tests and a reference implementation of the GraphStore ABC.
No external dependencies, no disk I/O.
"""

from __future__ import annotations

import fnmatch
import logging
from collections import defaultdict
from typing import Any

from warden.analysis.domain.code_graph import EdgeRelation, SymbolEdge, SymbolIntent, SymbolKind, SymbolNode
from warden.analysis.domain.graph_store import CYCLE_RELATIONS, GraphStore, detect_cycles
from warden.analysis.services.graph_store_factory import register_backend

logger = logging.getLogger(__name__)


class MemoryGraphStore(GraphStore):
    """In-memory graph store backed by plain dicts and lists."""

    def __init__(self) -> None:
        self._files: dict[str, dict[str, str]] = {}  # file_path -> {content_hash}
        self._nodes: dict[str, SymbolNode] = {}  # fqn -> SymbolNode
        self._edges: list[SymbolEdge] = []
        self._intents: dict[str, SymbolIntent] = {}  # fqn -> SymbolIntent
        self._closed = False

    # ── write path ────────────────────────────────────────────────────

    def upsert_file(self, file_path: str, *, content_hash: str = "") -> None:
        self._ensure_open()
        self._files[file_path] = {"content_hash": content_hash}

    def upsert_symbols(self, symbols: list[SymbolNode]) -> None:
        self._ensure_open()
        for sym in symbols:
            self._nodes[sym.fqn] = sym

    def upsert_edges(self, edges: list[SymbolEdge]) -> None:
        self._ensure_open()
        self._edges.extend(edges)

    def delete_file(self, file_path: str) -> None:
        self._ensure_open()
        self._files.pop(file_path, None)
        # Remove symbols belonging to this file.
        fqns_to_remove = [fqn for fqn, n in self._nodes.items() if n.file_path == file_path]
        for fqn in fqns_to_remove:
            del self._nodes[fqn]
        # Remove edges where either endpoint was in this file.
        self._edges = [e for e in self._edges if e.source not in fqns_to_remove and e.target not in fqns_to_remove]
        for fqn in fqns_to_remove:
            self._intents.pop(fqn, None)

    # ── intent / centrality (Layer A, #690) ───────────────────────────

    def compute_fan_in(self) -> dict[str, int]:
        self._ensure_open()
        # Key on the raw target string (FQN for resolved edges, short name for
        # unresolved CALLS/INHERITS), mirroring the SQLite COALESCE aggregate.
        counts: dict[str, int] = defaultdict(int)
        for edge in self._edges:
            if edge.target:
                counts[edge.target] += 1
        return dict(counts)

    def upsert_intents(self, intents: list[SymbolIntent]) -> None:
        self._ensure_open()
        for intent in intents:
            if intent.fqn in self._nodes:
                self._intents[intent.fqn] = intent

    def get_intent(self, symbol_fqn: str) -> SymbolIntent | None:
        self._ensure_open()
        return self._intents.get(symbol_fqn)

    # ── read path ─────────────────────────────────────────────────────

    def who_uses(self, symbol_fqn: str, *, include_tests: bool = False) -> list[SymbolEdge]:
        self._ensure_open()
        results: list[SymbolEdge] = []
        for edge in self._edges:
            if edge.target != symbol_fqn:
                continue
            if not include_tests:
                source_node = self._nodes.get(edge.source)
                if source_node and source_node.is_test:
                    continue
            results.append(edge)
        return results

    def callers(self, symbol_fqn: str) -> list[SymbolNode]:
        self._ensure_open()
        caller_fqns = {e.source for e in self._edges if e.target == symbol_fqn and e.relation == EdgeRelation.CALLS}
        return [self._nodes[fqn] for fqn in caller_fqns if fqn in self._nodes]

    def callees(self, symbol_fqn: str) -> list[SymbolNode]:
        self._ensure_open()
        callee_fqns = {e.target for e in self._edges if e.source == symbol_fqn and e.relation == EdgeRelation.CALLS}
        return [self._nodes[fqn] for fqn in callee_fqns if fqn in self._nodes]

    def impact(self, target_fqn: str, *, max_depth: int = 5) -> list[list[SymbolEdge]]:
        self._ensure_open()
        chains: list[list[SymbolEdge]] = []
        queue: list[tuple[str, list[SymbolEdge]]] = [(target_fqn, [])]
        visited: set[str] = set()

        while queue:
            current, path = queue.pop(0)
            if current in visited or len(path) >= max_depth:
                continue
            visited.add(current)

            outgoing = [e for e in self._edges if e.source == current]
            for edge in outgoing:
                new_path = [*path, edge]
                chains.append(new_path)
                queue.append((edge.target, new_path))

        return chains

    def reverse_impact(self, fqn: str, *, max_depth: int = 5, include_tests: bool = False) -> list[list[SymbolEdge]]:
        self._ensure_open()
        chains: list[list[SymbolEdge]] = []
        queue: list[tuple[str, list[SymbolEdge]]] = [(fqn, [])]
        visited: set[str] = set()

        semantic_relations = {
            EdgeRelation.CALLS,
            EdgeRelation.INHERITS,
            EdgeRelation.IMPLEMENTS,
            EdgeRelation.IMPORTS,
        }

        while queue:
            current, path = queue.pop(0)
            if current in visited or len(path) >= max_depth:
                continue
            visited.add(current)

            incoming = [e for e in self._edges if e.target == current and e.relation in semantic_relations]
            for edge in incoming:
                if not include_tests:
                    source_node = self._nodes.get(edge.source)
                    if source_node and source_node.is_test:
                        continue
                new_path = [*path, edge]
                chains.append(new_path)
                queue.append((edge.source, new_path))

        return chains

    def find_orphan_symbols(self) -> list[SymbolNode]:
        self._ensure_open()
        connected: set[str] = set()
        for edge in self._edges:
            connected.add(edge.source)
            connected.add(edge.target)
        return [node for fqn, node in self._nodes.items() if fqn not in connected]

    def find_circular_deps(self) -> list[list[str]]:
        self._ensure_open()
        adjacency: dict[str, list[str]] = {}
        for edge in self._edges:
            if edge.relation in CYCLE_RELATIONS:
                adjacency.setdefault(edge.source, []).append(edge.target)
        return detect_cycles(adjacency)

    def get_node(self, fqn: str) -> SymbolNode | None:
        self._ensure_open()
        return self._nodes.get(fqn)

    def who_inherits(self, fqn: str) -> list[SymbolNode]:
        self._ensure_open()
        child_fqns = {e.source for e in self._edges if e.target == fqn and e.relation == EdgeRelation.INHERITS}
        return [self._nodes[f] for f in child_fqns if f in self._nodes]

    def who_implements(self, fqn: str) -> list[SymbolNode]:
        self._ensure_open()
        impl_fqns = {e.source for e in self._edges if e.target == fqn and e.relation == EdgeRelation.IMPLEMENTS}
        return [self._nodes[f] for f in impl_fqns if f in self._nodes]

    def edges_from(self, fqn: str, *, relation: EdgeRelation | None = None) -> list[SymbolEdge]:
        self._ensure_open()
        if relation is not None:
            return [e for e in self._edges if e.source == fqn and e.relation == relation]
        return [e for e in self._edges if e.source == fqn]

    def search(self, query: str, *, kind: str | None = None, limit: int = 50) -> list[SymbolNode]:
        self._ensure_open()
        q = query.lower()
        results: list[SymbolNode] = []
        for node in self._nodes.values():
            if q not in node.name.lower() and q not in node.fqn.lower():
                continue
            if kind is not None and node.kind.value != kind:
                continue
            results.append(node)
            if len(results) >= limit:
                break
        return results

    # ── introspection ─────────────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        # Always allow status queries — even after close.
        return {
            "backend": "memory",
            "node_count": len(self._nodes),
            "edge_count": len(self._edges),
            "file_count": len(self._files),
            "closed": self._closed,
        }

    def export_json(self) -> dict[str, Any]:
        self._ensure_open()
        return {
            "nodes": [n.model_dump(mode="json") for n in self._nodes.values()],
            "edges": [e.model_dump(mode="json") for e in self._edges],
        }

    # ── lifecycle ─────────────────────────────────────────────────────

    def close(self) -> None:
        self._closed = True
        self._files.clear()
        self._nodes.clear()
        self._edges.clear()
        self._intents.clear()

    # ── internal ──────────────────────────────────────────────────────

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("MemoryGraphStore has been closed.")


# Self-register so the factory can find us.
register_backend("memory", MemoryGraphStore)
