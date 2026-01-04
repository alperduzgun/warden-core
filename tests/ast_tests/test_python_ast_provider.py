"""
Unit tests for PythonASTProvider.

Tests Python AST parsing with valid and invalid code.
"""

import pytest

from warden.ast.providers.python_ast_provider import PythonASTProvider
from warden.ast.domain.enums import (
    ASTNodeType,
    ASTProviderPriority,
    CodeLanguage,
    ParseStatus,
)


@pytest.mark.asyncio
class TestPythonASTProvider:
    """Test suite for PythonASTProvider."""

    async def test_provider_metadata(self) -> None:
        """Test provider metadata is correct."""
        provider = PythonASTProvider()

        assert provider.metadata.name == "python-native"
        assert provider.metadata.priority == ASTProviderPriority.NATIVE
        assert CodeLanguage.PYTHON in provider.metadata.supported_languages
        assert provider.metadata.requires_installation is False

    async def test_supports_python(self) -> None:
        """Test provider supports Python."""
        provider = PythonASTProvider()

        assert provider.supports_language(CodeLanguage.PYTHON) is True
        assert provider.supports_language(CodeLanguage.JAVASCRIPT) is False

    async def test_validate_always_ready(self) -> None:
        """Test provider is always valid (stdlib)."""
        provider = PythonASTProvider()

        is_valid = await provider.validate()

        assert is_valid is True

    async def test_parse_simple_function(self) -> None:
        """Test parsing simple Python function."""
        provider = PythonASTProvider()
        source = """
def hello():
    return "world"
"""

        result = await provider.parse(source, CodeLanguage.PYTHON)

        assert result.is_success()
        assert result.status == ParseStatus.SUCCESS
        assert result.language == CodeLanguage.PYTHON
        assert result.provider_name == "python-native"
        assert result.ast_root is not None

        # Check AST structure
        functions = result.ast_root.find_nodes(ASTNodeType.FUNCTION)
        assert len(functions) > 0
        assert functions[0].name == "hello"

    async def test_parse_class_with_methods(self) -> None:
        """Test parsing Python class."""
        provider = PythonASTProvider()
        source = """
class Calculator:
    def add(self, a, b):
        return a + b

    def subtract(self, a, b):
        return a - b
"""

        result = await provider.parse(source, CodeLanguage.PYTHON)

        assert result.is_success()
        assert result.ast_root is not None

        # Check for class
        classes = result.ast_root.find_nodes(ASTNodeType.CLASS)
        assert len(classes) > 0
        assert classes[0].name == "Calculator"

        # Check for methods
        functions = result.ast_root.find_nodes(ASTNodeType.FUNCTION)
        function_names = {f.name for f in functions}
        assert "add" in function_names
        assert "subtract" in function_names

    async def test_parse_with_imports(self) -> None:
        """Test parsing code with imports."""
        provider = PythonASTProvider()
        source = """
import os
from typing import List, Dict

def process_files():
    pass
"""

        result = await provider.parse(source, CodeLanguage.PYTHON)

        assert result.is_success()
        assert result.ast_root is not None

        # Check for imports
        imports = result.ast_root.find_nodes(ASTNodeType.IMPORT)
        assert len(imports) > 0

    async def test_parse_syntax_error(self) -> None:
        """Test parsing code with syntax error."""
        provider = PythonASTProvider()
        source = """
def broken(:
    return "invalid"
"""

        result = await provider.parse(source, CodeLanguage.PYTHON)

        assert not result.is_success()
        assert result.status == ParseStatus.FAILED
        assert len(result.errors) > 0
        assert "syntax" in result.errors[0].message.lower()

    async def test_parse_empty_code(self) -> None:
        """Test parsing empty code."""
        provider = PythonASTProvider()
        source = ""

        result = await provider.parse(source, CodeLanguage.PYTHON)

        assert result.is_success()
        assert result.ast_root is not None

    async def test_parse_unsupported_language(self) -> None:
        """Test parsing non-Python language."""
        provider = PythonASTProvider()
        source = "console.log('JavaScript')"

        result = await provider.parse(source, CodeLanguage.JAVASCRIPT)

        assert result.status == ParseStatus.UNSUPPORTED
        assert len(result.errors) > 0

    async def test_parse_with_file_path(self) -> None:
        """Test parsing with file path."""
        provider = PythonASTProvider()
        source = "def test(): pass"
        file_path = "/tmp/test.py"

        result = await provider.parse(source, CodeLanguage.PYTHON, file_path=file_path)

        assert result.is_success()
        assert result.file_path == file_path

    async def test_parse_async_function(self) -> None:
        """Test parsing async function."""
        provider = PythonASTProvider()
        source = """
async def fetch_data():
    return await get_data()
"""

        result = await provider.parse(source, CodeLanguage.PYTHON)

        assert result.is_success()
        assert result.ast_root is not None

        functions = result.ast_root.find_nodes(ASTNodeType.FUNCTION)
        assert len(functions) > 0
        assert functions[0].name == "fetch_data"
        # Check async attribute
        assert functions[0].attributes.get("async") is True

    async def test_parse_with_decorators(self) -> None:
        """Test parsing function with decorators."""
        provider = PythonASTProvider()
        source = """
@property
@cached
def get_value(self):
    return self._value
"""

        result = await provider.parse(source, CodeLanguage.PYTHON)

        assert result.is_success()
        assert result.ast_root is not None

        functions = result.ast_root.find_nodes(ASTNodeType.FUNCTION)
        assert len(functions) > 0
        # Check decorators
        decorators = functions[0].attributes.get("decorators", [])
        assert len(decorators) > 0

    async def test_find_nodes_by_name(self) -> None:
        """Test finding nodes by name."""
        provider = PythonASTProvider()
        source = """
def target_function():
    pass

def other_function():
    pass
"""

        result = await provider.parse(source, CodeLanguage.PYTHON)

        assert result.is_success()
        assert result.ast_root is not None

        # Find specific function by name
        nodes = result.ast_root.find_by_name("target_function")
        assert len(nodes) > 0
        assert nodes[0].name == "target_function"

    async def test_parse_time_recorded(self) -> None:
        """Test that parse time is recorded."""
        provider = PythonASTProvider()
        source = "def test(): pass"

        result = await provider.parse(source, CodeLanguage.PYTHON)

        assert result.is_success()
        assert result.parse_time_ms > 0
