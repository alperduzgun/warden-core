"""Tests for RustASTProvider."""

import pytest
from unittest.mock import MagicMock, patch

from warden.ast.domain.enums import (
    ASTNodeType,
    ASTProviderPriority,
    CodeLanguage,
    ParseStatus,
)
from warden.ast.providers.rust_ast_provider import RustASTProvider


@pytest.fixture
def provider():
    return RustASTProvider()


def _make_mock_metadata(functions=None, classes=None, imports=None, references=None):
    """Build a mock AstMetadata matching warden_core_rust schema."""
    meta = MagicMock()
    meta.functions = functions or []
    meta.classes = classes or []
    meta.imports = imports or []
    meta.references = references or []
    return meta


def _make_node_info(name, line_number=1, code_snippet=""):
    info = MagicMock()
    info.name = name
    info.line_number = line_number
    info.code_snippet = code_snippet
    return info


class TestRustASTProviderMetadata:
    def test_provider_name(self, provider):
        assert provider.metadata.name == "RustASTProvider"

    def test_priority_is_community(self, provider):
        assert provider.metadata.priority == ASTProviderPriority.COMMUNITY

    def test_supports_python(self, provider):
        assert CodeLanguage.PYTHON in provider.metadata.supported_languages

    def test_supports_typescript(self, provider):
        assert CodeLanguage.TYPESCRIPT in provider.metadata.supported_languages

    def test_supports_javascript(self, provider):
        assert CodeLanguage.JAVASCRIPT in provider.metadata.supported_languages

    def test_supports_go(self, provider):
        assert CodeLanguage.GO in provider.metadata.supported_languages

    def test_supports_java(self, provider):
        assert CodeLanguage.JAVA in provider.metadata.supported_languages


class TestRustASTProviderParse:
    @pytest.mark.asyncio
    async def test_parse_python_returns_shallow_tree(self, provider):
        """Rust provider builds MODULE root with flat FUNCTION/CLASS/IMPORT children."""
        mock_meta = _make_mock_metadata(
            functions=[_make_node_info("my_func", 10, "def my_func():")],
            classes=[_make_node_info("MyClass", 20, "class MyClass:")],
            imports=[_make_node_info("os", 1, "import os")],
            references=["my_func", "os", "MyClass", "print"],
        )

        with patch("warden.ast.providers.rust_ast_provider._RUST_AVAILABLE", True), \
             patch("warden.ast.providers.rust_ast_provider.warden_core_rust") as mock_rust:
            mock_rust.get_ast_metadata.return_value = mock_meta

            result = await provider.parse("import os\ndef my_func(): pass", CodeLanguage.PYTHON, "test.py")

        assert result.status == ParseStatus.SUCCESS
        assert result.provider_name == "RustASTProvider"
        assert result.ast_root is not None
        assert result.ast_root.node_type == ASTNodeType.MODULE

        # Check flat children
        children = result.ast_root.children
        assert len(children) == 3

        func_nodes = [c for c in children if c.node_type == ASTNodeType.FUNCTION]
        class_nodes = [c for c in children if c.node_type == ASTNodeType.CLASS]
        import_nodes = [c for c in children if c.node_type == ASTNodeType.IMPORT]

        assert len(func_nodes) == 1
        assert func_nodes[0].name == "my_func"
        assert func_nodes[0].location.start_line == 10

        assert len(class_nodes) == 1
        assert class_nodes[0].name == "MyClass"

        assert len(import_nodes) == 1
        assert import_nodes[0].name == "os"

        # Check references in root attributes
        assert result.ast_root.attributes["is_shallow"] is True
        assert "my_func" in result.ast_root.attributes["references"]
        assert len(result.ast_root.attributes["references"]) == 4

    @pytest.mark.asyncio
    async def test_parse_unsupported_language(self, provider):
        """Unsupported languages return UNSUPPORTED status."""
        with patch("warden.ast.providers.rust_ast_provider._RUST_AVAILABLE", True):
            result = await provider.parse("code", CodeLanguage.RUBY, "test.rb")

        assert result.status == ParseStatus.UNSUPPORTED

    @pytest.mark.asyncio
    async def test_graceful_degradation_without_rust(self, provider):
        """When Rust extension is not available, returns FAILED."""
        with patch("warden.ast.providers.rust_ast_provider._RUST_AVAILABLE", False):
            result = await provider.parse("code", CodeLanguage.PYTHON, "test.py")

        assert result.status == ParseStatus.FAILED

    @pytest.mark.asyncio
    async def test_parse_handles_rust_exception(self, provider):
        """Rust errors are caught and return FAILED."""
        with patch("warden.ast.providers.rust_ast_provider._RUST_AVAILABLE", True), \
             patch("warden.ast.providers.rust_ast_provider.warden_core_rust") as mock_rust:
            mock_rust.get_ast_metadata.side_effect = RuntimeError("Rust panic")

            result = await provider.parse("bad code", CodeLanguage.PYTHON, "test.py")

        assert result.status == ParseStatus.FAILED

    @pytest.mark.asyncio
    async def test_parse_time_is_recorded(self, provider):
        """Parse time in ms is recorded."""
        mock_meta = _make_mock_metadata()
        with patch("warden.ast.providers.rust_ast_provider._RUST_AVAILABLE", True), \
             patch("warden.ast.providers.rust_ast_provider.warden_core_rust") as mock_rust:
            mock_rust.get_ast_metadata.return_value = mock_meta

            result = await provider.parse("x = 1", CodeLanguage.PYTHON, "test.py")

        assert result.parse_time_ms >= 0


