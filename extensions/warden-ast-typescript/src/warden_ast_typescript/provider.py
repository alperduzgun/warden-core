"""
TypeScript/TSX AST provider using tree-sitter-typescript.

Provides AST parsing for TypeScript (.ts) and TSX (.tsx) code.
Uses tree-sitter for fast, pure-Python parsing with comprehensive TypeScript language support.
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


class TypeScriptParserProvider(IASTProvider):
    """
    TypeScript/TSX AST provider using tree-sitter-typescript library.

    Provides AST parsing for TypeScript (.ts) and TSX (.tsx) code.
    Pure Python implementation using dual grammar support.

    Features:
        - TypeScript 5.x syntax support
        - TSX (TypeScript + JSX) support
        - Pure Python (zero Node.js complexity)
        - Fast parsing (tree-sitter C implementation)
        - Universal AST conversion
        - Modern TypeScript features (decorators, generics, async/await)

    Supported TypeScript Constructs:
        - Interfaces, type aliases, enums
        - Classes with decorators
        - Functions, methods, arrow functions
        - Generics (functions, classes, interfaces)
        - Import/export statements (ESM)
        - Async/await patterns
        - Decorators (experimental)
        - JSX/TSX elements

    Dependencies:
        - tree-sitter: Python bindings for tree-sitter
        - tree-sitter-typescript: Dual grammar for TypeScript and TSX

    Example:
        ```python
        provider = TypeScriptParserProvider()

        if await provider.validate():
            result = await provider.parse(
                typescript_code,
                CodeLanguage.TYPESCRIPT,
                "UserService.ts"
            )

            if result.status == ParseStatus.SUCCESS:
                print(f"Nodes: {len(result.ast_root.children)}")
        ```
    """

    def __init__(self) -> None:
        """Initialize TypeScript parser provider with dual grammar support."""
        self._ts_parser: Optional[Any] = None  # For .ts files
        self._tsx_parser: Optional[Any] = None  # For .tsx files
        self._ts_language: Optional[Any] = None
        self._tsx_language: Optional[Any] = None

    @property
    def metadata(self) -> ASTProviderMetadata:
        """Get provider metadata."""
        return ASTProviderMetadata(
            name="typescript-parser",
            version="0.1.0",
            supported_languages=[CodeLanguage.TYPESCRIPT],
            priority=ASTProviderPriority.NATIVE,
            description="TypeScript/TSX AST provider using tree-sitter-typescript",
            author="Warden Team",
            requires_installation=True,
            installation_command="pip install warden-ast-typescript",
        )

    def supports_language(self, language: CodeLanguage) -> bool:
        """
        Check if language is supported.

        Args:
            language: Language to check

        Returns:
            True if language is TypeScript
        """
        return language == CodeLanguage.TYPESCRIPT

    async def validate(self) -> bool:
        """
        Validate provider setup and dependencies.

        Checks if tree-sitter and tree-sitter-typescript are installed.
        Initializes both TypeScript and TSX parsers.

        Returns:
            True if provider is ready to use
        """
        try:
            from tree_sitter import Language, Parser
            import tree_sitter_typescript as tsts

            # Initialize TypeScript language and parser
            self._ts_language = Language(tsts.language_typescript())
            self._ts_parser = Parser(self._ts_language)

            # Initialize TSX language and parser
            self._tsx_language = Language(tsts.language_tsx())
            self._tsx_parser = Parser(self._tsx_language)

            logger.debug(
                "typescript_provider_validated",
                status="ok",
                grammars=["typescript", "tsx"]
            )
            return True

        except ImportError as e:
            logger.warning(
                "typescript_provider_missing_dependency",
                error=str(e),
                install_command="pip install tree-sitter-typescript>=0.23.0",
            )
            return False
        except Exception as e:
            logger.error(
                "typescript_provider_validation_failed",
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
        Parse TypeScript/TSX source code to universal AST.

        Automatically detects whether to use TypeScript or TSX grammar based on file extension.

        Args:
            source_code: TypeScript/TSX source code to parse
            language: Must be CodeLanguage.TYPESCRIPT
            file_path: Optional file path (determines .ts vs .tsx grammar)

        Returns:
            ParseResult with universal AST or errors

        Example:
            ```python
            result = await provider.parse(
                'interface User { name: string; }',
                CodeLanguage.TYPESCRIPT,
                "User.ts"
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

        # Initialize parsers if needed
        if not self._ts_parser or not self._tsx_parser:
            is_valid = await self.validate()
            if not is_valid:
                return ParseResult(
                    status=ParseStatus.FAILED,
                    language=language,
                    provider_name=self.metadata.name,
                    file_path=file_path,
                    errors=[
                        ParseError(
                            message="Provider dependencies not installed. Run: pip install tree-sitter-typescript>=0.23.0",
                            severity="error",
                        )
                    ],
                )

        # Determine parser (TSX for .tsx files, TypeScript for everything else)
        is_tsx = file_path and file_path.endswith(".tsx")
        parser = self._tsx_parser if is_tsx else self._ts_parser
        grammar_type = "tsx" if is_tsx else "typescript"

        logger.info(
            "typescript_parse_started",
            language=language.value,
            file_path=file_path,
            code_length=len(source_code),
            grammar=grammar_type,
        )

        try:
            # Parse with tree-sitter
            tree = parser.parse(bytes(source_code, "utf8"))

            # Convert to universal AST
            ast_root = self._convert_to_universal_ast(tree.root_node, file_path or "unknown")

            node_count = self._count_nodes(ast_root)
            logger.info(
                "typescript_parse_completed",
                file_path=file_path,
                node_count=node_count,
                grammar=grammar_type,
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
                "typescript_parse_failed",
                error=str(e),
                error_type=type(e).__name__,
                file_path=file_path,
                grammar=grammar_type,
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

        # Container nodes (class_body, interface_body, etc.) should have their children flattened
        # These are structural containers in tree-sitter but not meaningful in the universal AST
        transparent_containers = {"class_body", "interface_body", "enum_body"}

        # Recursively convert children (only named nodes)
        children = []
        for child in node.children:
            if not child.is_named:  # Skip punctuation/keywords
                continue

            # If child is a transparent container, flatten its children into this node
            # Special handling: decorators that precede declarations should be attached to them
            if child.type in transparent_containers:
                grandchildren_list = [gc for gc in child.children if gc.is_named]
                pending_decorators = []

                for i, grandchild in enumerate(grandchildren_list):
                    if grandchild.type == "decorator":
                        # Collect decorators
                        pending_decorators.append(grandchild)
                    else:
                        # Convert grandchild and attach pending decorators
                        converted = self._convert_to_universal_ast(grandchild, file_path)
                        if pending_decorators:
                            # Attach decorators to this node's attributes
                            decorator_texts = [d.text.decode("utf8") for d in pending_decorators]
                            if "decorators" in converted.attributes:
                                converted.attributes["decorators"].extend(decorator_texts)
                            else:
                                converted.attributes["decorators"] = decorator_texts
                            pending_decorators = []
                        children.append(converted)

                # Any remaining decorators without a following declaration
                for decorator in pending_decorators:
                    children.append(self._convert_to_universal_ast(decorator, file_path))
            else:
                children.append(self._convert_to_universal_ast(child, file_path))

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
        Map tree-sitter TypeScript node type to universal AST node type.

        Args:
            node: tree-sitter Node

        Returns:
            Universal ASTNodeType
        """
        type_mapping = {
            # Top-level structures
            "program": ASTNodeType.MODULE,
            # Container bodies (transparent - children promoted)
            "class_body": ASTNodeType.MODULE,  # Use MODULE as transparent container
            "interface_body": ASTNodeType.MODULE,
            "enum_body": ASTNodeType.MODULE,
            # Type declarations
            "class_declaration": ASTNodeType.CLASS,
            "interface_declaration": ASTNodeType.CLASS,
            "type_alias_declaration": ASTNodeType.CLASS,
            "enum_declaration": ASTNodeType.CLASS,
            # Functions
            "function_declaration": ASTNodeType.FUNCTION,
            "method_definition": ASTNodeType.FUNCTION,
            "arrow_function": ASTNodeType.FUNCTION,
            "function_expression": ASTNodeType.FUNCTION,
            "generator_function_declaration": ASTNodeType.FUNCTION,
            # Members
            "public_field_definition": ASTNodeType.FIELD,
            "property_signature": ASTNodeType.PROPERTY,
            "method_signature": ASTNodeType.FUNCTION,
            # Imports/Exports
            "import_statement": ASTNodeType.IMPORT,
            "export_statement": ASTNodeType.IMPORT,
            # Statements
            "return_statement": ASTNodeType.RETURN_STATEMENT,
            "if_statement": ASTNodeType.IF_STATEMENT,
            "for_statement": ASTNodeType.LOOP_STATEMENT,
            "for_in_statement": ASTNodeType.LOOP_STATEMENT,
            "while_statement": ASTNodeType.LOOP_STATEMENT,
            "do_statement": ASTNodeType.LOOP_STATEMENT,
            "try_statement": ASTNodeType.TRY_CATCH,
            "throw_statement": ASTNodeType.THROW_STATEMENT,
            "switch_statement": ASTNodeType.IF_STATEMENT,
            # Expressions
            "call_expression": ASTNodeType.CALL_EXPRESSION,
            "binary_expression": ASTNodeType.BINARY_EXPRESSION,
            "unary_expression": ASTNodeType.UNARY_EXPRESSION,
            "assignment_expression": ASTNodeType.BINARY_EXPRESSION,
            "string": ASTNodeType.LITERAL,
            "number": ASTNodeType.LITERAL,
            "true": ASTNodeType.LITERAL,
            "false": ASTNodeType.LITERAL,
            "null": ASTNodeType.LITERAL,
            "undefined": ASTNodeType.LITERAL,
            "identifier": ASTNodeType.IDENTIFIER,
            "member_expression": ASTNodeType.MEMBER_ACCESS,
            "subscript_expression": ASTNodeType.ARRAY_ACCESS,
            "ternary_expression": ASTNodeType.IF_STATEMENT,
            # TypeScript Specific
            "decorator": ASTNodeType.ANNOTATION,
            "await_expression": ASTNodeType.UNARY_EXPRESSION,
            "as_expression": ASTNodeType.UNARY_EXPRESSION,  # Type assertion
            # JSX/TSX
            "jsx_element": ASTNodeType.CALL_EXPRESSION,
            "jsx_self_closing_element": ASTNodeType.CALL_EXPRESSION,
            "jsx_fragment": ASTNodeType.CALL_EXPRESSION,
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
            "interface_declaration",
            "type_alias_declaration",
            "enum_declaration",
            "function_declaration",
            "method_definition",
            "public_field_definition",
            "property_signature",
            "method_signature",
        ]:
            for child in node.children:
                # TypeScript uses type_identifier for class/interface names
                # and identifier/property_identifier for other names
                if child.type in ["identifier", "property_identifier", "type_identifier"]:
                    return child.text.decode("utf8")

        # For identifiers, use text directly
        if node.type in ["identifier", "property_identifier", "type_identifier"]:
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
        Extract TypeScript specific attributes from node.

        Extracts modifiers, decorators, generics, async flag, etc.

        Args:
            node: tree-sitter Node

        Returns:
            Dictionary of TypeScript specific attributes
        """
        attributes: dict[str, Any] = {}

        # Extract accessibility modifiers (public, private, protected)
        modifiers: list[str] = []

        # First pass: direct modifiers
        for child in node.children:
            if child.type in [
                "public",
                "private",
                "protected",
                "static",
                "async",
                "readonly",
                "abstract",
                "declare",
                "export",
                "default",
            ]:
                modifier_text = child.text.decode("utf8")
                if modifier_text not in modifiers:
                    modifiers.append(modifier_text)

        # Second pass: check for accessibility_modifier or nested structures
        for child in node.children:
            if "modifier" in child.type.lower() or child.type == "accessibility_modifier":
                for nested in child.children:
                    if nested.type in [
                        "public", "private", "protected", "static",
                        "async", "readonly", "abstract", "declare",
                        "export", "default"
                    ]:
                        modifier_text = nested.text.decode("utf8")
                        if modifier_text not in modifiers:
                            modifiers.append(modifier_text)

        if modifiers:
            attributes["modifiers"] = modifiers
            if "async" in modifiers:
                attributes["async"] = True
            if "abstract" in modifiers:
                attributes["abstract"] = True

        # Extract decorators (like @Component, @Injectable)
        decorators: list[str] = []
        for child in node.children:
            if child.type == "decorator":
                decorators.append(child.text.decode("utf8"))

        if decorators:
            attributes["decorators"] = decorators

        # Extract generics (type parameters)
        for child in node.children:
            if child.type == "type_parameters":
                attributes["generic"] = True
                attributes["type_parameters"] = child.text.decode("utf8")
                break

        # Extract import specifiers
        if node.type == "import_statement":
            for child in node.children:
                if child.type == "import_clause":
                    attributes["import_clause"] = child.text.decode("utf8")
                elif child.type == "string":
                    # Remove quotes from module path
                    module_path = child.text.decode("utf8").strip('"\'')
                    attributes["module"] = module_path

        # Extract export type (named, default, etc.)
        if node.type == "export_statement":
            for child in node.children:
                if child.type == "default":
                    attributes["export_type"] = "default"
                    break
            else:
                attributes["export_type"] = "named"

        # Extract interface extends clause
        if node.type == "interface_declaration":
            for child in node.children:
                if child.type == "extends_clause":
                    attributes["extends"] = child.text.decode("utf8")

        # Extract class extends/implements
        if node.type == "class_declaration":
            for child in node.children:
                if child.type == "class_heritage":
                    for heritage_child in child.children:
                        if heritage_child.type == "extends_clause":
                            attributes["extends"] = heritage_child.text.decode("utf8")
                        elif heritage_child.type == "implements_clause":
                            attributes["implements"] = heritage_child.text.decode("utf8")

        # Extract parameter list (for functions/methods)
        if node.type in ["function_declaration", "method_definition", "arrow_function"]:
            for child in node.children:
                if child.type == "formal_parameters":
                    params = self._extract_parameters(child)
                    if params:
                        attributes["parameters"] = params

        # Extract return type (for functions/methods)
        if node.type in ["function_declaration", "method_definition", "arrow_function"]:
            for child in node.children:
                if child.type == "type_annotation":
                    # Type annotation contains the actual type
                    for type_child in child.children:
                        if type_child.type != ":":  # Skip colon
                            attributes["return_type"] = type_child.text.decode("utf8")
                            break

        # Extract JSX tag name
        if node.type in ["jsx_element", "jsx_self_closing_element"]:
            for child in node.children:
                if child.type in ["jsx_opening_element", "jsx_self_closing_element"]:
                    for tag_child in child.children:
                        if tag_child.type == "identifier":
                            attributes["jsx_tag"] = tag_child.text.decode("utf8")
                            break

        return attributes

    def _extract_parameters(self, param_list_node: Any) -> list[dict[str, str]]:
        """
        Extract function parameters from formal_parameters node.

        Args:
            param_list_node: tree-sitter formal_parameters Node

        Returns:
            List of parameter dicts with name and type
        """
        parameters: list[dict[str, str]] = []

        for child in param_list_node.children:
            if child.type in ["required_parameter", "optional_parameter"]:
                param_info: dict[str, str] = {}

                # Extract name and type
                for param_child in child.children:
                    if param_child.type == "identifier":
                        param_info["name"] = param_child.text.decode("utf8")
                    elif param_child.type == "type_annotation":
                        # Type annotation contains the actual type
                        for type_child in param_child.children:
                            if type_child.type != ":":  # Skip colon
                                param_info["type"] = type_child.text.decode("utf8")
                                break

                if param_info:
                    if child.type == "optional_parameter":
                        param_info["optional"] = "true"
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
        """Clean up resources (parsers, language objects)."""
        self._ts_parser = None
        self._tsx_parser = None
        self._ts_language = None
        self._tsx_language = None
        logger.debug("typescript_provider_cleanup_complete")
