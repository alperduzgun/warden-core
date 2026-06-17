"""
Unit tests for GraphStore ABC, MemoryGraphStore, and backend factory.

Tests the contract interface and the in-memory reference implementation.
"""

from __future__ import annotations

import pytest

from warden.analysis.domain.code_graph import EdgeRelation, SymbolEdge, SymbolKind, SymbolNode
from warden.analysis.domain.graph_store import GraphStore
from warden.analysis.services.graph_store_factory import get_graph_store
from warden.analysis.services.memory_graph_store import MemoryGraphStore


# ── fixtures ──────────────────────────────────────────────────────────


@pytest.fixture()
def store() -> MemoryGraphStore:
    """Fresh in-memory store for each test."""
    return MemoryGraphStore()


@pytest.fixture()
def sample_nodes() -> list[SymbolNode]:
    """A small set of symbol nodes spanning kinds and files."""
    return [
        SymbolNode(
            fqn="src/app/main.py::App",
            name="App",
            kind=SymbolKind.CLASS,
            file_path="src/app/main.py",
            line=10,
            module="app.main",
        ),
        SymbolNode(
            fqn="src/app/main.py::run",
            name="run",
            kind=SymbolKind.FUNCTION,
            file_path="src/app/main.py",
            line=25,
            module="app.main",
        ),
        SymbolNode(
            fqn="src/app/utils.py::helper",
            name="helper",
            kind=SymbolKind.FUNCTION,
            file_path="src/app/utils.py",
            line=5,
            module="app.utils",
        ),
        SymbolNode(
            fqn="src/app/utils.py::format_output",
            name="format_output",
            kind=SymbolKind.FUNCTION,
            file_path="src/app/utils.py",
            line=30,
            module="app.utils",
        ),
        SymbolNode(
            fqn="tests/test_main.py::test_run",
            name="test_run",
            kind=SymbolKind.FUNCTION,
            file_path="tests/test_main.py",
            line=1,
            module="tests.test_main",
            is_test=True,
        ),
    ]


@pytest.fixture()
def sample_edges() -> list[SymbolEdge]:
    """Edges connecting the sample nodes."""
    return [
        SymbolEdge(source="src/app/main.py::App", target="src/app/main.py::run", relation=EdgeRelation.DEFINES),
        SymbolEdge(source="src/app/main.py::run", target="src/app/utils.py::helper", relation=EdgeRelation.CALLS),
        SymbolEdge(source="src/app/main.py::run", target="src/app/utils.py::format_output", relation=EdgeRelation.CALLS),
        SymbolEdge(source="tests/test_main.py::test_run", target="src/app/main.py::run", relation=EdgeRelation.CALLS),
    ]


# ── ABC contract tests ───────────────────────────────────────────────


class TestGraphStoreABC:
    """Verify the ABC cannot be instantiated and has all required methods."""

    def test_cannot_instantiate_abc(self) -> None:
        with pytest.raises(TypeError, match="GraphStore"):
            GraphStore()  # type: ignore[abstract]

    def test_abc_has_all_required_methods(self) -> None:
        expected = {
            "upsert_file",
            "upsert_symbols",
            "upsert_edges",
            "delete_file",
            "who_uses",
            "callers",
            "callees",
            "impact",
            "search",
            "status",
            "export_json",
            "close",
        }
        actual = {name for name in dir(GraphStore) if not name.startswith("_")}
        assert expected <= actual, f"Missing methods: {expected - actual}"

    def test_context_manager_protocol(self) -> None:
        assert hasattr(GraphStore, "__enter__")
        assert hasattr(GraphStore, "__exit__")


# ── MemoryGraphStore: write path ──────────────────────────────────────


