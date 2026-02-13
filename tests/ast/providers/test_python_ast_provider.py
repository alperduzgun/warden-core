"""
Tests for Python AST provider - Focus on model/enum extraction.

Verifies fix for issue #14: AST node type mapping for fields and enums.
"""

import pytest
from warden.ast.providers.python_ast_provider import PythonASTProvider
from warden.ast.domain.enums import CodeLanguage, ASTNodeType, ParseStatus


class TestPythonFieldExtraction:
    """Test that Python class fields are correctly identified as FIELD nodes."""

    @pytest.mark.asyncio
    async def test_pydantic_model_fields_detected(self):
        """Test Pydantic BaseModel fields are detected as FIELD type."""
        provider = PythonASTProvider()

        source_code = '''
from pydantic import BaseModel

class User(BaseModel):
    id: int
    name: str
    email: str
    age: int = 0
'''

        result = await provider.parse(source_code, CodeLanguage.PYTHON)

        assert result.status == ParseStatus.SUCCESS
        assert result.ast_root is not None

        # Find the User class
        classes = result.ast_root.find_nodes(ASTNodeType.CLASS)
        user_class = next((c for c in classes if c.name == "User"), None)
        assert user_class is not None

        # Find FIELD nodes (annotated assignments in class body)
        fields = [child for child in user_class.children if child.node_type == ASTNodeType.FIELD]

        # Should have 4 fields: id, name, email, age
        assert len(fields) >= 4, f"Expected at least 4 fields, got {len(fields)}"

        field_names = {f.name for f in fields}
        assert "id" in field_names
        assert "name" in field_names
        assert "email" in field_names
        assert "age" in field_names

        # Check type annotations are preserved
        id_field = next((f for f in fields if f.name == "id"), None)
        assert id_field is not None
        assert "type_annotation" in id_field.attributes
        assert id_field.attributes["type_annotation"] == "int"

    @pytest.mark.asyncio
    async def test_dataclass_fields_detected(self):
        """Test dataclass fields are detected as FIELD type."""
        provider = PythonASTProvider()

        source_code = '''
from dataclasses import dataclass

@dataclass
class Product:
    id: str
    name: str
    price: float
    in_stock: bool = True
'''

        result = await provider.parse(source_code, CodeLanguage.PYTHON)

        assert result.status == ParseStatus.SUCCESS
        assert result.ast_root is not None

        # Find the Product class
        classes = result.ast_root.find_nodes(ASTNodeType.CLASS)
        product_class = next((c for c in classes if c.name == "Product"), None)
        assert product_class is not None

        # Find FIELD nodes
        fields = [child for child in product_class.children if child.node_type == ASTNodeType.FIELD]

        # Should have 4 fields
        assert len(fields) >= 4

        field_names = {f.name for f in fields}
        assert "id" in field_names
        assert "name" in field_names
        assert "price" in field_names
        assert "in_stock" in field_names

    @pytest.mark.asyncio
    async def test_plain_class_fields_detected(self):
        """Test plain Python class annotated fields are detected."""
        provider = PythonASTProvider()

        source_code = '''
class Config:
    host: str
    port: int
    debug: bool
'''

        result = await provider.parse(source_code, CodeLanguage.PYTHON)

        assert result.status == ParseStatus.SUCCESS
        assert result.ast_root is not None

        # Find the Config class
        classes = result.ast_root.find_nodes(ASTNodeType.CLASS)
        config_class = next((c for c in classes if c.name == "Config"), None)
        assert config_class is not None

        # Find FIELD nodes
        fields = [child for child in config_class.children if child.node_type == ASTNodeType.FIELD]

        assert len(fields) >= 3

        field_names = {f.name for f in fields}
        assert "host" in field_names
        assert "port" in field_names
        assert "debug" in field_names


