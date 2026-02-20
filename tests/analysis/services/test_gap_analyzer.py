"""
Tests for GapAnalyzer.

Covers: Gemini test exclusion from unreachable, orphan detection,
        broken imports, circular deps, coverage, test-only consumers (Y7).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from warden.analysis.domain.code_graph import (
    CodeGraph,
    EdgeRelation,
    SymbolEdge,
    SymbolKind,
    SymbolNode,
)
from warden.analysis.services.gap_analyzer import GapAnalyzer


# --- Helpers ---


def _node(fqn: str, name: str = "", kind: SymbolKind = SymbolKind.CLASS,
          file_path: str = "src/foo.py", is_test: bool = False) -> SymbolNode:
    return SymbolNode(
        fqn=fqn, name=name or fqn.split("::")[-1], kind=kind,
        file_path=file_path, line=1, module="", is_test=is_test,
    )


def _edge(source: str, target: str, relation: EdgeRelation = EdgeRelation.IMPORTS,
          runtime: bool = True) -> SymbolEdge:
    return SymbolEdge(source=source, target=target, relation=relation, runtime=runtime)


def _mock_dep_graph(forward: dict[str, list[str]], reverse: dict[str, list[str]] | None = None):
    """Create a mock dependency graph."""
    graph = MagicMock()
    graph._forward_graph = {Path(k): {Path(v) for v in vs} for k, vs in forward.items()}
    if reverse is None:
        # Build reverse from forward
        rev: dict[str, set[str]] = {}
        for src, deps in forward.items():
            for d in deps:
                rev.setdefault(d, set()).add(src)
        graph._reverse_graph = {Path(k): {Path(v) for v in vs} for k, vs in rev.items()}
    else:
        graph._reverse_graph = {Path(k): {Path(v) for v in vs} for k, vs in reverse.items()}
    return graph


# --- Orphan File Detection ---


class TestOrphanFiles:
    def test_orphan_files_detected(self):
        dep_graph = _mock_dep_graph(
            forward={"src/a.py": ["src/b.py"]},
            reverse={"src/b.py": ["src/a.py"]},
        )
        # src/c.py is not in any edge
        dep_graph._forward_graph[Path("src/c.py")] = set()
        dep_graph._reverse_graph[Path("src/c.py")] = set()

        analyzer = GapAnalyzer()
        code_graph = CodeGraph()
        report = analyzer.analyze(code_graph, dep_graph=dep_graph)

        assert "src/c.py" in report.orphan_files


# --- Orphan Symbol Detection ---


class TestOrphanSymbols:
    def test_symbol_without_edges_is_orphan(self):
        graph = CodeGraph()
        graph.add_node(_node("src/x.py::Orphan"))
        graph.add_node(_node("src/y.py::Connected"))
        graph.add_edge(_edge("src/y.py::Connected", "something"))

        analyzer = GapAnalyzer()
        report = analyzer.analyze(graph)

        assert "src/x.py::Orphan" in report.orphan_symbols

    def test_connected_symbol_not_orphan(self):
        graph = CodeGraph()
        graph.add_node(_node("src/y.py::Used"))
        graph.add_edge(_edge("src/y.py::Used", "target"))

        analyzer = GapAnalyzer()
        report = analyzer.analyze(graph)

        assert "src/y.py::Used" not in report.orphan_symbols


# --- Broken Import Detection ---


class TestBrokenImports:
    def test_broken_import_detected(self):
        graph = CodeGraph()
        graph.add_node(_node("src/a.py::A"))
        graph.add_edge(_edge("src/a.py::A", "warden.missing.module", EdgeRelation.IMPORTS))

        analyzer = GapAnalyzer()
        report = analyzer.analyze(graph)

        assert "warden.missing.module" in report.broken_imports

    def test_valid_import_not_broken(self):
        graph = CodeGraph()
        graph.add_node(SymbolNode(fqn="src/a.py::A", name="A", kind=SymbolKind.CLASS,
                                  file_path="src/a.py", module="warden.a"))
        graph.add_edge(_edge("src/a.py::A", "warden.a", EdgeRelation.IMPORTS))

        analyzer = GapAnalyzer()
        report = analyzer.analyze(graph)

        assert "warden.a" not in report.broken_imports


# --- Circular Dependency Detection ---


class TestCircularDeps:
    def test_circular_deps_detected(self):
        graph = CodeGraph()
        graph.add_edge(_edge("A", "B", EdgeRelation.IMPORTS))
        graph.add_edge(_edge("B", "A", EdgeRelation.IMPORTS))

        analyzer = GapAnalyzer()
        report = analyzer.analyze(graph)

        assert len(report.circular_deps) >= 1


# --- Unreachable from Entry (Gemini Fix) ---


class TestUnreachable:
    def test_unreachable_files_detected(self):
        dep_graph = _mock_dep_graph(
            forward={
                "src/main.py": ["src/core.py"],
                "src/core.py": ["src/utils.py"],
                "src/isolated.py": [],
            }
        )

        analyzer = GapAnalyzer()
        graph = CodeGraph()
        report = analyzer.analyze(
            graph,
            dep_graph=dep_graph,
            entry_points=["src/main.py"],
        )

        assert "src/isolated.py" in report.unreachable_from_entry

    def test_gemini_fix_test_files_excluded_from_unreachable(self):
        """Gemini fix: test files should NOT appear as unreachable."""
        dep_graph = _mock_dep_graph(
            forward={
                "src/main.py": ["src/core.py"],
                "tests/test_core.py": ["src/core.py"],  # Test file imports core
                "src/standalone.py": [],  # Non-test, unreachable
            }
        )

        analyzer = GapAnalyzer()
        graph = CodeGraph()
        report = analyzer.analyze(
            graph,
            dep_graph=dep_graph,
            entry_points=["src/main.py"],
        )

        # Test files should NOT be in unreachable
        assert not any("test" in f for f in report.unreachable_from_entry)
        # But standalone.py should be
        assert "src/standalone.py" in report.unreachable_from_entry

    def test_no_entry_points_skips_unreachable_analysis(self):
        analyzer = GapAnalyzer()
        graph = CodeGraph()
        report = analyzer.analyze(graph, dep_graph=_mock_dep_graph({"a.py": []}))

        assert report.unreachable_from_entry == []


# --- Missing Mixin Implementation ---


class TestMissingMixinImpl:
    def test_mixin_without_implementors(self):
        graph = CodeGraph()
        graph.add_node(_node("src/m.py::TaintAware", kind=SymbolKind.MIXIN))
        # No IMPLEMENTS edges pointing to TaintAware

        analyzer = GapAnalyzer()
        report = analyzer.analyze(graph)

        assert "src/m.py::TaintAware" in report.missing_mixin_impl

    def test_mixin_with_implementor_not_missing(self):
        graph = CodeGraph()
        graph.add_node(_node("src/m.py::TaintAware", kind=SymbolKind.MIXIN))
        graph.add_node(_node("src/f.py::SecurityFrame"))
        graph.add_edge(_edge("src/f.py::SecurityFrame", "src/m.py::TaintAware", EdgeRelation.IMPLEMENTS))

        analyzer = GapAnalyzer()
        report = analyzer.analyze(graph)

        assert "src/m.py::TaintAware" not in report.missing_mixin_impl


# --- Coverage Calculation ---


class TestCoverage:
    def test_coverage_calculation(self):
        graph = CodeGraph()
        graph.add_node(_node("src/a.py::A", file_path="src/a.py"))
        graph.add_node(_node("src/b.py::B", file_path="src/b.py"))

        analyzer = GapAnalyzer(project_files=["src/a.py", "src/b.py", "src/c.py"])
        report = analyzer.analyze(graph)

        assert report.coverage == pytest.approx(2 / 3)

    def test_coverage_zero_with_no_project_files(self):
        analyzer = GapAnalyzer()
        graph = CodeGraph()
        report = analyzer.analyze(graph)
        assert report.coverage == 0.0


# --- Y7: Test-Only Consumers ---


class TestTestOnlyConsumers:
    def test_symbol_used_only_by_tests(self):
        graph = CodeGraph()
        graph.add_node(_node("src/x.py::Helper", file_path="src/x.py"))
        graph.add_node(_node("tests/test_x.py::TestHelper", file_path="tests/test_x.py", is_test=True))
        graph.add_edge(_edge("tests/test_x.py::TestHelper", "src/x.py::Helper", EdgeRelation.IMPORTS))

        analyzer = GapAnalyzer()
        report = analyzer.analyze(graph)

        assert "src/x.py::Helper" in report.test_only_consumers

    def test_symbol_used_by_prod_code_not_test_only(self):
        graph = CodeGraph()
        graph.add_node(_node("src/x.py::Helper", file_path="src/x.py"))
        graph.add_node(_node("src/y.py::Consumer", file_path="src/y.py"))
        graph.add_edge(_edge("src/y.py::Consumer", "src/x.py::Helper", EdgeRelation.IMPORTS))

        analyzer = GapAnalyzer()
        report = analyzer.analyze(graph)

        assert "src/x.py::Helper" not in report.test_only_consumers


# --- Builder Metadata Integration ---


class TestBuilderMetadata:
    def test_builder_meta_propagated(self):
        analyzer = GapAnalyzer()
        graph = CodeGraph()
        report = analyzer.analyze(
            graph,
            builder_meta={
                "star_imports": ["src/a.py"],
                "dynamic_imports": ["src/b.py"],
                "type_checking_imports": ["src/c.py"],
                "unparseable_files": ["src/d.py"],
            },
        )

        assert report.star_imports == ["src/a.py"]
        assert report.dynamic_imports == ["src/b.py"]
        assert report.type_checking_only == ["src/c.py"]
        assert report.unparseable_files == ["src/d.py"]
