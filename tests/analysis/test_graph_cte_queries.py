"""
Query-layer tests for SqliteGraphStore (#687).

Covers the recursive-CTE ``impact()``, indexed ``who_uses``/``callers``/``callees``
lookups (no O(E) scan), FTS5 ``search`` ranking/caps, and the ported
``find_orphan_symbols`` / ``find_circular_deps`` graph operations.

The differential test is the critical gate: the new CTE ``impact()`` and the
legacy in-Python BFS (``CodeGraph.get_dependency_chain``) must return identical
chain sets.
"""

from __future__ import annotations

import time

import pytest

from warden.analysis.domain.code_graph import (
    CodeGraph,
    EdgeRelation,
    SymbolEdge,
    SymbolKind,
    SymbolNode,
)
from warden.analysis.services.memory_graph_store import MemoryGraphStore
from warden.analysis.services.sqlite_graph_store import (
    _MAX_DEPTH,
    _MAX_IMPACT_RESULTS,
    SqliteGraphStore,
)

# ── helpers ───────────────────────────────────────────────────────────


def _node(fqn: str, *, file_path: str = "m.py", is_test: bool = False) -> SymbolNode:
    return SymbolNode(fqn=fqn, name=fqn.split("::")[-1], kind=SymbolKind.FUNCTION, file_path=file_path, is_test=is_test)


def _edge(src: str, tgt: str, relation: EdgeRelation = EdgeRelation.CALLS) -> SymbolEdge:
    return SymbolEdge(source=src, target=tgt, relation=relation)


def _normalise(chains: list[list[SymbolEdge]]) -> list[tuple[tuple[str, str, str], ...]]:
    """Collapse chains to a comparable, order-independent multiset."""
    return sorted(tuple((e.source, e.target, e.relation.value) for e in chain) for chain in chains)


def _build_both(
    nodes: list[SymbolNode], edges: list[SymbolEdge]
) -> tuple[SqliteGraphStore, CodeGraph]:
    """Populate a SqliteGraphStore and an in-memory CodeGraph from the same data."""
    store = SqliteGraphStore(":memory:")
    store.upsert_symbols(nodes)
    store.upsert_edges(edges)

    graph = CodeGraph()
    for n in nodes:
        graph.add_node(n)
    for e in edges:
        graph.add_edge(e)
    return store, graph


# ── differential gate: CTE impact() == legacy BFS ─────────────────────


class TestImpactDifferential:
    """New recursive-CTE impact() must match the OLD Python BFS exactly.

    Fixtures stay inside the domain where per-path traversal and the legacy
    global-visited BFS coincide: trees and simple cycles. (They only diverge on
    a node with multiple *incoming* paths that *also* has outgoing edges — a
    diamond fan-out — which is out of scope for this parity gate.)
    """

    def test_tree_matches_bfs_across_depths(self) -> None:
        nodes = [_node(n) for n in "ABCDEFG"]
        edges = [_edge(a, b) for a, b in [("A", "B"), ("A", "C"), ("B", "D"), ("B", "E"), ("C", "F"), ("D", "G")]]
        store, graph = _build_both(nodes, edges)
        try:
            for depth in range(1, 7):
                new = _normalise(store.impact("A", max_depth=depth))
                old = _normalise(graph.get_dependency_chain("A", max_depth=depth))
                assert new == old, f"depth={depth}: CTE diverged from BFS"
        finally:
            store.close()

    def test_simple_cycle_matches_bfs_and_terminates(self) -> None:
        nodes = [_node(n) for n in "XYZ"]
        edges = [_edge(a, b) for a, b in [("X", "Y"), ("Y", "Z"), ("Z", "X")]]
        store, graph = _build_both(nodes, edges)
        try:
            for depth in range(1, 6):
                new = _normalise(store.impact("X", max_depth=depth))
                old = _normalise(graph.get_dependency_chain("X", max_depth=depth))
                assert new == old, f"depth={depth}: cycle handling diverged"
        finally:
            store.close()

    def test_branching_with_back_edge_matches_bfs(self) -> None:
        # A->B->C->D plus a back-edge D->B (cycle) and a side branch A->E.
        nodes = [_node(n) for n in "ABCDE"]
        edges = [_edge(a, b) for a, b in [("A", "B"), ("B", "C"), ("C", "D"), ("D", "B"), ("A", "E")]]
        store, graph = _build_both(nodes, edges)
        try:
            for depth in range(1, 8):
                new = _normalise(store.impact("A", max_depth=depth))
                old = _normalise(graph.get_dependency_chain("A", max_depth=depth))
                assert new == old, f"depth={depth}: back-edge handling diverged"
        finally:
            store.close()


