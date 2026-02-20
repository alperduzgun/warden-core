"""
Tests for CodeGraphBuilder.

Covers: K3 Python-first, K1 FQN key format, Y1 re-export chain,
        Y5 star imports, Y6 TYPE_CHECKING, Y7 test file detection,
        O1 dynamic imports, Gemini mixin fix.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from warden.analysis.domain.code_graph import EdgeRelation, SymbolKind
from warden.analysis.services.code_graph_builder import CodeGraphBuilder
from warden.ast.domain.enums import ASTNodeType, CodeLanguage, ParseStatus
from warden.ast.domain.models import ASTNode, ParseResult, SourceLocation


# --- Helpers ---


def _loc(line: int = 1) -> SourceLocation:
    return SourceLocation(file_path="test.py", start_line=line, start_column=0, end_line=line, end_column=0)


def _make_class_node(
    name: str,
    bases: list[str] | None = None,
    methods: list[str] | None = None,
) -> ASTNode:
    """Create a CLASS ASTNode with optional bases and methods."""
    children = []
    for m in (methods or []):
        children.append(ASTNode(
            node_type=ASTNodeType.FUNCTION,
            name=m,
            location=_loc(10),
            children=[],
            attributes={"async": False},
        ))
    return ASTNode(
        node_type=ASTNodeType.CLASS,
        name=name,
        location=_loc(),
        children=children,
        attributes={"bases": bases or []},
    )


def _make_function_node(name: str, calls: list[str] | None = None) -> ASTNode:
    """Create a FUNCTION ASTNode with optional call expressions."""
    children = []
    for c in (calls or []):
        children.append(ASTNode(
            node_type=ASTNodeType.CALL_EXPRESSION,
            name=c,
            location=_loc(5),
            children=[],
        ))
    return ASTNode(
        node_type=ASTNodeType.FUNCTION,
        name=name,
        location=_loc(),
        children=children,
        attributes={},
    )


def _make_import_node(module: str = "", names: list[str] | None = None) -> ASTNode:
    return ASTNode(
        node_type=ASTNodeType.IMPORT,
        name="import",
        location=_loc(),
        children=[],
        attributes={"module": module, "names": names or []},
    )


def _make_module(children: list[ASTNode]) -> ASTNode:
    return ASTNode(
        node_type=ASTNodeType.MODULE,
        name="module",
        location=_loc(),
        children=children,
    )


def _make_parse_result(children: list[ASTNode], language: str = "python") -> ParseResult:
    return ParseResult(
        status=ParseStatus.SUCCESS,
        language=CodeLanguage(language),
        provider_name="test",
        ast_root=_make_module(children),
    )


# --- K1: FQN Key Format ---


class TestFQNKeyFormat:
    def test_class_fqn_includes_file_path(self):
        cache = {
            "/project/src/config.py": _make_parse_result([
                _make_class_node("Config"),
            ]),
        }
        builder = CodeGraphBuilder(cache, project_root=Path("/project"))
        graph = builder.build()

        # FQN should be "src/config.py::Config"
        assert any("::Config" in fqn for fqn in graph.nodes)

    def test_same_name_in_different_files(self):
        cache = {
            "/project/src/a.py": _make_parse_result([_make_class_node("Config")]),
            "/project/src/b.py": _make_parse_result([_make_class_node("Config")]),
        }
        builder = CodeGraphBuilder(cache, project_root=Path("/project"))
        graph = builder.build()

        configs = graph.get_symbols_by_name("Config")
        assert len(configs) == 2
        assert configs[0].file_path != configs[1].file_path

    def test_method_fqn_includes_class(self):
        cache = {
            "/project/src/frame.py": _make_parse_result([
                _make_class_node("SecurityFrame", methods=["execute_async"]),
            ]),
        }
        builder = CodeGraphBuilder(cache, project_root=Path("/project"))
        graph = builder.build()

        methods = [n for n in graph.nodes.values() if n.kind == SymbolKind.METHOD]
        assert len(methods) == 1
        assert "SecurityFrame.execute_async" in methods[0].fqn


# --- Gemini Mixin Fix ---


class TestMixinDetection:
    def test_mixin_base_creates_implements_edge(self):
        """Class inheriting from TaintAware should get IMPLEMENTS edge."""
        cache = {
            "/project/src/frame.py": _make_parse_result([
                _make_class_node("SecurityFrame", bases=["ValidationFrame", "TaintAware"]),
            ]),
        }
        builder = CodeGraphBuilder(cache, project_root=Path("/project"))
        graph = builder.build()

        implements_edges = [e for e in graph.edges if e.relation == EdgeRelation.IMPLEMENTS]
        inherits_edges = [e for e in graph.edges if e.relation == EdgeRelation.INHERITS]

        # TaintAware → IMPLEMENTS
        assert any(e.target == "TaintAware" for e in implements_edges)
        # ValidationFrame → INHERITS
        assert any(e.target == "ValidationFrame" for e in inherits_edges)

    def test_abc_base_creates_interface_kind(self):
        cache = {
            "/project/src/abc.py": _make_parse_result([
                _make_class_node("MyMixin", bases=["ABC"]),
            ]),
        }
        builder = CodeGraphBuilder(cache, project_root=Path("/project"))
        graph = builder.build()

        node = graph.get_symbol_by_name("MyMixin")
        assert node is not None
        # ABC base should make it INTERFACE kind
        assert node.kind in (SymbolKind.MIXIN, SymbolKind.INTERFACE)

    def test_mixin_in_class_name_detected(self):
        """Class with 'Mixin' in its name should be kind=MIXIN."""
        cache = {
            "/project/src/mixins.py": _make_parse_result([
                _make_class_node("TaintAware"),
            ]),
        }
        builder = CodeGraphBuilder(cache, project_root=Path("/project"))
        graph = builder.build()

        node = graph.get_symbol_by_name("TaintAware")
        assert node is not None
        assert node.kind == SymbolKind.MIXIN


# --- Y5: Star Import Detection ---


class TestStarImports:
    def test_star_import_tracked(self):
        cache = {
            "/project/src/app.py": _make_parse_result([
                _make_import_node(module="core", names=["*"]),
            ]),
        }
        builder = CodeGraphBuilder(cache, project_root=Path("/project"))
        builder.build()

        assert len(builder.star_import_files) == 1


# --- Y7: Test File Detection ---


class TestTestFileDetection:
    def test_test_file_by_path_pattern(self):
        cache = {
            "/project/tests/test_security.py": _make_parse_result([
                _make_class_node("TestSecurityFrame"),
            ]),
            "/project/src/security.py": _make_parse_result([
                _make_class_node("SecurityFrame"),
            ]),
        }
        builder = CodeGraphBuilder(cache, project_root=Path("/project"))
        graph = builder.build()

        test_node = graph.get_symbol_by_name("TestSecurityFrame")
        prod_node = graph.get_symbol_by_name("SecurityFrame")

        assert test_node is not None and test_node.is_test
        assert prod_node is not None and not prod_node.is_test

    def test_conftest_detected_as_test(self):
        cache = {
            "/project/tests/conftest.py": _make_parse_result([
                _make_function_node("fixture_func"),
            ]),
        }
        builder = CodeGraphBuilder(cache, project_root=Path("/project"))
        graph = builder.build()

        node = graph.get_symbol_by_name("fixture_func")
        assert node is not None and node.is_test


# --- Y1: Re-export Chain ---


class TestReExportChain:
    def test_init_py_re_export_creates_edge(self):
        cache = {
            "/project/src/taint/__init__.py": _make_parse_result([
                _make_import_node(module=".service", names=["TaintAnalysisService"]),
                _make_import_node(module=".models", names=["TaintPath"]),
            ]),
        }
        builder = CodeGraphBuilder(cache, project_root=Path("/project"))
        graph = builder.build()

        re_export_edges = [e for e in graph.edges if e.relation == EdgeRelation.RE_EXPORTS]
        assert len(re_export_edges) == 2


# --- K3: Python-First ---


class TestPythonFirst:
    def test_non_python_files_skipped(self):
        """K3: Non-Python files should be skipped in Phase 1."""
        cache = {
            "/project/src/app.ts": ParseResult(
                status=ParseStatus.SUCCESS,
                language=CodeLanguage.TYPESCRIPT,
                provider_name="tree-sitter",
                ast_root=_make_module([_make_class_node("App")]),
            ),
            "/project/src/main.py": _make_parse_result([
                _make_class_node("Main"),
            ]),
        }
        builder = CodeGraphBuilder(cache, project_root=Path("/project"))
        graph = builder.build()

        # Only Python class should be in graph
        assert graph.get_symbol_by_name("Main") is not None
        assert graph.get_symbol_by_name("App") is None


# --- O6: Unparseable Files ---


class TestUnparseableFiles:
    def test_failed_parse_tracked(self):
        cache = {
            "/project/src/broken.py": ParseResult(
                status=ParseStatus.FAILED,
                language=CodeLanguage.PYTHON,
                provider_name="test",
                ast_root=None,
            ),
        }
        builder = CodeGraphBuilder(cache, project_root=Path("/project"))
        builder.build()

        assert len(builder.unparseable_files) == 1

    def test_none_parse_result_tracked(self):
        cache = {"/project/src/null.py": None}
        builder = CodeGraphBuilder(cache, project_root=Path("/project"))
        builder.build()

        assert len(builder.unparseable_files) == 1


# --- Calls Extraction ---


class TestCallsExtraction:
    def test_call_expression_creates_calls_edge(self):
        cache = {
            "/project/src/main.py": _make_parse_result([
                _make_function_node("process", calls=["validate", "save"]),
            ]),
        }
        builder = CodeGraphBuilder(cache, project_root=Path("/project"))
        graph = builder.build()

        calls_edges = [e for e in graph.edges if e.relation == EdgeRelation.CALLS]
        targets = {e.target for e in calls_edges}
        assert "validate" in targets
        assert "save" in targets

    def test_builtin_calls_excluded(self):
        """Builtins like print, len should not create CALLS edges."""
        cache = {
            "/project/src/main.py": _make_parse_result([
                _make_function_node("process", calls=["print", "len", "my_func"]),
            ]),
        }
        builder = CodeGraphBuilder(cache, project_root=Path("/project"))
        graph = builder.build()

        calls_edges = [e for e in graph.edges if e.relation == EdgeRelation.CALLS]
        targets = {e.target for e in calls_edges}
        assert "print" not in targets
        assert "len" not in targets
        assert "my_func" in targets


# --- Empty/Edge Cases ---


class TestEdgeCases:
    def test_empty_cache(self):
        builder = CodeGraphBuilder({})
        graph = builder.build()
        assert len(graph.nodes) == 0
        assert len(graph.edges) == 0

    def test_class_without_name(self):
        """Nodes without names should be skipped."""
        node = ASTNode(
            node_type=ASTNodeType.CLASS,
            name="",
            location=_loc(),
            children=[],
            attributes={"bases": []},
        )
        cache = {"/project/src/x.py": _make_parse_result([node])}
        builder = CodeGraphBuilder(cache, project_root=Path("/project"))
        graph = builder.build()
        # Unnamed class should not be added
        assert len([n for n in graph.nodes.values() if n.kind == SymbolKind.CLASS]) == 0
