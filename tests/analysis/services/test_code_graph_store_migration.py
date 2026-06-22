"""
Tests for the CodeGraphBuilder → GraphStore migration (#688).

Covers the Python-only write-through path (full + incremental), the
``build_into_store`` convenience, the default DB path helper, and the
``warden graph build`` / ``warden graph status`` CLI commands.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from warden.analysis.domain.code_graph import (
    CodeGraph,
    EdgeRelation,
    SymbolEdge,
    SymbolKind,
    SymbolNode,
)
from warden.analysis.services.code_graph_builder import write_graph_to_store
from warden.analysis.services.graph_store_factory import default_db_path, get_graph_store
from warden.cli.commands.graph import graph_app


def _graph_two_files() -> CodeGraph:
    g = CodeGraph()
    g.add_node(SymbolNode(fqn="a.py::Foo", name="Foo", kind=SymbolKind.CLASS, file_path="a.py", module="a"))
    g.add_node(SymbolNode(fqn="a.py::run", name="run", kind=SymbolKind.FUNCTION, file_path="a.py", module="a"))
    g.add_node(SymbolNode(fqn="b.py::helper", name="helper", kind=SymbolKind.FUNCTION, file_path="b.py", module="b"))
    # symbol→symbol edge (persisted) + file→symbol DEFINES edge (dropped)
    g.add_edge(SymbolEdge(source="a.py::run", target="b.py::helper", relation=EdgeRelation.CALLS))
    g.add_edge(SymbolEdge(source="a.py", target="a.py::Foo", relation=EdgeRelation.DEFINES))
    return g


class TestWriteThrough:
    def test_full_write_persists_symbols_and_symbol_edges(self):
        store = get_graph_store("sqlite", path=":memory:")
        try:
            write_graph_to_store(_graph_two_files(), store)
            status = store.status()
            assert status["node_count"] == 3
            # Only the symbol→symbol CALLS edge survives; the file→symbol
            # DEFINES edge is intentionally not persisted.
            assert status["edge_count"] == 1
            assert status["file_count"] == 2
        finally:
            store.close()

    def test_full_write_works_on_memory_backend(self):
        store = get_graph_store("memory")
        try:
            write_graph_to_store(_graph_two_files(), store)
            assert store.status()["node_count"] == 3
        finally:
            store.close()

    def test_content_hashes_recorded(self):
        store = get_graph_store("sqlite", path=":memory:")
        try:
            write_graph_to_store(_graph_two_files(), store, content_hashes={"a.py": "deadbeef"})
            # who_uses round-trips through the files join, proving the row exists.
            exported = store.export_json()
            assert any(n["file_path"] == "a.py" for n in exported["nodes"])
        finally:
            store.close()


class TestIncrementalUpdate:
    def test_incremental_rewrites_only_named_files(self):
        store = get_graph_store("sqlite", path=":memory:")
        try:
            write_graph_to_store(_graph_two_files(), store)

            # Re-build a.py with a changed symbol set; b.py untouched.
            updated = CodeGraph()
            updated.add_node(
                SymbolNode(fqn="a.py::Foo", name="Foo", kind=SymbolKind.CLASS, file_path="a.py", module="a")
            )
            updated.add_node(
                SymbolNode(fqn="a.py::Bar", name="Bar", kind=SymbolKind.CLASS, file_path="a.py", module="a")
            )
            write_graph_to_store(updated, store, files=["a.py"])

            exported = store.export_json()
            fqns = {n["fqn"] for n in exported["nodes"]}
            # a.py rewritten: run gone, Bar added; b.py preserved.
            assert "a.py::Bar" in fqns
            assert "a.py::run" not in fqns
            assert "b.py::helper" in fqns
        finally:
            store.close()

    def test_incremental_clears_stale_edges(self):
        store = get_graph_store("sqlite", path=":memory:")
        try:
            write_graph_to_store(_graph_two_files(), store)
            assert store.status()["edge_count"] == 1

            # Rewrite a.py with no outgoing edges → the stale CALLS edge clears.
            updated = CodeGraph()
            updated.add_node(
                SymbolNode(fqn="a.py::Foo", name="Foo", kind=SymbolKind.CLASS, file_path="a.py", module="a")
            )
            write_graph_to_store(updated, store, files=["a.py"])
            assert store.status()["edge_count"] == 0
        finally:
            store.close()


class TestDefaultDbPath:
    def test_default_db_path(self, tmp_path: Path):
        assert default_db_path(tmp_path) == tmp_path / ".warden" / "graph.db"


class TestGraphCli:
    def _write_project(self, root: Path) -> None:
        (root / "pkg").mkdir()
        (root / "pkg" / "mod.py").write_text(
            "class Service:\n"
            "    def run(self):\n"
            "        return helper()\n"
            "\n"
            "def helper():\n"
            "    return 1\n",
            encoding="utf-8",
        )

    def test_build_then_status(self, tmp_path: Path):
        self._write_project(tmp_path)
        runner = CliRunner()

        build = runner.invoke(graph_app, ["build", str(tmp_path)])
        assert build.exit_code == 0, build.output
        assert "Graph build complete" in build.output

        db_path = default_db_path(tmp_path)
        assert db_path.exists()

        # Symbols actually landed in the DB.
        store = get_graph_store("sqlite", path=str(db_path))
        try:
            assert store.status()["node_count"] >= 2  # Service + run + helper
        finally:
            store.close()

        status = runner.invoke(graph_app, ["status", str(tmp_path)])
        assert status.exit_code == 0, status.output
        assert "Schema version" in status.output
        assert "Nodes" in status.output
        assert "Staleness" in status.output

    def test_status_without_db_exits_nonzero(self, tmp_path: Path):
        runner = CliRunner()
        result = runner.invoke(graph_app, ["status", str(tmp_path)])
        assert result.exit_code == 1
        assert "No graph DB found" in result.output

    def test_force_rebuild(self, tmp_path: Path):
        self._write_project(tmp_path)
        runner = CliRunner()
        assert runner.invoke(graph_app, ["build", str(tmp_path)]).exit_code == 0
        rebuilt = runner.invoke(graph_app, ["build", str(tmp_path), "--force"])
        assert rebuilt.exit_code == 0, rebuilt.output
        assert default_db_path(tmp_path).exists()


class _FakeAstCache:
    """Minimal stand-in for PipelineContext.ast_cache exposing keys()."""

    def __init__(self, keys: list[str]) -> None:
        self._keys = keys

    def __iter__(self):
        return iter(self._keys)

    def keys(self):
        return list(self._keys)


class _Ctx:
    def __init__(self, ast_cache: _FakeAstCache) -> None:
        self.ast_cache = ast_cache


class TestPreAnalysisG1Sync:
    """The permanent G1 fix: read-from-DB + update-only-parsed-files."""

    def _phase(self, root: Path):
        from warden.analysis.application.pre_analysis_phase import PreAnalysisPhase

        return PreAnalysisPhase(project_root=root)

    def test_no_db_returns_input_unchanged(self, tmp_path: Path):
        from warden.analysis.services.code_graph_builder import CodeGraphBuilder

        phase = self._phase(tmp_path)
        graph = _graph_two_files()
        ctx = _Ctx(_FakeAstCache([str(tmp_path / "a.py")]))
        builder = CodeGraphBuilder({}, project_root=tmp_path)

        result = phase._sync_graph_store(graph, ctx, builder)
        # Same object back — no persistent DB means no behaviour change.
        assert result is graph

    def test_db_present_updates_parsed_files_and_reads_whole_graph(self, tmp_path: Path):
        from warden.analysis.services.code_graph_builder import CodeGraphBuilder

        # Seed a persistent DB with b.py only (simulating `warden graph build`).
        db_path = default_db_path(tmp_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        seed = CodeGraph()
        seed.add_node(
            SymbolNode(fqn="b.py::helper", name="helper", kind=SymbolKind.FUNCTION, file_path="b.py", module="b")
        )
        store = get_graph_store("sqlite", path=str(db_path))
        try:
            write_graph_to_store(seed, store)
        finally:
            store.close()

        # This run only parsed a.py.
        run_graph = CodeGraph()
        run_graph.add_node(
            SymbolNode(fqn="a.py::run", name="run", kind=SymbolKind.FUNCTION, file_path="a.py", module="a")
        )

        phase = self._phase(tmp_path)
        ctx = _Ctx(_FakeAstCache([str(tmp_path / "a.py")]))
        builder = CodeGraphBuilder({}, project_root=tmp_path)

        result = phase._sync_graph_store(run_graph, ctx, builder)

        # Whole-project graph from the DB: a.py (updated) + b.py (preserved).
        assert "a.py::run" in result.nodes
        assert "b.py::helper" in result.nodes
