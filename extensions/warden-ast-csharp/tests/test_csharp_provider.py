"""
Unit tests for C# AST provider.
"""

import pytest
from warden_ast_csharp.provider import CSharpParserProvider
from warden.ast.domain.enums import CodeLanguage, ParseStatus, ASTNodeType


@pytest.fixture
async def provider():
    """Create and validate C# provider."""
    p = CSharpParserProvider()
    is_valid = await p.validate()
    if not is_valid:
        pytest.skip("tree-sitter-c-sharp not installed")
    return p


class TestProviderMetadata:
    """Test provider metadata and configuration."""

    def test_metadata_name(self, provider):
        """Test provider name."""
        assert provider.metadata.name == "csharp-parser"

    def test_metadata_version(self, provider):
        """Test provider version."""
        assert provider.metadata.version == "0.1.0"

    def test_supported_languages(self, provider):
        """Test supported languages."""
        assert CodeLanguage.CSHARP in provider.metadata.supported_languages

    def test_supports_csharp(self, provider):
        """Test C# language support check."""
        assert provider.supports_language(CodeLanguage.CSHARP) is True

    def test_does_not_support_java(self, provider):
        """Test other language rejection."""
        assert provider.supports_language(CodeLanguage.JAVA) is False


class TestBasicParsing:
    """Test basic C# parsing capabilities."""

    @pytest.mark.asyncio
    async def test_parse_simple_class(self, provider):
        """Test parsing a simple class."""
        code = """
        public class User
        {
            public string Name { get; set; }
        }
        """
        result = await provider.parse(code, CodeLanguage.CSHARP, "User.cs")

        assert result.status == ParseStatus.SUCCESS
        assert result.ast_root is not None
        assert result.errors == []

    @pytest.mark.asyncio
    async def test_parse_with_namespace(self, provider):
        """Test parsing class with namespace."""
        code = """
        using System;

        namespace MyApp.Services
        {
            public class UserService
            {
            }
        }
        """
        result = await provider.parse(code, CodeLanguage.CSHARP, "UserService.cs")

        assert result.status == ParseStatus.SUCCESS
        assert result.ast_root is not None

        # Find namespace node
        namespace_found = self._find_node_by_type(result.ast_root, ASTNodeType.MODULE)
        assert namespace_found is not None

    @pytest.mark.asyncio
    async def test_parse_empty_code(self, provider):
        """Test parsing empty code."""
        result = await provider.parse("", CodeLanguage.CSHARP, "empty.cs")

        assert result.status == ParseStatus.FAILED
        assert len(result.errors) > 0
        assert "empty" in result.errors[0].message.lower()

    @pytest.mark.asyncio
    async def test_parse_unsupported_language(self, provider):
        """Test parsing with wrong language."""
        result = await provider.parse("class Foo {}", CodeLanguage.JAVA, "Foo.java")

        assert result.status == ParseStatus.UNSUPPORTED
        assert len(result.errors) > 0

    def _find_node_by_type(self, node, node_type):
        """Helper to find node by type."""
        if node.node_type == node_type:
            return node
        for child in node.children:
            found = self._find_node_by_type(child, node_type)
            if found:
                return found
        return None


class TestPropertyParsing:
    """Test C# property parsing."""

    @pytest.mark.asyncio
    async def test_parse_auto_property(self, provider):
        """Test parsing auto-implemented property."""
        code = """
        public class Person
        {
            public string Name { get; set; }
        }
        """
        result = await provider.parse(code, CodeLanguage.CSHARP)

        assert result.status == ParseStatus.SUCCESS

        # Find property node
        prop_node = self._find_property_node(result.ast_root, "Name")
        assert prop_node is not None
        assert prop_node.node_type == ASTNodeType.PROPERTY
        assert prop_node.attributes.get("has_getter") is True
        assert prop_node.attributes.get("has_setter") is True

    @pytest.mark.asyncio
    async def test_parse_readonly_property(self, provider):
        """Test parsing read-only property."""
        code = """
        public class Person
        {
            public string Name { get; }
        }
        """
        result = await provider.parse(code, CodeLanguage.CSHARP)

        assert result.status == ParseStatus.SUCCESS

        prop_node = self._find_property_node(result.ast_root, "Name")
        assert prop_node is not None
        assert prop_node.attributes.get("has_getter") is True
        assert prop_node.attributes.get("has_setter") is False

    def _find_property_node(self, node, name):
        """Helper to find property by name."""
        if node.node_type == ASTNodeType.PROPERTY and node.name == name:
            return node
        for child in node.children:
            found = self._find_property_node(child, name)
            if found:
                return found
        return None


class TestAttributeParsing:
    """Test C# attribute (annotation) parsing."""

    @pytest.mark.asyncio
    async def test_parse_class_with_attribute(self, provider):
        """Test parsing class with C# attribute."""
        code = """
        [Serializable]
        public class User
        {
        }
        """
        result = await provider.parse(code, CodeLanguage.CSHARP)

        assert result.status == ParseStatus.SUCCESS

        # Find class node
        class_node = self._find_class_node(result.ast_root, "User")
        assert class_node is not None
        assert "attributes" in class_node.attributes
        assert "Serializable" in class_node.attributes["attributes"][0]

    def _find_class_node(self, node, name):
        """Helper to find class by name."""
        if node.node_type == ASTNodeType.CLASS and node.name == name:
            return node
        for child in node.children:
            found = self._find_class_node(child, name)
            if found:
                return found
        return None