class TestPythonEnumExtraction:
    """Test that Python Enum classes are correctly identified as ENUM nodes."""

    @pytest.mark.asyncio
    async def test_enum_detected_as_enum_type(self):
        """Test Enum classes are detected as ENUM type, not CLASS."""
        provider = PythonASTProvider()

        source_code = '''
from enum import Enum

class Status(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
'''

        result = await provider.parse(source_code, CodeLanguage.PYTHON)

        assert result.status == ParseStatus.SUCCESS
        assert result.ast_root is not None

        # Find ENUM nodes
        enums = result.ast_root.find_nodes(ASTNodeType.ENUM)

        # Should have 1 enum
        assert len(enums) >= 1

        status_enum = next((e for e in enums if e.name == "Status"), None)
        assert status_enum is not None
        assert status_enum.node_type == ASTNodeType.ENUM

    @pytest.mark.asyncio
    async def test_int_enum_detected(self):
        """Test IntEnum is detected as ENUM type."""
        provider = PythonASTProvider()

        source_code = '''
from enum import IntEnum

class Priority(IntEnum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
'''

        result = await provider.parse(source_code, CodeLanguage.PYTHON)

        assert result.status == ParseStatus.SUCCESS
        assert result.ast_root is not None

        # Find ENUM nodes
        enums = result.ast_root.find_nodes(ASTNodeType.ENUM)

        assert len(enums) >= 1

        priority_enum = next((e for e in enums if e.name == "Priority"), None)
        assert priority_enum is not None
        assert priority_enum.node_type == ASTNodeType.ENUM

    @pytest.mark.asyncio
    async def test_str_enum_detected(self):
        """Test StrEnum is detected as ENUM type."""
        provider = PythonASTProvider()

        source_code = '''
from enum import StrEnum

class Color(StrEnum):
    RED = "red"
    GREEN = "green"
    BLUE = "blue"
'''

        result = await provider.parse(source_code, CodeLanguage.PYTHON)

        assert result.status == ParseStatus.SUCCESS
        assert result.ast_root is not None

        # Find ENUM nodes
        enums = result.ast_root.find_nodes(ASTNodeType.ENUM)

        assert len(enums) >= 1

        color_enum = next((e for e in enums if e.name == "Color"), None)
        assert color_enum is not None
        assert color_enum.node_type == ASTNodeType.ENUM

    @pytest.mark.asyncio
    async def test_regular_class_not_detected_as_enum(self):
        """Test regular classes are CLASS type, not ENUM."""
        provider = PythonASTProvider()

        source_code = '''
class User:
    def __init__(self, name: str):
        self.name = name
'''

        result = await provider.parse(source_code, CodeLanguage.PYTHON)

        assert result.status == ParseStatus.SUCCESS
        assert result.ast_root is not None

        # Find CLASS nodes
        classes = result.ast_root.find_nodes(ASTNodeType.CLASS)

        assert len(classes) >= 1

        user_class = next((c for c in classes if c.name == "User"), None)
        assert user_class is not None
        assert user_class.node_type == ASTNodeType.CLASS

        # Should NOT be detected as ENUM
        enums = result.ast_root.find_nodes(ASTNodeType.ENUM)
        user_enums = [e for e in enums if e.name == "User"]
        assert len(user_enums) == 0


class TestPythonASTProviderBasics:
    """Basic tests for Python AST provider functionality."""

    @pytest.mark.asyncio
    async def test_provider_supports_python(self):
        """Test provider supports Python language."""
        provider = PythonASTProvider()
        assert provider.supports_language(CodeLanguage.PYTHON) is True
        assert provider.supports_language(CodeLanguage.JAVASCRIPT) is False

    @pytest.mark.asyncio
    async def test_provider_validates_successfully(self):
        """Test provider validation (always True for stdlib)."""
        provider = PythonASTProvider()
        assert await provider.validate() is True

    @pytest.mark.asyncio
    async def test_parse_simple_code(self):
        """Test parsing simple Python code."""
        provider = PythonASTProvider()

        source_code = '''
def hello():
    return "world"
'''

        result = await provider.parse(source_code, CodeLanguage.PYTHON)

        assert result.status == ParseStatus.SUCCESS
        assert result.ast_root is not None
        assert result.language == CodeLanguage.PYTHON

    @pytest.mark.asyncio
    async def test_parse_invalid_python(self):
        """Test parsing invalid Python returns error."""
        provider = PythonASTProvider()

        source_code = '''
def hello(
    # Syntax error: unclosed parenthesis
'''

        result = await provider.parse(source_code, CodeLanguage.PYTHON)

        assert result.status == ParseStatus.FAILED
        assert len(result.errors) > 0

    @pytest.mark.asyncio
    async def test_extract_dependencies(self):
        """Test dependency extraction from imports."""
        provider = PythonASTProvider()

        source_code = '''
import os
import sys
from pathlib import Path
from typing import List, Dict
'''

        deps = provider.extract_dependencies(source_code, CodeLanguage.PYTHON)

        assert "os" in deps
        assert "sys" in deps
        assert "pathlib" in deps
        assert "typing" in deps
