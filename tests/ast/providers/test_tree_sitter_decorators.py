"""Tests for tree-sitter provider decorator/annotation extraction.

Covers: Python @decorators, Java @annotations, no-decorator functions.
"""

from __future__ import annotations

import pytest

from warden.ast.domain.enums import ASTNodeType, CodeLanguage
from warden.ast.providers.tree_sitter_provider import TREE_SITTER_AVAILABLE, TreeSitterProvider

pytestmark = pytest.mark.skipif(not TREE_SITTER_AVAILABLE, reason="tree-sitter not installed")


@pytest.fixture
async def provider():
    p = TreeSitterProvider()
    await p.validate()
    return p


# ---------------------------------------------------------------------------
# Python decorators
# ---------------------------------------------------------------------------


class TestPythonDecorators:
    @pytest.mark.asyncio
    async def test_multiple_decorators_on_function(self, provider):
        code = "@app.route('/login', methods=['POST'])\n@require_auth\n@rate_limit(100)\ndef login():\n    pass\n"
        result = await provider.parse(code, CodeLanguage.PYTHON, "test.py")
        funcs = result.ast_root.find_nodes(ASTNodeType.FUNCTION)

        assert len(funcs) == 1
        decs = funcs[0].attributes.get("decorators", [])
        assert "app.route" in decs
        assert "require_auth" in decs
        assert "rate_limit" in decs

    @pytest.mark.asyncio
    async def test_no_decorators(self, provider):
        code = "def plain():\n    return 42\n"
        result = await provider.parse(code, CodeLanguage.PYTHON, "test.py")
        funcs = result.ast_root.find_nodes(ASTNodeType.FUNCTION)

        assert len(funcs) == 1
        assert funcs[0].attributes.get("decorators", []) == []

    @pytest.mark.asyncio
    async def test_single_decorator(self, provider):
        code = "@staticmethod\ndef helper():\n    pass\n"
        result = await provider.parse(code, CodeLanguage.PYTHON, "test.py")
        funcs = result.ast_root.find_nodes(ASTNodeType.FUNCTION)

        assert len(funcs) == 1
        assert "staticmethod" in funcs[0].attributes.get("decorators", [])

    @pytest.mark.asyncio
    async def test_class_decorators(self, provider):
        code = "@dataclass\n@frozen\nclass Config:\n    name: str = 'test'\n"
        result = await provider.parse(code, CodeLanguage.PYTHON, "test.py")
        classes = result.ast_root.find_nodes(ASTNodeType.CLASS)

        assert len(classes) == 1
        decs = classes[0].attributes.get("decorators", [])
        assert "dataclass" in decs
        assert "frozen" in decs


# ---------------------------------------------------------------------------
# Java annotations
# ---------------------------------------------------------------------------


class TestJavaAnnotations:
    @pytest.mark.asyncio
    async def test_class_annotations(self, provider):
        code = '@RestController\n@RequestMapping("/api")\npublic class UserController {\n}\n'
        result = await provider.parse(code, CodeLanguage.JAVA, "Test.java")
        classes = result.ast_root.find_nodes(ASTNodeType.CLASS)

        assert len(classes) == 1
        decs = classes[0].attributes.get("decorators", [])
        assert "RestController" in decs
        assert "RequestMapping" in decs

    @pytest.mark.asyncio
    async def test_method_annotations(self, provider):
        code = (
            "public class Ctrl {\n"
            '    @GetMapping("/users")\n'
            "    @PreAuthorize(\"hasRole('ADMIN')\")\n"
            "    public void getUsers() {\n"
            "    }\n"
            "}\n"
        )
        result = await provider.parse(code, CodeLanguage.JAVA, "Test.java")
        methods = result.ast_root.find_nodes(ASTNodeType.METHOD)

        assert len(methods) >= 1
        decs = methods[0].attributes.get("decorators", [])
        assert "GetMapping" in decs
        assert "PreAuthorize" in decs

    @pytest.mark.asyncio
    async def test_no_annotations(self, provider):
        code = "public class Plain {\n    public void doStuff() {\n    }\n}\n"
        result = await provider.parse(code, CodeLanguage.JAVA, "Test.java")
        methods = result.ast_root.find_nodes(ASTNodeType.METHOD)

        assert len(methods) >= 1
        assert methods[0].attributes.get("decorators", []) == []
