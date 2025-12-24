"""
C# AST provider using tree-sitter-c-sharp.

Provides AST parsing for C# code (C# 1-10 syntax) without requiring .NET runtime.
Uses tree-sitter for fast, pure-Python parsing with comprehensive C# language support.
"""

from __future__ import annotations

from typing import Optional, Any
import structlog

from warden.ast.application.provider_interface import IASTProvider
from warden.ast.domain.enums import (
    CodeLanguage,
    ASTProviderPriority,
    ParseStatus,
    ASTNodeType,
)
from warden.ast.domain.models import (
    ASTProviderMetadata,
    ParseResult,
    ParseError,
    ASTNode,
    SourceLocation,
)

logger = structlog.get_logger(__name__)


class CSharpParserProvider(IASTProvider):
    """
    C# AST provider using tree-sitter-c-sharp library.

    Provides AST parsing for C# code (C# 1-10 syntax).
    Pure Python implementation, no .NET runtime required.

    Features:
        - C# 1-10 syntax support
        - Pure Python (zero .NET complexity)
        - Fast parsing (tree-sitter C implementation)
        - Universal AST conversion
        - Modern C# features (records, patterns, async/await, LINQ)

    Supported C# Constructs:
        - Classes, structs, interfaces, enums, records
        - Methods, properties, fields, constructors
        - Namespaces and using directives
        - Attributes (C# annotations)
        - Async/await patterns
        - Properties with getter/setter
        - Partial classes

    Dependencies:
        - tree-sitter: Python bindings for tree-sitter
        - tree-sitter-c-sharp: C# grammar for tree-sitter

    Example:
        ```python
        provider = CSharpParserProvider()

        if await provider.validate():
            result = await provider.parse(
                csharp_code,
                CodeLanguage.CSHARP,
                "UserService.cs"
            )

            if result.status == ParseStatus.SUCCESS:
                print(f"Nodes: {len(result.ast_root.children)}")
        ```
    """

    def __init__(self) -> None:
        """Initialize C# parser provider."""
        self._parser: Optional[Any] = None
        self._language: Optional[Any] = None

    @property
    def metadata(self) -> ASTProviderMetadata:
        """Get provider metadata."""
        return ASTProviderMetadata(
            name="csharp-parser",
            version="0.1.0",
            supported_languages=[CodeLanguage.CSHARP],
            priority=ASTProviderPriority.NATIVE,
            description="C# AST provider using tree-sitter-c-sharp (C# 1-10)",
            author="Warden Team",
            requires_installation=True,
            installation_command="pip install warden-ast-csharp",
        )

    def supports_language(self, language: CodeLanguage) -> bool:
        """
        Check if language is supported.

        Args:
            language: Language to check

        Returns:
            True if language is C#
        """
        return language == CodeLanguage.CSHARP

    async def validate(self) -> bool:
        """
        Validate provider setup and dependencies.

        Checks if tree-sitter and tree-sitter-c-sharp are installed.
        Initializes parser if dependencies are available.

        Returns:
            True if provider is ready to use
        """
        try:
            from tree_sitter import Language, Parser
            import tree_sitter_c_sharp as tscs

            # Initialize language and parser
            self._language = Language(tscs.language())
            self._parser = Parser(self._language)

            logger.debug("csharp_provider_validated", status="ok")
            return True

        except ImportError as e:
            logger.warning(
                "csharp_provider_missing_dependency",
                error=str(e),
                install_command="pip install tree-sitter-c-sharp>=0.21.0",
            )
            return False
        except Exception as e:
            logger.error(
                "csharp_provider_validation_failed",
                error=str(e),
                error_type=type(e).__name__,
            )
            return False

    async def parse(
        self,
        source_code: str,
        language: CodeLanguage,
        file_path: Optional[str] = None,
    ) -> ParseResult:
        """
        Parse C# source code to universal AST.

        Args:
            source_code: C# source code to parse
            language: Must be CodeLanguage.CSHARP
            file_path: Optional file path for error reporting

        Returns:
            ParseResult with universal AST or errors

        Example:
            ```python
            result = await provider.parse(
                'public class User { public string Name { get; set; } }',
                CodeLanguage.CSHARP,
                "User.cs"
            )
            ```
        """
        # Validation
        if not source_code:
            return ParseResult(
                status=ParseStatus.FAILED,
                language=language,
                provider_name=self.metadata.name,
                file_path=file_path,
                errors=[ParseError(message="source_code cannot be empty", severity="error")],
            )

        if not self.supports_language(language):
            return ParseResult(
                status=ParseStatus.UNSUPPORTED,
                language=language,
                provider_name=self.metadata.name,
                file_path=file_path,
                errors=[
                    ParseError(
                        message=f"Provider does not support {language.value}",
                        severity="error",
                    )
                ],
            )

        # Initialize parser if needed
        if not self._parser:
            is_valid = await self.validate()
            if not is_valid:
                return ParseResult(
                    status=ParseStatus.FAILED,
                    language=language,
                    provider_name=self.metadata.name,
                    file_path=file_path,
                    errors=[
                        ParseError(
                            message="Provider dependencies not installed. Run: pip install tree-sitter-c-sharp>=0.21.0",
                            severity="error",
                        )
                    ],
                )

        logger.info(
            "csharp_parse_started",
            language=language.value,
            file_path=file_path,
            code_length=len(source_code),
        )

        try:
            # Parse with tree-sitter
            tree = self._parser.parse(bytes(source_code, "utf8"))

            # Convert to universal AST
            ast_root = self._convert_to_universal_ast(tree.root_node, file_path or "unknown")

            node_count = self._count_nodes(ast_root)
            logger.info(
                "csharp_parse_completed",
                file_path=file_path,
                node_count=node_count,
            )

            return ParseResult(
                status=ParseStatus.SUCCESS,
                language=language,
                provider_name=self.metadata.name,
                file_path=file_path,
                ast_root=ast_root,
                errors=[],
            )

        except Exception as e:
            logger.error(
                "csharp_parse_failed",
                error=str(e),
                error_type=type(e).__name__,
                file_path=file_path,
            )

            return ParseResult(
                status=ParseStatus.FAILED,
                language=language,
                provider_name=self.metadata.name,
                file_path=file_path,
                errors=[
                    ParseError(
                        message=f"Parsing failed: {str(e)}",
                        severity="error",
                    )
                ],
            )

    def _convert_to_universal_ast(self, node: Any, file_path: str) -> ASTNode:
        """
        Convert tree-sitter node to universal AST.

        Args:
            node: tree-sitter Node object
            file_path: Source file path

        Returns:
            Universal ASTNode
        """
        node_type = self._map_node_type(node)
        name = self._extract_name(node)
        location = self._extract_location(node, file_path)

        # Recursively convert children (only named nodes)
        children = [
            self._convert_to_universal_ast(child, file_path)
            for child in node.children
            if child.is_named  # Skip punctuation/keywords
        ]

        attributes = self._extract_attributes(node)

        return ASTNode(
            node_type=node_type,
            name=name,
            location=location,
            children=children,
            attributes=attributes,
            raw_node=None,  # Don't serialize tree-sitter nodes
        )

    def _map_node_type(self, node: Any) -> ASTNodeType:
        """
        Map tree-sitter C# node type to universal AST node type.

        Args:
            node: tree-sitter Node

        Returns:
            Universal ASTNodeType
        """
        type_mapping = {
            # Top-level structures
            "compilation_unit": ASTNodeType.MODULE,
            "namespace_declaration": ASTNodeType.MODULE,
            # Type declarations
            "class_declaration": ASTNodeType.CLASS,
            "struct_declaration": ASTNodeType.CLASS,
            "interface_declaration": ASTNodeType.CLASS,
            "enum_declaration": ASTNodeType.CLASS,
            "record_declaration": ASTNodeType.CLASS,  # C# 9+
            # Members
            "method_declaration": ASTNodeType.FUNCTION,
            "constructor_declaration": ASTNodeType.FUNCTION,
            "destructor_declaration": ASTNodeType.FUNCTION,
            "field_declaration": ASTNodeType.FIELD,
            "property_declaration": ASTNodeType.PROPERTY,
            "event_declaration": ASTNodeType.FIELD,
            # Imports
            "using_directive": ASTNodeType.IMPORT,
            # Statements
            "return_statement": ASTNodeType.RETURN_STATEMENT,
            "if_statement": ASTNodeType.IF_STATEMENT,
            "for_statement": ASTNodeType.LOOP_STATEMENT,
            "foreach_statement": ASTNodeType.LOOP_STATEMENT,
            "while_statement": ASTNodeType.LOOP_STATEMENT,
            "do_statement": ASTNodeType.LOOP_STATEMENT,
            "try_statement": ASTNodeType.TRY_CATCH,
            "throw_statement": ASTNodeType.THROW_STATEMENT,
            "switch_statement": ASTNodeType.IF_STATEMENT,  # Conditional logic
            # Expressions
            "invocation_expression": ASTNodeType.CALL_EXPRESSION,
            "binary_expression": ASTNodeType.BINARY_EXPRESSION,
            "unary_expression": ASTNodeType.UNARY_EXPRESSION,
            "assignment_expression": ASTNodeType.BINARY_EXPRESSION,
            "literal_expression": ASTNodeType.LITERAL,
            "identifier_name": ASTNodeType.IDENTIFIER,
            "identifier": ASTNodeType.IDENTIFIER,
            "member_access_expression": ASTNodeType.MEMBER_ACCESS,
            "element_access_expression": ASTNodeType.ARRAY_ACCESS,
            "conditional_expression": ASTNodeType.IF_STATEMENT,  # Ternary
            # C# Specific
            "attribute": ASTNodeType.ANNOTATION,
            "attribute_list": ASTNodeType.ANNOTATION,
            "await_expression": ASTNodeType.UNARY_EXPRESSION,
            "query_expression": ASTNodeType.CALL_EXPRESSION,  # LINQ
        }

        return type_mapping.get(node.type, ASTNodeType.UNKNOWN)

    def _extract_name(self, node: Any) -> Optional[str]:
        """
        Extract name from node (for declarations).

        Args:
            node: tree-sitter Node

        Returns:
            Name string or None
        """
        # For named declarations, find identifier child
        if node.type in [
            "class_declaration",
            "struct_declaration",
            "interface_declaration",
            "enum_declaration",
            "record_declaration",
            "method_declaration",
            "property_declaration",
            "field_declaration",
            "namespace_declaration",
            "constructor_declaration",
        ]:
            for child in node.children:
                if child.type == "identifier":
                    return child.text.decode("utf8")

        # For identifiers, use text directly
        if node.type in ["identifier", "identifier_name"]:
            return node.text.decode("utf8")

        return None

    def _extract_location(self, node: Any, file_path: str) -> SourceLocation:
        """
        Extract source location from tree-sitter node.

        Args:
            node: tree-sitter Node
            file_path: Source file path

        Returns:
            SourceLocation with line/column info
        """
        return SourceLocation(
            file_path=file_path,
            start_line=node.start_point[0] + 1,  # tree-sitter uses 0-based lines
            start_column=node.start_point[1],
            end_line=node.end_point[0] + 1,
            end_column=node.end_point[1],
        )

    def _extract_attributes(self, node: Any) -> dict[str, Any]:
        """
        Extract C# specific attributes from node.

        Extracts modifiers, property accessors, C# attributes, async flag, etc.

        Args:
            node: tree-sitter Node

        Returns:
            Dictionary of C# specific attributes
        """
        attributes: dict[str, Any] = {}

        # Extract modifiers (public, private, static, async, etc.)
        # For declarations, search both direct children and nested modifier nodes
        modifiers: list[str] = []

        # First pass: direct modifiers
        for child in node.children:
            if child.type in [
                "public",
                "private",
                "protected",
                "internal",
                "static",
                "async",
                "virtual",
                "override",
                "abstract",
                "sealed",
                "partial",
                "readonly",
                "const",
                "extern",
                "unsafe",
                "new",  # member hiding
                "volatile",
            ]:
                modifier_text = child.text.decode("utf8")
                if modifier_text not in modifiers:  # Avoid duplicates
                    modifiers.append(modifier_text)

        # Second pass: check for modifier_list or nested structures
        for child in node.children:
            if "modifier" in child.type.lower():
                # Recursively extract modifiers from modifier lists
                for nested in child.children:
                    if nested.type in [
                        "public", "private", "protected", "internal",
                        "static", "async", "virtual", "override",
                        "abstract", "sealed", "partial", "readonly",
                        "const", "extern", "unsafe", "new", "volatile"
                    ]:
                        modifier_text = nested.text.decode("utf8")
                        if modifier_text not in modifiers:
                            modifiers.append(modifier_text)

        if modifiers:
            attributes["modifiers"] = modifiers
            # Set async flag for methods
            if "async" in modifiers:
                attributes["async"] = True
            # Set partial flag for classes
            if "partial" in modifiers:
                attributes["partial"] = True

        # Extract property accessor info (get/set)
        if node.type == "property_declaration":
            for child in node.children:
                if child.type == "accessor_list":
                    accessor_text = child.text.decode("utf8")
                    attributes["has_getter"] = "get" in accessor_text
                    attributes["has_setter"] = "set" in accessor_text

        # Extract C# attributes (annotations like [Serializable])
        attribute_texts: list[str] = []
        for child in node.children:
            if child.type == "attribute_list":
                for attr_child in child.children:
                    if attr_child.type == "attribute":
                        attribute_texts.append(attr_child.text.decode("utf8"))

        if attribute_texts:
            attributes["attributes"] = attribute_texts

        # Extract using directive namespace
        if node.type == "using_directive":
            for child in node.children:
                if child.type in ["qualified_name", "identifier_name", "identifier"]:
                    attributes["namespace"] = child.text.decode("utf8")
                    break

        # Extract namespace name
        if node.type == "namespace_declaration":
            for child in node.children:
                if child.type in ["qualified_name", "identifier_name", "identifier"]:
                    attributes["namespace"] = child.text.decode("utf8")
                    break

        # Extract parameter list (for methods/constructors)
        if node.type in ["method_declaration", "constructor_declaration"]:
            for child in node.children:
                if child.type == "parameter_list":
                    params = self._extract_parameters(child)
                    if params:
                        attributes["parameters"] = params

        # Extract return type (for methods)
        if node.type == "method_declaration":
            for child in node.children:
                if child.type in ["predefined_type", "identifier_name", "generic_name", "array_type"]:
                    attributes["return_type"] = child.text.decode("utf8")
                    break

        return attributes

    def _extract_parameters(self, param_list_node: Any) -> list[dict[str, str]]:
        """
        Extract method parameters from parameter_list node.

        Args:
            param_list_node: tree-sitter parameter_list Node

        Returns:
            List of parameter dicts with name and type
        """
        parameters: list[dict[str, str]] = []

        for child in param_list_node.children:
            if child.type == "parameter":
                param_info: dict[str, str] = {}

                # Extract type and name
                for param_child in child.children:
                    if param_child.type in ["predefined_type", "identifier_name", "generic_name", "array_type"]:
                        param_info["type"] = param_child.text.decode("utf8")
                    elif param_child.type == "identifier":
                        param_info["name"] = param_child.text.decode("utf8")

                if param_info:
                    parameters.append(param_info)

        return parameters

    def _count_nodes(self, node: ASTNode) -> int:
        """
        Count total nodes in AST tree.

        Args:
            node: Root ASTNode

        Returns:
            Total node count
        """
        count = 1
        for child in node.children:
            count += self._count_nodes(child)
        return count

    async def cleanup(self) -> None:
        """Clean up resources (parser, language objects)."""
        self._parser = None
        self._language = None
        logger.debug("csharp_provider_cleanup_complete")