class TestModifierExtraction:
    """Test C# modifier extraction."""

    @pytest.mark.asyncio
    async def test_parse_public_static_method(self, provider):
        """Test parsing method with modifiers."""
        code = """
        public class Helper
        {
            public static void DoSomething()
            {
            }
        }
        """
        result = await provider.parse(code, CodeLanguage.CSHARP)

        assert result.status == ParseStatus.SUCCESS

        # Find method node
        method_node = self._find_method_node(result.ast_root, "DoSomething")
        assert method_node is not None
        assert "modifiers" in method_node.attributes
        assert "public" in method_node.attributes["modifiers"]
        assert "static" in method_node.attributes["modifiers"]

    @pytest.mark.asyncio
    async def test_parse_async_method(self, provider):
        """Test parsing async method."""
        code = """
        public class UserService
        {
            public async Task<User> GetUserAsync()
            {
                return null;
            }
        }
        """
        result = await provider.parse(code, CodeLanguage.CSHARP)

        assert result.status == ParseStatus.SUCCESS

        method_node = self._find_method_node(result.ast_root, "GetUserAsync")
        assert method_node is not None
        assert method_node.attributes.get("async") is True
        assert "async" in method_node.attributes.get("modifiers", [])

    def _find_method_node(self, node, name):
        """Helper to find method by name."""
        if node.node_type == ASTNodeType.FUNCTION and node.name == name:
            return node
        for child in node.children:
            found = self._find_method_node(child, name)
            if found:
                return found
        return None


class TestUsingDirectives:
    """Test C# using directive parsing."""

    @pytest.mark.asyncio
    async def test_parse_using_directive(self, provider):
        """Test parsing using directives."""
        code = """
        using System;
        using System.Collections.Generic;

        public class MyClass
        {
        }
        """
        result = await provider.parse(code, CodeLanguage.CSHARP)

        assert result.status == ParseStatus.SUCCESS

        # Find using directives
        using_nodes = self._find_all_imports(result.ast_root)
        assert len(using_nodes) >= 2

    def _find_all_imports(self, node):
        """Helper to find all import nodes."""
        imports = []
        if node.node_type == ASTNodeType.IMPORT:
            imports.append(node)
        for child in node.children:
            imports.extend(self._find_all_imports(child))
        return imports


class TestRecordParsing:
    """Test C# 9+ record parsing."""

    @pytest.mark.asyncio
    async def test_parse_record(self, provider):
        """Test parsing C# record."""
        code = """
        public record UserDto(int Id, string Name, string Email);
        """
        result = await provider.parse(code, CodeLanguage.CSHARP)

        assert result.status == ParseStatus.SUCCESS

        # Find record node (mapped to CLASS)
        record_node = self._find_class_node(result.ast_root, "UserDto")
        assert record_node is not None
        assert record_node.node_type == ASTNodeType.CLASS

    def _find_class_node(self, node, name):
        """Helper to find class/record by name."""
        if node.node_type == ASTNodeType.CLASS and node.name == name:
            return node
        for child in node.children:
            found = self._find_class_node(child, name)
            if found:
                return found
        return None


class TestComplexCode:
    """Test parsing complex C# code."""

    @pytest.mark.asyncio
    async def test_parse_complete_class(self, provider):
        """Test parsing a complete class with multiple features."""
        code = """
        using System;
        using System.Threading.Tasks;

        namespace MyApp.Services
        {
            [Service]
            public class UserService
            {
                private readonly ILogger _logger;

                public UserService(ILogger logger)
                {
                    _logger = logger;
                }

                public string Name { get; set; }

                public async Task<bool> ValidateUserAsync(int userId)
                {
                    if (userId <= 0)
                    {
                        return false;
                    }

                    return await Task.FromResult(true);
                }
            }
        }
        """
        result = await provider.parse(code, CodeLanguage.CSHARP, "UserService.cs")

        assert result.status == ParseStatus.SUCCESS
        assert result.ast_root is not None
        assert result.errors == []

        # Verify various nodes exist
        assert self._has_namespace(result.ast_root)
        assert self._has_class(result.ast_root)
        assert self._has_property(result.ast_root)
        assert self._has_method(result.ast_root)

    def _has_namespace(self, node):
        """Check if AST has namespace."""
        if node.node_type == ASTNodeType.MODULE:
            return True
        return any(self._has_namespace(child) for child in node.children)

    def _has_class(self, node):
        """Check if AST has class."""
        if node.node_type == ASTNodeType.CLASS:
            return True
        return any(self._has_class(child) for child in node.children)

    def _has_property(self, node):
        """Check if AST has property."""
        if node.node_type == ASTNodeType.PROPERTY:
            return True
        return any(self._has_property(child) for child in node.children)

    def _has_method(self, node):
        """Check if AST has method."""
        if node.node_type == ASTNodeType.FUNCTION:
            return True
        return any(self._has_method(child) for child in node.children)