class TestMemoryGraphStoreWrite:
    """Test upsert_file, upsert_symbols, upsert_edges, delete_file."""

    def test_upsert_file(self, store: MemoryGraphStore) -> None:
        store.upsert_file("src/foo.py", content_hash="abc123")
        assert store.status()["file_count"] == 1

    def test_upsert_symbols(self, store: MemoryGraphStore, sample_nodes: list[SymbolNode]) -> None:
        store.upsert_symbols(sample_nodes)
        assert store.status()["node_count"] == len(sample_nodes)

    def test_upsert_edges(self, store: MemoryGraphStore, sample_edges: list[SymbolEdge]) -> None:
        store.upsert_edges(sample_edges)
        assert store.status()["edge_count"] == len(sample_edges)

    def test_delete_file_removes_symbols_and_edges(
        self, store: MemoryGraphStore, sample_nodes: list[SymbolNode], sample_edges: list[SymbolEdge]
    ) -> None:
        store.upsert_symbols(sample_nodes)
        store.upsert_edges(sample_edges)

        initial_nodes = store.status()["node_count"]
        initial_edges = store.status()["edge_count"]

        # Delete utils.py — should remove helper + format_output + their edges
        store.delete_file("src/app/utils.py")

        remaining = store.status()
        assert remaining["node_count"] < initial_nodes
        assert remaining["edge_count"] < initial_edges

        # helper should be gone
        assert store.search("helper") == []

    def test_upsert_symbols_overwrites(self, store: MemoryGraphStore) -> None:
        node_v1 = SymbolNode(fqn="a.py::X", name="X", kind=SymbolKind.CLASS, file_path="a.py", line=1)
        node_v2 = SymbolNode(fqn="a.py::X", name="X", kind=SymbolKind.CLASS, file_path="a.py", line=99)
        store.upsert_symbols([node_v1])
        store.upsert_symbols([node_v2])
        assert store.status()["node_count"] == 1
        results = store.search("X")
        assert results[0].line == 99


# ── MemoryGraphStore: read path ───────────────────────────────────────


class TestMemoryGraphStoreRead:
    """Test who_uses, callers, callees, impact, search."""

    def _populate(self, store: MemoryGraphStore, nodes: list[SymbolNode], edges: list[SymbolEdge]) -> None:
        store.upsert_symbols(nodes)
        store.upsert_edges(edges)

    def test_who_uses_excludes_tests_by_default(
        self, store: MemoryGraphStore, sample_nodes: list[SymbolNode], sample_edges: list[SymbolEdge]
    ) -> None:
        self._populate(store, sample_nodes, sample_edges)
        # run is used by test_run (test) and App (non-test)
        uses = store.who_uses("src/app/main.py::run", include_tests=False)
        sources = {e.source for e in uses}
        assert "tests/test_main.py::test_run" not in sources

    def test_who_uses_includes_tests_when_flagged(
        self, store: MemoryGraphStore, sample_nodes: list[SymbolNode], sample_edges: list[SymbolEdge]
    ) -> None:
        self._populate(store, sample_nodes, sample_edges)
        uses = store.who_uses("src/app/main.py::run", include_tests=True)
        sources = {e.source for e in uses}
        assert "tests/test_main.py::test_run" in sources

    def test_callers(
        self, store: MemoryGraphStore, sample_nodes: list[SymbolNode], sample_edges: list[SymbolEdge]
    ) -> None:
        self._populate(store, sample_nodes, sample_edges)
        callers = store.callers("src/app/utils.py::helper")
        caller_fqns = {n.fqn for n in callers}
        assert "src/app/main.py::run" in caller_fqns

    def test_callees(
        self, store: MemoryGraphStore, sample_nodes: list[SymbolNode], sample_edges: list[SymbolEdge]
    ) -> None:
        self._populate(store, sample_nodes, sample_edges)
        callees = store.callees("src/app/main.py::run")
        callee_fqns = {n.fqn for n in callees}
        assert "src/app/utils.py::helper" in callee_fqns
        assert "src/app/utils.py::format_output" in callee_fqns

    def test_impact_returns_chains(
        self, store: MemoryGraphStore, sample_nodes: list[SymbolNode], sample_edges: list[SymbolEdge]
    ) -> None:
        self._populate(store, sample_nodes, sample_edges)
        chains = store.impact("src/app/utils.py::helper", max_depth=3)
        # helper has no outgoing CALLS edges, so direct chains = 0
        # But we look from run's perspective instead
        chains = store.impact("src/app/main.py::run", max_depth=2)
        assert len(chains) >= 2  # run -> helper, run -> format_output

    def test_impact_respects_max_depth(
        self, store: MemoryGraphStore, sample_nodes: list[SymbolNode], sample_edges: list[SymbolEdge]
    ) -> None:
        self._populate(store, sample_nodes, sample_edges)
        chains_d1 = store.impact("src/app/main.py::run", max_depth=1)
        chains_d3 = store.impact("src/app/main.py::run", max_depth=3)
        assert len(chains_d3) >= len(chains_d1)

    def test_search_by_name(
        self, store: MemoryGraphStore, sample_nodes: list[SymbolNode], sample_edges: list[SymbolEdge]
    ) -> None:
        self._populate(store, sample_nodes, sample_edges)
        results = store.search("helper")
        assert len(results) == 1
        assert results[0].fqn == "src/app/utils.py::helper"

    def test_search_by_fqn_substring(
        self, store: MemoryGraphStore, sample_nodes: list[SymbolNode], sample_edges: list[SymbolEdge]
    ) -> None:
        self._populate(store, sample_nodes, sample_edges)
        results = store.search("utils.py")
        assert len(results) >= 2

    def test_search_with_kind_filter(
        self, store: MemoryGraphStore, sample_nodes: list[SymbolNode], sample_edges: list[SymbolEdge]
    ) -> None:
        self._populate(store, sample_nodes, sample_edges)
        classes = store.search("", kind="class")
        assert all(n.kind == SymbolKind.CLASS for n in classes)

    def test_search_respects_limit(
        self, store: MemoryGraphStore, sample_nodes: list[SymbolNode], sample_edges: list[SymbolEdge]
    ) -> None:
        self._populate(store, sample_nodes, sample_edges)
        results = store.search("", limit=2)
        assert len(results) <= 2


