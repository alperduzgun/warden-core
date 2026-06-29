"""
Tests for the 4 new GraphStore ABC methods: get_node, who_inherits,
who_implements, edges_from — on both SQLite and Memory backends.
"""

from __future__ import annotations

import json

import pytest

from warden.analysis.domain.code_graph import EdgeRelation, SymbolEdge, SymbolKind, SymbolNode
from warden.analysis.services.memory_graph_store import MemoryGraphStore
from warden.analysis.services.sqlite_graph_store import SqliteGraphStore

# ── shared fixture data ────────────────────────────────────────────────

PARENT_NODE = SymbolNode(
    fqn="app.base::Base",
    name="Base",
    kind=SymbolKind.CLASS,
    file_path="src/app/base.py",
    line=1,
    module="app.base",
    bases=[],
    metadata={},
)

CHILD_NODE = SymbolNode(
    fqn="app.child::Child",
    name="Child",
    kind=SymbolKind.CLASS,
    file_path="src/app/child.py",
    line=10,
    module="app.child",
    bases=["Base"],
    metadata={},
)

IMPL_NODE = SymbolNode(
    fqn="app.mixins::Runnable",
    name="Runnable",
    kind=SymbolKind.INTERFACE,
    file_path="src/app/mixins.py",
    line=1,
    module="app.mixins",
    bases=[],
    metadata={},
)

IMPL_CHILD = SymbolNode(
    fqn="app.impl::Runner",
    name="Runner",
    kind=SymbolKind.CLASS,
    file_path="src/app/impl.py",
    line=5,
    module="app.impl",
    bases=["Runnable"],
    metadata={},
)

CALLER_NODE = SymbolNode(
    fqn="app.ctrl::Controller",
    name="Controller",
    kind=SymbolKind.CLASS,
    file_path="src/app/ctrl.py",
    line=1,
    module="app.ctrl",
    bases=[],
    metadata={},
)

CALLEE_NODE = SymbolNode(
    fqn="app.util::helper",
    name="helper",
    kind=SymbolKind.FUNCTION,
    file_path="src/app/util.py",
    line=1,
    module="app.util",
    bases=[],
    metadata={},
)

ALL_SYMBOLS = [PARENT_NODE, CHILD_NODE, IMPL_NODE, IMPL_CHILD, CALLER_NODE, CALLEE_NODE]

ALL_EDGES = [
    SymbolEdge(source=CHILD_NODE.fqn, target=PARENT_NODE.fqn, relation=EdgeRelation.INHERITS),
    SymbolEdge(source=IMPL_CHILD.fqn, target=IMPL_NODE.fqn, relation=EdgeRelation.IMPLEMENTS),
    SymbolEdge(source=CALLER_NODE.fqn, target=CALLEE_NODE.fqn, relation=EdgeRelation.CALLS),
    SymbolEdge(source=CHILD_NODE.fqn, target=CALLEE_NODE.fqn, relation=EdgeRelation.CALLS),
]


def _populate_sqlite() -> SqliteGraphStore:
    store = SqliteGraphStore(":memory:")
    for sym in ALL_SYMBOLS:
        store.upsert_file(sym.file_path)
    store.upsert_symbols(ALL_SYMBOLS)
    store.upsert_edges(ALL_EDGES)
    return store


def _populate_memory() -> MemoryGraphStore:
    store = MemoryGraphStore()
    for sym in ALL_SYMBOLS:
        store.upsert_file(sym.file_path)
    store.upsert_symbols(ALL_SYMBOLS)
    store.upsert_edges(ALL_EDGES)
    return store


# ── backend-parametrized fixture ───────────────────────────────────────

BACKEND_IDS = ["sqlite", "memory"]


@pytest.fixture(params=BACKEND_IDS)
def store(request):
    if request.param == "sqlite":
        s = _populate_sqlite()
    else:
        s = _populate_memory()
    yield s
    s.close()


# ── get_node ───────────────────────────────────────────────────────────


class TestGetNode:
    def test_finds_existing_node(self, store):
        node = store.get_node(PARENT_NODE.fqn)
        assert node is not None
        assert node.fqn == PARENT_NODE.fqn
        assert node.name == "Base"
        assert node.kind == SymbolKind.CLASS

    def test_returns_none_for_unknown(self, store):
        assert store.get_node("does.not::Exist") is None

    def test_round_trip_properties(self, store):
        node = store.get_node(CALLEE_NODE.fqn)
        assert node is not None
        assert node.file_path == "src/app/util.py"
        assert node.module == "app.util"


# ── who_inherits ───────────────────────────────────────────────────────


class TestWhoInherits:
    def test_finds_child_class(self, store):
        children = store.who_inherits(PARENT_NODE.fqn)
        assert len(children) == 1
        assert children[0].fqn == CHILD_NODE.fqn

    def test_empty_for_leaf_class(self, store):
        assert store.who_inherits(CHILD_NODE.fqn) == []

    def test_empty_for_unknown(self, store):
        assert store.who_inherits("does.not::Exist") == []


# ── who_implements ─────────────────────────────────────────────────────


class TestWhoImplements:
    def test_finds_implementor(self, store):
        implementors = store.who_implements(IMPL_NODE.fqn)
        assert len(implementors) == 1
        assert implementors[0].fqn == IMPL_CHILD.fqn

    def test_empty_for_non_interface(self, store):
        assert store.who_implements(CALLER_NODE.fqn) == []

    def test_empty_for_unknown(self, store):
        assert store.who_implements("does.not::Exist") == []


# ── edges_from ─────────────────────────────────────────────────────────


class TestEdgesFrom:
    def test_all_outgoing_edges(self, store):
        edges = store.edges_from(CHILD_NODE.fqn)
        assert len(edges) == 2  # INHERITS + CALLS
        relations = {e.relation for e in edges}
        assert EdgeRelation.INHERITS in relations
        assert EdgeRelation.CALLS in relations

    def test_filtered_by_relation(self, store):
        edges = store.edges_from(CHILD_NODE.fqn, relation=EdgeRelation.CALLS)
        assert len(edges) == 1
        assert edges[0].relation == EdgeRelation.CALLS
        assert edges[0].target == CALLEE_NODE.fqn

    def test_empty_for_unknown_source(self, store):
        assert store.edges_from("does.not::Exist") == []

    def test_no_edges_no_relation_filter(self, store):
        edges = store.edges_from(IMPL_NODE.fqn)
        assert edges == []
