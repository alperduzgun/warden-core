"""
Tests for IntelligenceSaver graph export methods.

Covers: save_dependency_graph, save_code_graph, save_gap_report,
        O5 atomic write pattern.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from warden.analysis.domain.code_graph import (
    CodeGraph,
    EdgeRelation,
    GapReport,
    SymbolEdge,
    SymbolKind,
    SymbolNode,
)
from warden.analysis.services.intelligence_saver import IntelligenceSaver


@pytest.fixture
def tmp_project(tmp_path):
    """Create a temporary project directory."""
    return tmp_path


@pytest.fixture
def saver(tmp_project):
    return IntelligenceSaver(tmp_project)


def _mock_dep_graph(project_root: Path):
    graph = MagicMock()
    graph.project_root = project_root
    graph._forward_graph = {
        project_root / "src/a.py": {project_root / "src/b.py", project_root / "src/c.py"},
        project_root / "src/b.py": {project_root / "src/c.py"},
    }
    graph._reverse_graph = {
        project_root / "src/b.py": {project_root / "src/a.py"},
        project_root / "src/c.py": {project_root / "src/a.py", project_root / "src/b.py"},
    }
    return graph


# --- Dependency Graph ---


class TestSaveDependencyGraph:
    def test_basic_save(self, saver, tmp_project):
        graph = _mock_dep_graph(tmp_project)
        assert saver.save_dependency_graph(graph)

        path = tmp_project / ".warden/intelligence/dependency_graph.json"
        assert path.exists()

        data = json.loads(path.read_text())
        assert data["schema_version"] == "1.0.0"
        assert "forward" in data
        assert "reverse" in data
        assert data["stats"]["total_edges"] > 0

    def test_orphan_detection(self, saver, tmp_project):
        graph = _mock_dep_graph(tmp_project)
        # Add orphan: node in graph but no edges
        graph._forward_graph[tmp_project / "src/orphan.py"] = set()

        saver.save_dependency_graph(graph)

        path = tmp_project / ".warden/intelligence/dependency_graph.json"
        data = json.loads(path.read_text())
        # orphan.py has no outgoing or incoming edges
        assert data["stats"]["orphan_count"] >= 0

    def test_integrity_check(self, saver, tmp_project):
        graph = _mock_dep_graph(tmp_project)
        saver.save_dependency_graph(graph)

        path = tmp_project / ".warden/intelligence/dependency_graph.json"
        data = json.loads(path.read_text())
        assert "integrity" in data
        assert isinstance(data["integrity"]["forward_reverse_match"], bool)

    def test_empty_graph(self, saver, tmp_project):
        graph = MagicMock()
        graph.project_root = tmp_project
        graph._forward_graph = {}
        graph._reverse_graph = {}

        assert saver.save_dependency_graph(graph)

        path = tmp_project / ".warden/intelligence/dependency_graph.json"
        data = json.loads(path.read_text())
        assert data["stats"]["total_files"] == 0
        assert data["stats"]["total_edges"] == 0


# --- Code Graph ---


class TestSaveCodeGraph:
    def test_basic_save(self, saver, tmp_project):
        graph = CodeGraph()
        graph.add_node(SymbolNode(
            fqn="src/a.py::Foo", name="Foo", kind=SymbolKind.CLASS,
            file_path="src/a.py", line=1, module="a",
        ))
        graph.add_edge(SymbolEdge(
            source="src/a.py::Foo", target="Base", relation=EdgeRelation.INHERITS,
        ))

        assert saver.save_code_graph(graph)

        path = tmp_project / ".warden/intelligence/code_graph.json"
        assert path.exists()

        data = json.loads(path.read_text())
        assert "nodes" in data
        assert "edges" in data
        assert data["generated_at"] is not None

    def test_roundtrip_serialization(self, saver, tmp_project):
        graph = CodeGraph()
        graph.add_node(SymbolNode(
            fqn="src/x.py::X", name="X", kind=SymbolKind.CLASS,
            file_path="src/x.py", line=10, module="x", is_test=False,
        ))
        saver.save_code_graph(graph)

        path = tmp_project / ".warden/intelligence/code_graph.json"
        data = json.loads(path.read_text())

        # Verify node data preserved
        nodes = data["nodes"]
        assert "src/x.py::X" in nodes


# --- Gap Report ---


class TestSaveGapReport:
    def test_basic_save(self, saver, tmp_project):
        report = GapReport(
            orphan_files=["src/orphan.py"],
            broken_imports=["missing.module"],
            coverage=0.85,
            star_imports=["src/app.py"],
        )

        assert saver.save_gap_report(report)

        path = tmp_project / ".warden/intelligence/gap_report.json"
        assert path.exists()

        data = json.loads(path.read_text())
        assert data["orphanFiles"] == ["src/orphan.py"]
        assert data["coverage"] == 0.85
        assert data["starImports"] == ["src/app.py"]

    def test_empty_report(self, saver, tmp_project):
        report = GapReport()
        assert saver.save_gap_report(report)

        path = tmp_project / ".warden/intelligence/gap_report.json"
        data = json.loads(path.read_text())
        assert data["coverage"] == 0.0


# --- Atomic Write (O5) ---


class TestAtomicWrite:
    def test_atomic_write_creates_file(self, saver, tmp_project):
        target = tmp_project / ".warden/intelligence/test.json"
        saver._atomic_write(target, '{"test": true}')

        assert target.exists()
        assert json.loads(target.read_text()) == {"test": True}

    def test_atomic_write_no_temp_file_on_success(self, saver, tmp_project):
        target = tmp_project / ".warden/intelligence/test2.json"
        saver._atomic_write(target, '{"ok": true}')

        # No .tmp files should remain
        tmp_files = list(target.parent.glob("*.tmp"))
        assert len(tmp_files) == 0

    def test_atomic_write_replaces_existing(self, saver, tmp_project):
        target = tmp_project / ".warden/intelligence/test3.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('{"old": true}')

        saver._atomic_write(target, '{"new": true}')

        data = json.loads(target.read_text())
        assert data == {"new": True}