# ── impact() caps ─────────────────────────────────────────────────────


class TestImpactCaps:
    def test_max_depth_clamped_to_module_ceiling(self) -> None:
        # A linear chain longer than _MAX_DEPTH; asking for more is clamped.
        nodes = [_node(f"n{i}") for i in range(_MAX_DEPTH + 6)]
        edges = [_edge(f"n{i}", f"n{i + 1}") for i in range(_MAX_DEPTH + 5)]
        store = SqliteGraphStore(":memory:")
        store.upsert_symbols(nodes)
        store.upsert_edges(edges)
        try:
            chains = store.impact("n0", max_depth=1000)
            longest = max(len(c) for c in chains)
            assert longest == _MAX_DEPTH
        finally:
            store.close()

    def test_zero_or_negative_depth_returns_empty(self) -> None:
        store = SqliteGraphStore(":memory:")
        store.upsert_symbols([_node("a"), _node("b")])
        store.upsert_edges([_edge("a", "b")])
        try:
            assert store.impact("a", max_depth=0) == []
            assert store.impact("a", max_depth=-3) == []
        finally:
            store.close()

    def test_result_count_capped(self) -> None:
        # A star with more anchor edges than the result cap.
        fanout = _MAX_IMPACT_RESULTS + 200
        nodes = [_node("hub")] + [_node(f"leaf{i}") for i in range(fanout)]
        edges = [_edge("hub", f"leaf{i}") for i in range(fanout)]
        store = SqliteGraphStore(":memory:")
        store.upsert_symbols(nodes)
        store.upsert_edges(edges)
        try:
            chains = store.impact("hub", max_depth=5)
            assert len(chains) == _MAX_IMPACT_RESULTS
        finally:
            store.close()


# ── indexed lookups (no O(E) scan) ────────────────────────────────────


class TestIndexedLookups:
    """who_uses/callers/callees must hit an index, never full-scan `edges`."""

    def _plan(self, store: SqliteGraphStore, sql: str, params) -> str:
        rows = store._conn.execute("EXPLAIN QUERY PLAN " + sql, params).fetchall()
        return "\n".join(r["detail"] for r in rows)

    def test_who_uses_uses_index(self, ) -> None:
        store = SqliteGraphStore(":memory:")
        try:
            plan = self._plan(
                store,
                "SELECT e.relation FROM edges e WHERE e.target_id = ? OR e.target_fqn_hint = ?",
                (1, "x"),
            )
            assert "USING INDEX" in plan
            assert "SCAN e\n" not in plan and not plan.endswith("SCAN e")
        finally:
            store.close()

    def test_callers_uses_index(self) -> None:
        store = SqliteGraphStore(":memory:")
        try:
            plan = self._plan(
                store,
                "SELECT s.fqn FROM edges e JOIN symbols s ON s.id = e.source_id "
                "WHERE e.relation = ? AND (e.target_id = ? OR e.target_fqn_hint = ?)",
                ("calls", 1, "x"),
            )
            assert "USING INDEX" in plan
            assert "SCAN e\n" not in plan and not plan.endswith("SCAN e")
        finally:
            store.close()

    def test_callees_uses_source_index(self) -> None:
        store = SqliteGraphStore(":memory:")
        try:
            plan = self._plan(
                store,
                "SELECT s.fqn FROM edges e JOIN symbols s ON s.id = e.target_id "
                "WHERE e.relation = ? AND e.source_id = ?",
                ("calls", 1),
            )
            assert "idx_edges_source_rel" in plan
        finally:
            store.close()


