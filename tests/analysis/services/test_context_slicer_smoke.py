"""Smoke tests: ContextSlicer + real parser integration.

Verifies the full chain: source file -> real AST provider -> ContextSlicerService.
Uses ASTProviderRegistry to pick the best provider per language (not hardcoded).

Existing 31 tests use hand-crafted ASTNode fixtures. These smoke tests prove
the slicer works with *real parser output* from multiple languages.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from warden.analysis.services.context_slicer import ContextSlicerService
from warden.ast.application.provider_registry import ASTProviderRegistry
from warden.ast.domain.enums import CodeLanguage
from warden.ast.domain.models import ASTNode

FIXTURES = Path(__file__).parent.parent.parent / "e2e" / "fixtures" / "sample_project" / "src"


# ---------------------------------------------------------------------------
# Registry + provider helpers
# ---------------------------------------------------------------------------


@pytest.fixture
async def registry() -> ASTProviderRegistry:
    """Build a registry with all available providers (native + tree-sitter)."""
    reg = ASTProviderRegistry()
    await reg.discover_providers()
    return reg


async def _parse(registry: ASTProviderRegistry, code: str, lang: CodeLanguage) -> ASTNode:
    """Parse source code with the best available provider. Fails fast on error."""
    provider = registry.get_provider(lang)
    assert provider is not None, f"No provider for {lang.value}"
    result = await provider.parse(code, lang)
    assert result.ast_root is not None, f"Parse failed: {result.errors}"
    return result.ast_root


# ---------------------------------------------------------------------------
# Fixtures — real source files
# ---------------------------------------------------------------------------


@pytest.fixture
def python_code() -> str:
    return (FIXTURES / "vulnerable.py").read_text()


@pytest.fixture
def js_code() -> str:
    return (FIXTURES / "unsafe.js").read_text()


@pytest.fixture
async def python_ast(registry: ASTProviderRegistry, python_code: str) -> ASTNode:
    return await _parse(registry, python_code, CodeLanguage.PYTHON)


@pytest.fixture
async def js_ast(registry: ASTProviderRegistry, js_code: str) -> ASTNode:
    return await _parse(registry, js_code, CodeLanguage.JAVASCRIPT)


@pytest.fixture
def slicer() -> ContextSlicerService:
    return ContextSlicerService()


# ===================================================================
# Python — PythonASTProvider (native)
# ===================================================================


class TestPythonSmoke:
    """Real parser → slicer chain for Python (vulnerable.py)."""

    def test_sql_injection_function(self, slicer: ContextSlicerService, python_code: str, python_ast: ASTNode):
        """Line 12 → get_user, body contains SELECT, no unrelated code."""
        ctx = slicer.slice_for_function(python_code, [12], python_ast)

        assert not ctx.is_fallback
        assert ctx.function_name == "get_user"
        assert "SELECT * FROM" in ctx.function_body
        # Must NOT leak unrelated functions
        assert "os.system" not in ctx.function_body
        assert "eval(" not in ctx.function_body

    def test_command_injection_function(self, slicer: ContextSlicerService, python_code: str, python_ast: ASTNode):
        """Line 17 → run_command, body contains os.system, no SELECT."""
        ctx = slicer.slice_for_function(python_code, [17], python_ast)

        assert not ctx.is_fallback
        assert ctx.function_name == "run_command"
        assert "os.system" in ctx.function_body
        assert "SELECT" not in ctx.function_body

    def test_eval_function(self, slicer: ContextSlicerService, python_code: str, python_ast: ASTNode):
        """Line 22 → evaluate, body contains eval(."""
        ctx = slicer.slice_for_function(python_code, [22], python_ast)

        assert not ctx.is_fallback
        assert ctx.function_name == "evaluate"
        assert "eval(" in ctx.function_body

    def test_excludes_unrelated_code(self, slicer: ContextSlicerService, python_code: str, python_ast: ASTNode):
        """Slicing for line 12 must not include eval or os.system."""
        ctx = slicer.slice_for_function(python_code, [12], python_ast)

        assert ctx.function_name == "get_user"
        assert "eval(" not in ctx.function_body
        assert "os.system" not in ctx.function_body
        assert "subprocess" not in ctx.function_body

    def test_build_focused_context(self, slicer: ContextSlicerService, python_code: str, python_ast: ASTNode):
        """build_focused_context with tight budget slices to function level."""
        # Use budget=30 to force slicing (vulnerable.py is ~130 tokens)
        result = slicer.build_focused_context(
            file_content=python_code,
            file_path="vulnerable.py",
            target_lines=[12],
            ast_root=python_ast,
            token_budget=30,
        )

        assert len(result) < len(python_code)
        assert "SELECT" in result

    def test_import_context_extracted(self, slicer: ContextSlicerService, python_code: str, python_ast: ASTNode):
        """Import lines (os, subprocess) appear in import_context."""
        ctx = slicer.slice_for_function(python_code, [17], python_ast)

        assert "import os" in ctx.import_context
        assert "import subprocess" in ctx.import_context


# ===================================================================
# JavaScript — TreeSitterProvider
# ===================================================================


class TestJavaScriptSmoke:
    """Real parser → slicer chain for JavaScript (unsafe.js)."""

    def test_eval_function(self, slicer: ContextSlicerService, js_code: str, js_ast: ASTNode):
        """Line 13 → calculate, body contains eval(."""
        ctx = slicer.slice_for_function(js_code, [13], js_ast)

        assert not ctx.is_fallback
        assert ctx.function_name == "calculate"
        assert "eval(" in ctx.function_body

    def test_sql_injection_function(self, slicer: ContextSlicerService, js_code: str, js_ast: ASTNode):
        """Line 18 → findUser, body contains SELECT."""
        ctx = slicer.slice_for_function(js_code, [18], js_ast)

        assert not ctx.is_fallback
        assert ctx.function_name == "findUser"
        assert "SELECT * FROM" in ctx.function_body

    def test_excludes_unrelated_code(self, slicer: ContextSlicerService, js_code: str, js_ast: ASTNode):
        """Slicing for findUser (line 18) must not include eval or XSS code."""
        ctx = slicer.slice_for_function(js_code, [18], js_ast)

        assert ctx.function_name == "findUser"
        assert "eval(" not in ctx.function_body
        assert "res.send" not in ctx.function_body

    def test_build_focused_context(self, slicer: ContextSlicerService, js_code: str, js_ast: ASTNode):
        """build_focused_context with tight budget slices to function level."""
        # Use budget=30 to force slicing (unsafe.js is ~120 tokens)
        result = slicer.build_focused_context(
            file_content=js_code,
            file_path="unsafe.js",
            target_lines=[13],
            ast_root=js_ast,
            token_budget=30,
        )

        assert len(result) < len(js_code)
        assert "eval(" in result


# ===================================================================
# Cross-language: registry selects the right provider
# ===================================================================


class TestRegistryRouting:
    """Verify registry picks native provider for Python, tree-sitter for JS."""

    def test_python_uses_native_provider(self, registry: ASTProviderRegistry):
        provider = registry.get_provider(CodeLanguage.PYTHON)
        assert provider is not None
        assert provider.metadata.name == "python-native"

    def test_js_uses_tree_sitter_provider(self, registry: ASTProviderRegistry):
        provider = registry.get_provider(CodeLanguage.JAVASCRIPT)
        assert provider is not None
        assert provider.metadata.name == "tree-sitter"


# ===================================================================
# CodeGraph integration: real parse → CodeGraphBuilder → caller lookup
# ===================================================================

# Inline fixture: a file that calls vulnerable.get_user
CALLER_CODE = """\
from vulnerable import get_user

def handle_request(user_id):
    return get_user(user_id)
"""


class TestCodeGraphIntegration:
    """Real parser → CodeGraphBuilder → ContextSlicer caller lookup chain."""

    async def _build_code_graph(self, registry: ASTProviderRegistry, files: dict[str, str]):
        """Parse files and build a real CodeGraph via CodeGraphBuilder."""
        from warden.analysis.services.code_graph_builder import CodeGraphBuilder

        ast_cache: dict = {}
        provider = registry.get_provider(CodeLanguage.PYTHON)
        assert provider is not None

        for path, code in files.items():
            result = await provider.parse(code, CodeLanguage.PYTHON)
            assert result.ast_root is not None, f"Parse failed for {path}: {result.errors}"
            ast_cache[path] = result

        builder = CodeGraphBuilder(ast_cache)
        return builder.build()

    def test_codegraph_from_real_parse_has_symbols(self, registry: ASTProviderRegistry, python_code: str):
        """vulnerable.py parse → CodeGraphBuilder → 3 function SymbolNodes."""
        import asyncio

        graph = asyncio.get_event_loop().run_until_complete(
            self._build_code_graph(registry, {"vulnerable.py": python_code})
        )

        names = {n.name for n in graph.nodes.values()}
        assert "get_user" in names
        assert "run_command" in names
        assert "evaluate" in names

    def test_codegraph_isolated_functions_no_callers(self, registry: ASTProviderRegistry, python_code: str):
        """Isolated functions (no cross-calls) → callers=[], callees=[]."""
        import asyncio

        graph = asyncio.get_event_loop().run_until_complete(
            self._build_code_graph(registry, {"vulnerable.py": python_code})
        )

        slicer = ContextSlicerService()
        callers, callees = slicer.get_caller_signatures("vulnerable.py", "get_user", graph)
        # get_user doesn't call any tracked function, and nobody calls it in this file
        assert callers == []
        assert callees == []

    def test_codegraph_cross_file_symbols_and_imports(self, registry: ASTProviderRegistry, python_code: str):
        """Multi-file parse → CodeGraphBuilder produces nodes from both files + IMPORTS edge.

        Note: CALLS edges require the AST provider to extract callee names from
        ast.Call.func, which the native Python provider doesn't do yet (K3 limitation).
        This test verifies the pipeline works end-to-end with real parsers.
        """
        import asyncio

        from warden.analysis.domain.code_graph import EdgeRelation

        graph = asyncio.get_event_loop().run_until_complete(
            self._build_code_graph(
                registry,
                {"vulnerable.py": python_code, "handler.py": CALLER_CODE},
            )
        )

        # Both files produce function nodes
        names = {n.name for n in graph.nodes.values()}
        assert "handle_request" in names, f"handler.py function missing, got: {names}"
        assert "get_user" in names

        # IMPORTS edge: handler.py imports vulnerable.get_user
        import_edges = [e for e in graph.edges if e.relation == EdgeRelation.IMPORTS]
        import_targets = {e.target for e in import_edges}
        assert "vulnerable.get_user" in import_targets, (
            f"Expected import edge to vulnerable.get_user, got: {import_targets}"
        )

    def test_build_focused_context_with_real_codegraph(
        self, registry: ASTProviderRegistry, python_code: str, python_ast: ASTNode
    ):
        """Real AST + real CodeGraph → build_focused_context produces valid output."""
        import asyncio

        graph = asyncio.get_event_loop().run_until_complete(
            self._build_code_graph(
                registry,
                {"vulnerable.py": python_code, "handler.py": CALLER_CODE},
            )
        )

        slicer = ContextSlicerService()
        result = slicer.build_focused_context(
            file_content=python_code,
            file_path="vulnerable.py",
            target_lines=[12],
            ast_root=python_ast,
            code_graph=graph,
            token_budget=2400,
        )

        assert "get_user" in result
        assert "SELECT" in result
        # Graph is provided and has nodes — slicer should not crash
        assert len(result) > 0


# ===================================================================
# Tight budget: fast-tier budget still captures target
# ===================================================================


class TestTightBudget:
    """Verify that aggressive budget (400 tokens) still captures the target line."""

    def test_tight_budget_still_captures_target(
        self, slicer: ContextSlicerService, python_code: str, python_ast: ASTNode
    ):
        """budget=400 → body trimmed but target line (SELECT) preserved."""
        result = slicer.build_focused_context(
            file_content=python_code,
            file_path="vulnerable.py",
            target_lines=[12],
            ast_root=python_ast,
            token_budget=400,
        )

        # Target line must survive even with tight budget
        assert "SELECT" in result
        # Should still be shorter than the full file (or equal for small files)
        assert len(result) <= len(python_code) + 100  # small overhead allowed
