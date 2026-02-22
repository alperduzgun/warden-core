"""Tests for GraphQueryService."""

from __future__ import annotations

from warden.analysis.domain.code_graph import (
    CodeGraph,
    EdgeRelation,
    GapReport,
    SymbolEdge,
    SymbolKind,
    SymbolNode,
)
from warden.analysis.services.graph_query_service import GraphQueryService

# --- Helpers ---


def _node(
    fqn: str,
    name: str = "",
    kind: SymbolKind = SymbolKind.CLASS,
    file_path: str = "src/foo.py",
    is_test: bool = False,
    metadata: dict | None = None,
) -> SymbolNode:
    return SymbolNode(
        fqn=fqn,
        name=name or fqn.split("::")[-1],
        kind=kind,
        file_path=file_path,
        line=1,
        module="",
        is_test=is_test,
        metadata=metadata or {},
    )


def _edge(
    source: str, target: str, relation: EdgeRelation = EdgeRelation.IMPORTS
) -> SymbolEdge:
    return SymbolEdge(source=source, target=target, relation=relation)


# --- Orphan Evidence ---


class TestOrphanEvidence:
    def test_collects_direct_references(self):
        graph = CodeGraph()
        graph.add_node(_node("src/utils.py::Helper", file_path="src/utils.py"))
        graph.add_node(_node("src/main.py::App", file_path="src/main.py"))
        graph.add_edge(
            _edge("src/main.py::App", "src/utils.py::Helper", EdgeRelation.IMPORTS)
        )

        report = GapReport(orphan_files=["src/utils.py"])
        svc = GraphQueryService(graph, report)

        evidence = svc.collect_evidence("orphan_file", "src/utils.py")
        assert evidence["direct_references_who_uses"] == 1
        assert evidence["symbols_in_file"] == 1

    def test_no_references_zero_count(self):
        graph = CodeGraph()
        graph.add_node(_node("src/orphan.py::Lone", file_path="src/orphan.py"))

        report = GapReport(orphan_files=["src/orphan.py"])
        svc = GraphQueryService(graph, report)

        evidence = svc.collect_evidence("orphan_file", "src/orphan.py")
        assert evidence["direct_references_who_uses"] == 0

    def test_dynamic_importers_flag(self):
        graph = CodeGraph()
        graph.add_node(_node("src/plugin.py::Plugin", file_path="src/plugin.py"))

        report = GapReport(
            orphan_files=["src/plugin.py"],
            dynamic_imports=["src/loader.py"],
        )
        svc = GraphQueryService(graph, report)

        evidence = svc.collect_evidence("orphan_file", "src/plugin.py")
        assert evidence["project_has_dynamic_importers"] is True

    def test_framework_in_evidence(self):
        graph = CodeGraph()
        report = GapReport(detected_framework="django")
        svc = GraphQueryService(graph, report)

        evidence = svc.collect_evidence("orphan_file", "manage.py")
        assert evidence["detected_framework"] == "django"


# --- Unreachable Evidence ---


class TestUnreachableEvidence:
    def test_used_by_tests_only(self):
        graph = CodeGraph()
        graph.add_node(_node("src/x.py::Helper", file_path="src/x.py"))
        graph.add_node(
            _node(
                "tests/test_x.py::TestHelper",
                file_path="tests/test_x.py",
                is_test=True,
            )
        )
        graph.add_edge(
            _edge(
                "tests/test_x.py::TestHelper",
                "src/x.py::Helper",
                EdgeRelation.IMPORTS,
            )
        )

        report = GapReport(unreachable_from_entry=["src/x.py"])
        svc = GraphQueryService(graph, report)

        evidence = svc.collect_evidence("unreachable", "src/x.py")
        assert evidence["used_by_anyone"] is True
        assert evidence["test_only_users"] >= 1

    def test_decorator_metadata_collected(self):
        graph = CodeGraph()
        graph.add_node(
            _node(
                "src/views.py::index",
                kind=SymbolKind.FUNCTION,
                file_path="src/views.py",
                metadata={"decorators": ["app.route"]},
            )
        )

        report = GapReport(unreachable_from_entry=["src/views.py"])
        svc = GraphQueryService(graph, report)

        evidence = svc.collect_evidence("unreachable", "src/views.py")
        assert "app.route" in evidence["decorators_found"]


# --- Missing Mixin Evidence ---


class TestMissingMixinEvidence:
    def test_mixin_evidence_collected(self):
        graph = CodeGraph()
        graph.add_node(
            _node(
                "src/base.py::TaintAware",
                kind=SymbolKind.MIXIN,
                file_path="src/base.py",
            )
        )

        report = GapReport(
            missing_mixin_impl=["src/base.py::TaintAware"],
            detected_framework="fastapi",
        )
        svc = GraphQueryService(graph, report)

        evidence = svc.collect_evidence("missing_mixin_impl", "src/base.py")
        assert evidence["mixin_count_in_file"] == 1
        assert "mixin_TaintAware" in evidence
        assert evidence["detected_framework"] == "fastapi"


# --- Prompt Formatting ---


class TestFormatAsPrompt:
    def test_empty_evidence(self):
        graph = CodeGraph()
        report = GapReport()
        svc = GraphQueryService(graph, report)
        assert svc.format_as_prompt({}) == ""

    def test_formats_key_value_pairs(self):
        graph = CodeGraph()
        report = GapReport()
        svc = GraphQueryService(graph, report)

        result = svc.format_as_prompt(
            {"direct_references": 3, "framework": "django"}
        )
        assert "[GRAPH EVIDENCE]:" in result
        assert "direct_references: 3" in result
        assert "framework: django" in result

    def test_formats_lists(self):
        graph = CodeGraph()
        report = GapReport()
        svc = GraphQueryService(graph, report)

        result = svc.format_as_prompt({"files": ["a.py", "b.py"]})
        assert "a.py" in result
        assert "b.py" in result


# --- Unknown type ---


class TestUnknownType:
    def test_unknown_type_returns_empty(self):
        graph = CodeGraph()
        report = GapReport()
        svc = GraphQueryService(graph, report)
        assert svc.collect_evidence("nonexistent_type", "foo.py") == {}
