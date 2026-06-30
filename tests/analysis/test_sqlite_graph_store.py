"""
Unit tests for SqliteGraphStore (#686).

Covers CRUD against the GraphStore contract, WAL concurrency (separate
connections reading/writing the same file), a 10k-symbol bulk load, and
schema-version persistence round-trips across reopen.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from warden.analysis.domain.code_graph import EdgeRelation, SymbolEdge, SymbolKind, SymbolNode
from warden.analysis.services.sqlite_graph_store import SCHEMA_VERSION, SqliteGraphStore

# ── fixtures ──────────────────────────────────────────────────────────


@pytest.fixture()
def store() -> SqliteGraphStore:
    """Fresh in-memory SQLite store for each test."""
    s = SqliteGraphStore(":memory:")
    yield s
    s.close()


@pytest.fixture()
def sample_nodes() -> list[SymbolNode]:
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
    return [
        SymbolEdge(source="src/app/main.py::App", target="src/app/main.py::run", relation=EdgeRelation.DEFINES),
        SymbolEdge(source="src/app/main.py::run", target="src/app/utils.py::helper", relation=EdgeRelation.CALLS),
        SymbolEdge(
            source="src/app/main.py::run", target="src/app/utils.py::format_output", relation=EdgeRelation.CALLS
        ),
        SymbolEdge(source="tests/test_main.py::test_run", target="src/app/main.py::run", relation=EdgeRelation.CALLS),
    ]


def _populate(store: SqliteGraphStore, nodes: list[SymbolNode], edges: list[SymbolEdge]) -> None:
    store.upsert_symbols(nodes)
    store.upsert_edges(edges)


# ── schema / DDL ──────────────────────────────────────────────────────


class TestSchema:
    def test_required_tables_exist(self, store: SqliteGraphStore) -> None:
        rows = store._conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view')").fetchall()
        names = {r["name"] for r in rows}
        assert {"files", "symbols", "edges", "graph_meta", "symbol_intent"} <= names

    def test_fts_table_exists(self, store: SqliteGraphStore) -> None:
        row = store._conn.execute("SELECT name FROM sqlite_master WHERE name = 'graph_fts'").fetchone()
        assert row is not None

    def test_required_indexes_exist(self, store: SqliteGraphStore) -> None:
        rows = store._conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'").fetchall()
        names = {r["name"] for r in rows}
        assert {"idx_symbols_name_file", "idx_edges_target_rel", "idx_edges_source_rel"} <= names

    def test_edges_target_id_is_nullable(self, store: SqliteGraphStore) -> None:
        cols = {r["name"]: r for r in store._conn.execute("PRAGMA table_info(edges)").fetchall()}
        assert cols["target_id"]["notnull"] == 0
        assert "target_fqn_hint" in cols

    def test_symbol_intent_layer_b_cols_nullable(self, store: SqliteGraphStore) -> None:
        cols = {r["name"]: r for r in store._conn.execute("PRAGMA table_info(symbol_intent)").fetchall()}
        for col in ("intent", "summary", "confidence"):
            assert cols[col]["notnull"] == 0


# ── CRUD: write path ──────────────────────────────────────────────────


class TestWrite:
    def test_upsert_file(self, store: SqliteGraphStore) -> None:
        store.upsert_file("src/foo.py", content_hash="abc123")
        assert store.status()["file_count"] == 1

    def test_upsert_symbols(self, store: SqliteGraphStore, sample_nodes: list[SymbolNode]) -> None:
        store.upsert_symbols(sample_nodes)
        assert store.status()["node_count"] == len(sample_nodes)

    def test_upsert_edges(self, store: SqliteGraphStore, sample_nodes, sample_edges) -> None:
        _populate(store, sample_nodes, sample_edges)
        assert store.status()["edge_count"] == len(sample_edges)

    def test_upsert_symbols_overwrites(self, store: SqliteGraphStore) -> None:
        v1 = SymbolNode(fqn="a.py::X", name="X", kind=SymbolKind.CLASS, file_path="a.py", line=1)
        v2 = SymbolNode(fqn="a.py::X", name="X", kind=SymbolKind.CLASS, file_path="a.py", line=99)
        store.upsert_symbols([v1])
        store.upsert_symbols([v2])
        assert store.status()["node_count"] == 1
        assert store.search("X")[0].line == 99

    def test_delete_file_removes_symbols(self, store: SqliteGraphStore, sample_nodes, sample_edges) -> None:
        _populate(store, sample_nodes, sample_edges)
        before_nodes = store.status()["node_count"]
        store.delete_file("src/app/utils.py")
        after = store.status()
        # helper + format_output (and their FTS rows) are gone.
        assert after["node_count"] == before_nodes - 2
        assert store.search("helper") == []
        assert store.callees("src/app/main.py::run") == []

    def test_delete_file_leaves_dangling_edges_findable_by_hint(
        self, store: SqliteGraphStore, sample_nodes, sample_edges
    ) -> None:
        # By design target_id is ON DELETE SET NULL with target_fqn_hint kept,
        # so an edge into a deleted symbol survives and is still discoverable.
        _populate(store, sample_nodes, sample_edges)
        store.delete_file("src/app/utils.py")
        uses = store.who_uses("src/app/utils.py::helper")
        assert {e.source for e in uses} == {"src/app/main.py::run"}

    def test_unknown_source_edge_skipped(self, store: SqliteGraphStore) -> None:
        store.upsert_edges([SymbolEdge(source="ghost.py::nope", target="x", relation=EdgeRelation.CALLS)])
        assert store.status()["edge_count"] == 0


# ── CRUD: read path ───────────────────────────────────────────────────


class TestRead:
    def test_who_uses_excludes_tests_by_default(self, store, sample_nodes, sample_edges) -> None:
        _populate(store, sample_nodes, sample_edges)
        sources = {e.source for e in store.who_uses("src/app/main.py::run")}
        assert "tests/test_main.py::test_run" not in sources
        assert "src/app/main.py::App" in sources

    def test_who_uses_includes_tests_when_flagged(self, store, sample_nodes, sample_edges) -> None:
        _populate(store, sample_nodes, sample_edges)
        sources = {e.source for e in store.who_uses("src/app/main.py::run", include_tests=True)}
        assert "tests/test_main.py::test_run" in sources

    def test_who_uses_unresolved_target_hint(self, store: SqliteGraphStore) -> None:
        # Edge to an external/unparsed target keeps a hint and is still found.
        store.upsert_symbols(
            [SymbolNode(fqn="a.py::caller", name="caller", kind=SymbolKind.FUNCTION, file_path="a.py")]
        )
        store.upsert_edges(
            [SymbolEdge(source="a.py::caller", target="external.lib::thing", relation=EdgeRelation.CALLS)]
        )
        uses = store.who_uses("external.lib::thing")
        assert len(uses) == 1
        assert uses[0].target == "external.lib::thing"

    def test_callers(self, store, sample_nodes, sample_edges) -> None:
        _populate(store, sample_nodes, sample_edges)
        assert "src/app/main.py::run" in {n.fqn for n in store.callers("src/app/utils.py::helper")}

    def test_callees(self, store, sample_nodes, sample_edges) -> None:
        _populate(store, sample_nodes, sample_edges)
        fqns = {n.fqn for n in store.callees("src/app/main.py::run")}
        assert "src/app/utils.py::helper" in fqns
        assert "src/app/utils.py::format_output" in fqns

    def test_callees_carry_file_path(self, store, sample_nodes, sample_edges) -> None:
        _populate(store, sample_nodes, sample_edges)
        nodes = store.callees("src/app/main.py::run")
        assert all(n.file_path for n in nodes)

    def test_impact_returns_chains(self, store, sample_nodes, sample_edges) -> None:
        _populate(store, sample_nodes, sample_edges)
        chains = store.impact("src/app/main.py::run", max_depth=2)
        assert len(chains) >= 2

    def test_impact_respects_max_depth(self, store, sample_nodes, sample_edges) -> None:
        _populate(store, sample_nodes, sample_edges)
        d1 = store.impact("src/app/main.py::run", max_depth=1)
        d3 = store.impact("src/app/main.py::run", max_depth=3)
        assert len(d3) >= len(d1)

    def test_search_by_name(self, store, sample_nodes, sample_edges) -> None:
        _populate(store, sample_nodes, sample_edges)
        results = store.search("helper")
        assert [n.fqn for n in results] == ["src/app/utils.py::helper"]

    def test_search_by_path_token(self, store, sample_nodes, sample_edges) -> None:
        _populate(store, sample_nodes, sample_edges)
        results = store.search("utils.py")
        assert len({n.fqn for n in results}) >= 2

    def test_search_with_kind_filter(self, store, sample_nodes, sample_edges) -> None:
        _populate(store, sample_nodes, sample_edges)
        classes = store.search("", kind="class")
        assert classes and all(n.kind == SymbolKind.CLASS for n in classes)

    def test_search_respects_limit(self, store, sample_nodes, sample_edges) -> None:
        _populate(store, sample_nodes, sample_edges)
        assert len(store.search("", limit=2)) <= 2


# ── reverse impact ────────────────────────────────────────────────────


@pytest.fixture()
def reverse_impact_nodes() -> list[SymbolNode]:
    return [
        SymbolNode(fqn="a.py::Base", name="Base", kind=SymbolKind.CLASS, file_path="a.py"),
        SymbolNode(fqn="b.py::Child", name="Child", kind=SymbolKind.CLASS, file_path="b.py"),
        SymbolNode(fqn="c.py::Caller", name="Caller", kind=SymbolKind.FUNCTION, file_path="c.py"),
        SymbolNode(fqn="d.py::Leaf", name="Leaf", kind=SymbolKind.FUNCTION, file_path="d.py"),
        SymbolNode(
            fqn="tests/test_c.py::test_caller",
            name="test_caller",
            kind=SymbolKind.FUNCTION,
            file_path="tests/test_c.py",
            is_test=True,
        ),
    ]


@pytest.fixture()
def reverse_impact_edges() -> list[SymbolEdge]:
    return [
        SymbolEdge(source="b.py::Child", target="a.py::Base", relation=EdgeRelation.INHERITS),
        SymbolEdge(source="c.py::Caller", target="b.py::Child", relation=EdgeRelation.CALLS),
        SymbolEdge(source="d.py::Leaf", target="c.py::Caller", relation=EdgeRelation.CALLS),
        SymbolEdge(source="tests/test_c.py::test_caller", target="c.py::Caller", relation=EdgeRelation.CALLS),
    ]


class TestReverseImpact:
    def test_reverse_impact_returns_callers_and_inheritors(
        self, store: SqliteGraphStore, reverse_impact_nodes: list[SymbolNode], reverse_impact_edges: list[SymbolEdge]
    ) -> None:
        store.upsert_symbols(reverse_impact_nodes)
        store.upsert_edges(reverse_impact_edges)
        chains = store.reverse_impact("a.py::Base", max_depth=3)
        assert len(chains) >= 2
        targets = {chain[-1].source for chain in chains}
        assert "b.py::Child" in targets
        assert "c.py::Caller" in targets

    def test_reverse_impact_excludes_tests_by_default(
        self, store: SqliteGraphStore, reverse_impact_nodes: list[SymbolNode], reverse_impact_edges: list[SymbolEdge]
    ) -> None:
        store.upsert_symbols(reverse_impact_nodes)
        store.upsert_edges(reverse_impact_edges)
        chains = store.reverse_impact("c.py::Caller", max_depth=2)
        sources = {chain[-1].source for chain in chains}
        assert "d.py::Leaf" in sources
        assert "tests/test_c.py::test_caller" not in sources

    def test_reverse_impact_includes_tests_when_flagged(
        self, store: SqliteGraphStore, reverse_impact_nodes: list[SymbolNode], reverse_impact_edges: list[SymbolEdge]
    ) -> None:
        store.upsert_symbols(reverse_impact_nodes)
        store.upsert_edges(reverse_impact_edges)
        chains = store.reverse_impact("c.py::Caller", max_depth=2, include_tests=True)
        sources = {chain[-1].source for chain in chains}
        assert "tests/test_c.py::test_caller" in sources

    def test_reverse_impact_respects_max_depth(
        self, store: SqliteGraphStore, reverse_impact_nodes: list[SymbolNode], reverse_impact_edges: list[SymbolEdge]
    ) -> None:
        store.upsert_symbols(reverse_impact_nodes)
        store.upsert_edges(reverse_impact_edges)
        d1 = store.reverse_impact("a.py::Base", max_depth=1)
        d3 = store.reverse_impact("a.py::Base", max_depth=3)
        assert len(d3) >= len(d1)
        assert all(len(chain) <= 1 for chain in d1)

    def test_reverse_impact_handles_unresolved_target_hint(
        self, store: SqliteGraphStore, reverse_impact_nodes: list[SymbolNode]
    ) -> None:
        store.upsert_symbols(reverse_impact_nodes)
        # Edge whose target is an unresolved short/hint name, not a known symbol.
        store.upsert_edges([SymbolEdge(source="d.py::Leaf", target="external.lib::thing", relation=EdgeRelation.CALLS)])
        chains = store.reverse_impact("external.lib::thing", max_depth=1)
        assert len(chains) == 1
        assert chains[0][0].source == "d.py::Leaf"


# ── introspection ─────────────────────────────────────────────────────


class TestIntrospection:
    def test_status_required_keys(self, store: SqliteGraphStore) -> None:
        s = store.status()
        assert s["backend"] == "sqlite"
        assert {"node_count", "edge_count", "schema_version"} <= set(s)

    def test_export_json_round_trip(self, store, sample_nodes, sample_edges) -> None:
        _populate(store, sample_nodes, sample_edges)
        exported = store.export_json()
        assert len(exported["nodes"]) == len(sample_nodes)
        assert len(exported["edges"]) == len(sample_edges)
        node = exported["nodes"][0]
        assert isinstance(node, dict) and node["file_path"]  # model_dump(mode="json") → snake_case


# ── lifecycle ─────────────────────────────────────────────────────────


class TestLifecycle:
    def test_close_then_status(self, store: SqliteGraphStore) -> None:
        store.close()
        assert store.status()["closed"] is True

    def test_operations_after_close_raise(self, store: SqliteGraphStore) -> None:
        store.close()
        with pytest.raises(RuntimeError, match="closed"):
            store.upsert_file("a.py")

    def test_context_manager_closes(self) -> None:
        with SqliteGraphStore(":memory:") as s:
            s.upsert_file("a.py")
            assert s.status()["file_count"] == 1
        assert s.status()["closed"] is True


# ── schema-version round-trip ─────────────────────────────────────────


class TestSchemaVersionRoundTrip:
    def test_version_persisted_on_init(self, store: SqliteGraphStore) -> None:
        assert store.schema_version() == SCHEMA_VERSION

    def test_version_survives_reopen(self, tmp_path: Path) -> None:
        db = tmp_path / "graph.db"
        s1 = SqliteGraphStore(db)
        s1.upsert_file("a.py", content_hash="h")
        assert s1.schema_version() == SCHEMA_VERSION
        s1.close()

        s2 = SqliteGraphStore(db)
        assert s2.schema_version() == SCHEMA_VERSION
        assert s2.status()["file_count"] == 1  # data persisted, not duplicated
        s2.close()

    def test_reopen_does_not_duplicate_meta(self, tmp_path: Path) -> None:
        db = tmp_path / "graph.db"
        SqliteGraphStore(db).close()
        s2 = SqliteGraphStore(db)
        count = s2._conn.execute("SELECT COUNT(*) AS c FROM graph_meta WHERE key = 'schema_version'").fetchone()["c"]
        s2.close()
        assert count == 1


# ── WAL / concurrency ─────────────────────────────────────────────────


class TestWalConcurrency:
    def test_journal_mode_is_wal_for_file_db(self, tmp_path: Path) -> None:
        db = tmp_path / "graph.db"
        s = SqliteGraphStore(db)
        mode = s._conn.execute("PRAGMA journal_mode").fetchone()[0]
        s.close()
        assert mode.lower() == "wal"

    def test_second_connection_reads_committed_writes(self, tmp_path: Path) -> None:
        db = tmp_path / "graph.db"
        writer = SqliteGraphStore(db)
        writer.upsert_symbols([SymbolNode(fqn="a.py::A", name="A", kind=SymbolKind.CLASS, file_path="a.py")])

        reader = SqliteGraphStore(db)  # separate connection
        assert reader.status()["node_count"] == 1
        assert {n.fqn for n in reader.search("A")} == {"a.py::A"}
        reader.close()
        writer.close()

    def test_concurrent_writer_and_reader(self, tmp_path: Path) -> None:
        db = tmp_path / "graph.db"
        seed = SqliteGraphStore(db)
        seed.close()

        errors: list[Exception] = []

        def writer() -> None:
            try:
                w = SqliteGraphStore(db)
                for i in range(200):
                    w.upsert_symbols(
                        [SymbolNode(fqn=f"f{i}.py::S{i}", name=f"S{i}", kind=SymbolKind.FUNCTION, file_path=f"f{i}.py")]
                    )
                w.close()
            except Exception as exc:  # pragma: no cover - failure path
                errors.append(exc)

        def reader() -> None:
            try:
                r = SqliteGraphStore(db)
                for _ in range(200):
                    r.status()
                    r.search("S")
                r.close()
            except Exception as exc:  # pragma: no cover - failure path
                errors.append(exc)

        threads = [threading.Thread(target=writer), threading.Thread(target=reader)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"WAL concurrency errors: {errors}"
        final = SqliteGraphStore(db)
        assert final.status()["node_count"] == 200
        final.close()


# ── bulk load ─────────────────────────────────────────────────────────


class TestBulkLoad:
    def test_10k_symbol_load(self, tmp_path: Path) -> None:
        db = tmp_path / "big.db"
        store = SqliteGraphStore(db)
        nodes = [
            SymbolNode(
                fqn=f"src/mod{i // 100}.py::Sym{i}",
                name=f"Sym{i}",
                kind=SymbolKind.FUNCTION,
                file_path=f"src/mod{i // 100}.py",
                line=i,
                module=f"mod{i // 100}",
            )
            for i in range(10_000)
        ]
        store.upsert_symbols(nodes)
        assert store.status()["node_count"] == 10_000

        # FTS search still resolves a specific symbol out of 10k.
        hits = store.search("Sym4242")
        assert any(n.fqn == "src/mod42.py::Sym4242" for n in hits)
        store.close()

    def test_10k_with_edges_query(self, tmp_path: Path) -> None:
        db = tmp_path / "big_edges.db"
        store = SqliteGraphStore(db)
        nodes = [
            SymbolNode(fqn=f"m.py::S{i}", name=f"S{i}", kind=SymbolKind.FUNCTION, file_path="m.py")
            for i in range(10_000)
        ]
        store.upsert_symbols(nodes)
        # Chain S0 -> S1 -> ... so callees/who_uses exercise indexed edge lookups.
        edges = [
            SymbolEdge(source=f"m.py::S{i}", target=f"m.py::S{i + 1}", relation=EdgeRelation.CALLS)
            for i in range(9_999)
        ]
        store.upsert_edges(edges)
        assert store.status()["edge_count"] == 9_999
        assert {n.fqn for n in store.callees("m.py::S0")} == {"m.py::S1"}
        assert {e.source for e in store.who_uses("m.py::S9999")} == {"m.py::S9998"}
        store.close()
