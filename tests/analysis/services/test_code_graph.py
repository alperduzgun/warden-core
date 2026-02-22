"""
Tests for CodeGraph domain models.

Covers: K1 FQN keys, Y6 runtime flag, Y7 test exclusion,
        query methods, cycle detection, orphan detection.
"""

from __future__ import annotations

import pytest

from warden.analysis.domain.code_graph import (
    CodeGraph,
    EdgeRelation,
    GapReport,
    SymbolEdge,
    SymbolKind,
    SymbolNode,
)


# --- Fixtures ---


def _make_node(
    fqn: str,
    name: str = "",
    kind: SymbolKind = SymbolKind.CLASS,
    file_path: str = "src/foo.py",
    is_test: bool = False,
    bases: list[str] | None = None,
) -> SymbolNode:
    return SymbolNode(
        fqn=fqn,
        name=name or fqn.split("::")[-1],
        kind=kind,
        file_path=file_path,
        line=1,
        module="foo",
        is_test=is_test,
        bases=bases or [],
    )


def _make_edge(
    source: str,
    target: str,
    relation: EdgeRelation = EdgeRelation.IMPORTS,
    runtime: bool = True,
) -> SymbolEdge:
    return SymbolEdge(source=source, target=target, relation=relation, runtime=runtime)


@pytest.fixture
def empty_graph() -> CodeGraph:
    return CodeGraph()


@pytest.fixture
def simple_graph() -> CodeGraph:
    """Graph with 3 classes: Base → Child, Base → TestChild (test file)."""
    g = CodeGraph()
    g.add_node(_make_node("src/base.py::Base", kind=SymbolKind.CLASS))
    g.add_node(_make_node("src/child.py::Child", kind=SymbolKind.CLASS, file_path="src/child.py"))
    g.add_node(_make_node("tests/test_child.py::TestChild", kind=SymbolKind.CLASS, file_path="tests/test_child.py", is_test=True))

    # Child inherits Base
    g.add_edge(_make_edge("src/child.py::Child", "src/base.py::Base", EdgeRelation.INHERITS))
    # TestChild uses Base (test file)
    g.add_edge(_make_edge("tests/test_child.py::TestChild", "src/base.py::Base", EdgeRelation.IMPORTS))

    return g


# --- K1: FQN Key Collision Prevention ---


class TestFQNKeys:
    """K1: Verify FQN keys prevent symbol collision."""

    def test_same_name_different_files_no_collision(self, empty_graph: CodeGraph):
        """Two 'Config' classes in different files should both exist."""
        empty_graph.add_node(_make_node("src/llm/config.py::Config", file_path="src/llm/config.py"))
        empty_graph.add_node(_make_node("src/pipeline/config.py::Config", file_path="src/pipeline/config.py"))
        empty_graph.add_node(_make_node("src/build/config.py::Config", file_path="src/build/config.py"))

        assert len(empty_graph.nodes) == 3
        assert "src/llm/config.py::Config" in empty_graph.nodes
        assert "src/pipeline/config.py::Config" in empty_graph.nodes
        assert "src/build/config.py::Config" in empty_graph.nodes

    def test_get_symbols_by_name_returns_all_matches(self, empty_graph: CodeGraph):
        """get_symbols_by_name should return all 'Config' regardless of file."""
        empty_graph.add_node(_make_node("src/a.py::Config", file_path="src/a.py"))
        empty_graph.add_node(_make_node("src/b.py::Config", file_path="src/b.py"))

        results = empty_graph.get_symbols_by_name("Config")
        assert len(results) == 2

    def test_get_symbol_by_name_returns_first(self, empty_graph: CodeGraph):
        """get_symbol_by_name returns first match."""
        empty_graph.add_node(_make_node("src/a.py::Foo"))
        result = empty_graph.get_symbol_by_name("Foo")
        assert result is not None
        assert result.fqn == "src/a.py::Foo"

    def test_method_fqn_includes_class(self, empty_graph: CodeGraph):
        """Methods should have ClassName.method_name in FQN."""
        empty_graph.add_node(_make_node(
            "src/frame.py::SecurityFrame.execute_async",
            name="execute_async",
            kind=SymbolKind.METHOD,
        ))
        empty_graph.add_node(_make_node(
            "src/frame.py::ResilienceFrame.execute_async",
            name="execute_async",
            kind=SymbolKind.METHOD,
        ))

        assert len(empty_graph.nodes) == 2


# --- Y6: TYPE_CHECKING Runtime Flag ---


class TestRuntimeFlag:
    """Y6: TYPE_CHECKING import edge filtering."""

    def test_get_runtime_edges_excludes_type_checking(self, empty_graph: CodeGraph):
        empty_graph.add_edge(_make_edge("a", "b", runtime=True))
        empty_graph.add_edge(_make_edge("a", "c", runtime=False))  # TYPE_CHECKING

        runtime_edges = empty_graph.get_runtime_edges()
        assert len(runtime_edges) == 1
        assert runtime_edges[0].target == "b"

    def test_stats_counts_type_checking_edges(self, empty_graph: CodeGraph):
        empty_graph.add_edge(_make_edge("a", "b", runtime=True))
        empty_graph.add_edge(_make_edge("a", "c", runtime=False))

        stats = empty_graph.stats()
        assert stats["type_checking_edges"] == 1