class TestRustASTProviderDependencies:
    def test_extract_dependencies_returns_import_names(self, provider):
        mock_meta = _make_mock_metadata(
            imports=[
                _make_node_info("os", 1),
                _make_node_info("sys", 2),
                _make_node_info("json", 3),
            ]
        )

        with patch("warden.ast.providers.rust_ast_provider._RUST_AVAILABLE", True), \
             patch("warden.ast.providers.rust_ast_provider.warden_core_rust") as mock_rust:
            mock_rust.get_ast_metadata.return_value = mock_meta

            deps = provider.extract_dependencies("import os\nimport sys\nimport json", CodeLanguage.PYTHON)

        assert deps == ["os", "sys", "json"]

    def test_extract_dependencies_without_rust(self, provider):
        with patch("warden.ast.providers.rust_ast_provider._RUST_AVAILABLE", False):
            deps = provider.extract_dependencies("import os", CodeLanguage.PYTHON)
        assert deps == []

    def test_extract_dependencies_unsupported_lang(self, provider):
        with patch("warden.ast.providers.rust_ast_provider._RUST_AVAILABLE", True):
            deps = provider.extract_dependencies("code", CodeLanguage.RUBY)
        assert deps == []


class TestRustASTProviderValidation:
    @pytest.mark.asyncio
    async def test_validate_returns_true_when_rust_available(self, provider):
        with patch("warden.ast.providers.rust_ast_provider._RUST_AVAILABLE", True):
            assert await provider.validate() is True

    @pytest.mark.asyncio
    async def test_validate_returns_false_without_rust(self, provider):
        with patch("warden.ast.providers.rust_ast_provider._RUST_AVAILABLE", False):
            assert await provider.validate() is False

    def test_supports_language_python(self, provider):
        with patch("warden.ast.providers.rust_ast_provider._RUST_AVAILABLE", True):
            assert provider.supports_language(CodeLanguage.PYTHON) is True

    def test_supports_language_ruby_false(self, provider):
        with patch("warden.ast.providers.rust_ast_provider._RUST_AVAILABLE", True):
            assert provider.supports_language(CodeLanguage.RUBY) is False

    def test_supports_language_without_rust(self, provider):
        with patch("warden.ast.providers.rust_ast_provider._RUST_AVAILABLE", False):
            assert provider.supports_language(CodeLanguage.PYTHON) is False