class TestWhoUsesPerformance:
    """who_uses must answer in well under 50ms on a non-trivial graph."""

    def test_who_uses_under_50ms(self) -> None:
        store = SqliteGraphStore(":memory:")
        target = "core.py::target"
        nodes = [_node(target, file_path="core.py")]
        edges: list[SymbolEdge] = []
        # 5000 distinct callers of `target`, plus 5000 unrelated chain edges
        # so the table is genuinely large and a scan would be visibly slow.
        for i in range(5000):
            nodes.append(_node(f"caller{i}.py::c{i}", file_path=f"caller{i}.py"))
            edges.append(_edge(f"caller{i}.py::c{i}", target))
        for i in range(5000):
            nodes.append(_node(f"noise{i}.py::n{i}", file_path=f"noise{i}.py"))
        for i in range(4999):
            edges.append(_edge(f"noise{i}.py::n{i}", f"noise{i + 1}.py::n{i + 1}"))
        store.upsert_symbols(nodes)
        store.upsert_edges(edges)
        try:
            store.who_uses(target)  # warm caches
            best = min(_timed(lambda: store.who_uses(target)) for _ in range(3))
            assert len(store.who_uses(target)) == 5000
            assert best < 0.050, f"who_uses took {best * 1000:.1f}ms (>50ms)"
        finally:
            store.close()


def _timed(fn) -> float:
    start = time.perf_counter()
    fn()
    return time.perf_counter() - start


# ── FTS5 search ranking + caps ────────────────────────────────────────


class TestSearchRanking:
    def test_exact_name_ranks_above_prefix_noise(self) -> None:
        store = SqliteGraphStore(":memory:")
        nodes = [_node("a.py::handler", file_path="a.py")]
        # Many symbols that merely share the prefix should not bury the exact hit.
        nodes += [_node(f"b.py::handler_variant_{i}", file_path="b.py") for i in range(20)]
        store.upsert_symbols(nodes)
        try:
            results = store.search("handler", limit=5)
            assert results, "expected ranked FTS hits"
            assert "a.py::handler" in {n.fqn for n in results[:5]}
        finally:
            store.close()

    def test_search_respects_limit(self) -> None:
        store = SqliteGraphStore(":memory:")
        store.upsert_symbols([_node(f"m.py::sym{i}") for i in range(40)])
        try:
            assert len(store.search("sym", limit=7)) == 7
        finally:
            store.close()


# ── ported graph ops: orphans + cycles ────────────────────────────────


class TestPortedGraphOps:
    """find_orphan_symbols / find_circular_deps: parity across all backends."""

    @pytest.fixture()
    def fixture(self) -> tuple[list[SymbolNode], list[SymbolEdge]]:
        nodes = [
            _node("p.py::A", file_path="p.py"),
            _node("p.py::B", file_path="p.py"),
            _node("p.py::C", file_path="p.py"),
            _node("p.py::Lonely", file_path="p.py"),  # orphan
        ]
        edges = [
            _edge("p.py::A", "p.py::B", EdgeRelation.IMPORTS),
            _edge("p.py::B", "p.py::C", EdgeRelation.IMPORTS),
            _edge("p.py::C", "p.py::A", EdgeRelation.IMPORTS),  # cycle A->B->C->A
        ]
        return nodes, edges

    def test_orphans_match_legacy(self, fixture) -> None:
        nodes, edges = fixture
        sqlite, graph = _build_both(nodes, edges)
        mem = MemoryGraphStore()
        mem.upsert_symbols(nodes)
        mem.upsert_edges(edges)
        try:
            legacy = {n.fqn for n in graph.find_orphan_symbols()}
            assert {n.fqn for n in sqlite.find_orphan_symbols()} == legacy
            assert {n.fqn for n in mem.find_orphan_symbols()} == legacy
            assert legacy == {"p.py::Lonely"}
        finally:
            sqlite.close()
            mem.close()

    def test_circular_deps_match_legacy(self, fixture) -> None:
        nodes, edges = fixture
        sqlite, graph = _build_both(nodes, edges)
        mem = MemoryGraphStore()
        mem.upsert_symbols(nodes)
        mem.upsert_edges(edges)
        try:
            legacy = graph.find_circular_deps()
            assert sqlite.find_circular_deps() == legacy
            assert mem.find_circular_deps() == legacy
            assert len(legacy) == 1  # one cycle detected
        finally:
            sqlite.close()
            mem.close()

    def test_calls_edges_excluded_from_cycle_detection(self) -> None:
        # A call cycle is NOT a dependency cycle.
        nodes = [_node("q.py::A", file_path="q.py"), _node("q.py::B", file_path="q.py")]
        edges = [
            _edge("q.py::A", "q.py::B", EdgeRelation.CALLS),
            _edge("q.py::B", "q.py::A", EdgeRelation.CALLS),
        ]
        store = SqliteGraphStore(":memory:")
        store.upsert_symbols(nodes)
        store.upsert_edges(edges)
        try:
            assert store.find_circular_deps() == []
        finally:
            store.close()