# --- Y7: Test File Exclusion ---


class TestTestExclusion:
    """Y7: who_uses excludes test files by default."""

    def test_who_uses_excludes_tests_by_default(self, simple_graph: CodeGraph):
        """Default who_uses should not include TestChild's edge."""
        edges = simple_graph.who_uses("src/base.py::Base")
        sources = [e.source for e in edges]
        assert "src/child.py::Child" in sources
        assert "tests/test_child.py::TestChild" not in sources

    def test_who_uses_includes_tests_when_requested(self, simple_graph: CodeGraph):
        """include_tests=True should include TestChild."""
        edges = simple_graph.who_uses("src/base.py::Base", include_tests=True)
        sources = [e.source for e in edges]
        assert "tests/test_child.py::TestChild" in sources

    def test_stats_counts_test_nodes(self, simple_graph: CodeGraph):
        stats = simple_graph.stats()
        assert stats["test_nodes"] == 1


# --- Query Methods ---


class TestQueryMethods:
    def test_who_inherits(self, simple_graph: CodeGraph):
        children = simple_graph.who_inherits("src/base.py::Base")
        assert len(children) == 1
        assert children[0].name == "Child"

    def test_who_implements(self, empty_graph: CodeGraph):
        empty_graph.add_node(_make_node("src/m.py::TaintAware", kind=SymbolKind.MIXIN))
        empty_graph.add_node(_make_node("src/f.py::SecurityFrame"))
        empty_graph.add_edge(_make_edge(
            "src/f.py::SecurityFrame", "src/m.py::TaintAware", EdgeRelation.IMPLEMENTS
        ))

        impls = empty_graph.who_implements("src/m.py::TaintAware")
        assert len(impls) == 1
        assert impls[0].name == "SecurityFrame"

    def test_get_dependency_chain(self, empty_graph: CodeGraph):
        """A → B → C should produce chains."""
        empty_graph.add_node(_make_node("a::A"))
        empty_graph.add_node(_make_node("b::B"))
        empty_graph.add_node(_make_node("c::C"))
        empty_graph.add_edge(_make_edge("a::A", "b::B", EdgeRelation.IMPORTS))
        empty_graph.add_edge(_make_edge("b::B", "c::C", EdgeRelation.IMPORTS))

        chains = empty_graph.get_dependency_chain("a::A", max_depth=3)
        # Should have 2 chains: [A→B] and [A→B, B→C]
        assert len(chains) == 2

    def test_find_orphan_symbols(self, empty_graph: CodeGraph):
        empty_graph.add_node(_make_node("src/x.py::Orphan"))
        empty_graph.add_node(_make_node("src/y.py::Connected"))
        empty_graph.add_edge(_make_edge("src/y.py::Connected", "something", EdgeRelation.IMPORTS))

        orphans = empty_graph.find_orphan_symbols()
        assert len(orphans) == 1
        assert orphans[0].name == "Orphan"


# --- Circular Dependency Detection ---


class TestCircularDeps:
    def test_simple_cycle(self, empty_graph: CodeGraph):
        empty_graph.add_edge(_make_edge("A", "B", EdgeRelation.IMPORTS))
        empty_graph.add_edge(_make_edge("B", "A", EdgeRelation.IMPORTS))

        cycles = empty_graph.find_circular_deps()
        assert len(cycles) >= 1

    def test_no_cycle(self, empty_graph: CodeGraph):
        empty_graph.add_edge(_make_edge("A", "B", EdgeRelation.IMPORTS))
        empty_graph.add_edge(_make_edge("B", "C", EdgeRelation.IMPORTS))

        cycles = empty_graph.find_circular_deps()
        assert len(cycles) == 0


# --- GapReport ---


class TestGapReport:
    def test_has_critical_gaps_with_broken_imports(self):
        report = GapReport(broken_imports=["missing.module"])
        assert report.has_critical_gaps()

    def test_no_critical_gaps_clean(self):
        report = GapReport()
        assert not report.has_critical_gaps()

    def test_summary(self):
        report = GapReport(
            orphan_files=["a.py"],
            broken_imports=["x.y"],
            circular_deps=[["a", "b", "a"]],
            coverage=0.85,
        )
        s = report.summary()
        assert s["orphan_files"] == 1
        assert s["broken_imports"] == 1
        assert s["circular_deps"] == 1
        assert s["coverage"] == 0.85

    def test_serialization_roundtrip(self):
        report = GapReport(
            orphan_files=["a.py"],
            star_imports=["b.py"],
            dynamic_imports=["c.py"],
            coverage=0.9,
        )
        data = report.to_json()
        restored = GapReport.from_json(data)
        assert restored.orphan_files == ["a.py"]
        assert restored.star_imports == ["b.py"]
        assert restored.coverage == 0.9