# ── MemoryGraphStore: introspection ───────────────────────────────────


class TestMemoryGraphStoreIntrospection:
    """Test status, export_json."""

    def test_status_has_required_keys(self, store: MemoryGraphStore) -> None:
        s = store.status()
        assert "backend" in s
        assert s["backend"] == "memory"
        assert "node_count" in s
        assert "edge_count" in s

    def test_export_json_round_trip(
        self, store: MemoryGraphStore, sample_nodes: list[SymbolNode], sample_edges: list[SymbolEdge]
    ) -> None:
        store.upsert_symbols(sample_nodes)
        store.upsert_edges(sample_edges)
        exported = store.export_json()
        assert "nodes" in exported
        assert "edges" in exported
        assert len(exported["nodes"]) == len(sample_nodes)
        assert len(exported["edges"]) == len(sample_edges)
        # Nodes should be JSON-serialisable dicts
        assert isinstance(exported["nodes"][0], dict)
        assert isinstance(exported["edges"][0], dict)


# ── MemoryGraphStore: lifecycle ───────────────────────────────────────


class TestMemoryGraphStoreLifecycle:
    """Test close and context manager."""

    def test_close_clears_state(self, store: MemoryGraphStore) -> None:
        store.upsert_symbols([SymbolNode(fqn="a.py::X", name="X", kind=SymbolKind.CLASS, file_path="a.py")])
        store.close()
        assert store.status()["closed"] is True

    def test_operations_after_close_raise(self, store: MemoryGraphStore) -> None:
        store.close()
        with pytest.raises(RuntimeError, match="closed"):
            store.upsert_file("a.py")

    def test_context_manager(self) -> None:
        with MemoryGraphStore() as s:
            s.upsert_file("a.py")
            assert s.status()["file_count"] == 1
        # After exiting, store should be closed
        assert s.status()["closed"] is True


# ── Factory tests ─────────────────────────────────────────────────────


class TestGraphStoreFactory:
    """Test get_graph_store with various backend names."""

    def test_default_is_memory(self) -> None:
        store = get_graph_store()
        assert isinstance(store, MemoryGraphStore)
        store.close()

    def test_explicit_memory(self) -> None:
        store = get_graph_store("memory")
        assert isinstance(store, MemoryGraphStore)
        store.close()

    def test_sqlite_raises_not_implemented(self) -> None:
        with pytest.raises(NotImplementedError, match="SQLite.*not yet implemented.*#686"):
            get_graph_store("sqlite")

    def test_kuzu_raises_not_implemented(self) -> None:
        with pytest.raises(NotImplementedError, match="Kuzu.*reserved"):
            get_graph_store("kuzu")

    def test_unknown_backend_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Unknown graph store backend"):
            get_graph_store("nonexistent_backend_xyz")
