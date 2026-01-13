"""
Java AST provider using javalang.

This provider uses javalang (pure Python Java parser) to parse Java source
code into Warden's universal AST representation.
"""

from typing import Optional, Any, List
import structlog
import javalang
from javalang.tree import Node

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

logger = structlog.get_logger()


class JavaParserProvider(IASTProvider):
    """
    Java AST provider using javalang library.

    Provides AST parsing for Java code (Java 8 syntax).
    Pure Python implementation, no JVM required.

    Features:
        - Java 8 syntax support
        - Pure Python (zero JVM complexity)
        - Fast parsing
        - Universal AST conversion

    Dependencies:
        - javalang: Pure Python Java parser
    """

    @property
    def metadata(self) -> ASTProviderMetadata:
        """Get provider metadata."""
        return ASTProviderMetadata(
            name="javalang-parser",
            version="0.1.0",
            supported_languages=[CodeLanguage.JAVA],
            priority=ASTProviderPriority.NATIVE,
            description="Java AST provider using javalang (Java 8)",
            author="Warden Team",
            requires_installation=True,
            installation_command="pip install warden-ast-java",
        )

    def supports_language(self, language: CodeLanguage) -> bool:
        """Check if language is supported."""
        return language == CodeLanguage.JAVA

    async def parse(
        self,
        source_code: str,
        language: CodeLanguage,
        file_path: Optional[str] = None,
    ) -> ParseResult:
        """
        Parse Java source code to universal AST.

        Args:
            source_code: Java source code to parse
            language: Must be CodeLanguage.JAVA
            file_path: Optional file path for error reporting

        Returns:
            ParseResult with universal AST or errors
        """
        # Validate inputs
        if not source_code:
            return ParseResult(
                status=ParseStatus.FAILED,
                language=language,
                provider_name=self.metadata.name,
                file_path=file_path,
                errors=[ParseError(message="source_code cannot be empty")],
            )

        if not self.supports_language(language):
            return ParseResult(
                status=ParseStatus.UNSUPPORTED,
                language=language,
                provider_name=self.metadata.name,
                file_path=file_path,
                errors=[
                    ParseError(
                        message=f"javalang does not support {language.value}",
                        severity="error",
                    )
                ],
            )

        logger.info(
            "parse_started",
            language=language.value,
            file_path=file_path,
            code_length=len(source_code),
        )

        try:
            # Parse with javalang
            java_tree = javalang.parse.parse(source_code)

            # Convert to universal AST
            ast_root = self._convert_to_universal_ast(java_tree, file_path or "unknown")

            logger.info(
                "parse_completed",
                file_path=file_path,
                node_count=self._count_nodes(ast_root),
            )

            return ParseResult(
                status=ParseStatus.SUCCESS,
                language=language,
                provider_name=self.metadata.name,
                file_path=file_path,
                ast_root=ast_root,
                errors=[],
            )

        except javalang.parser.JavaSyntaxError as e:
            logger.warning(
                "java_syntax_error",
                error=str(e),
                file_path=file_path,
            )

            return ParseResult(
                status=ParseStatus.FAILED,
                language=language,
                provider_name=self.metadata.name,
                file_path=file_path,
                errors=[
                    ParseError(
                        message=f"Java syntax error: {str(e)}",
                        severity="error",
                    )
                ],
            )

        except Exception as e:
            logger.error(
                "parse_failed",
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

    async def validate(self) -> bool:
        """
        Validate provider setup.

        Checks if javalang is installed and working.

        Returns:
            True if provider is ready, False otherwise
        """
        try:
            # Check if javalang is available
            import javalang  # noqa: F401

            logger.debug("javalang_available", status="ok")
            return True

        except ImportError as e:
            logger.warning(
                "javalang_missing",
                error=str(e),
                install_command="pip install javalang>=0.13.0",
            )
            return False

    def _convert_to_universal_ast(self, java_node: Any, file_path: str) -> ASTNode:
        """
        Convert javalang AST to universal AST.

        Args:
            java_node: javalang node (CompilationUnit, ClassDeclaration, etc.)
            file_path: Source file path

        Returns:
            Universal ASTNode
        """
        node_type = self._map_node_type(java_node)
        name = self._extract_name(java_node)
        location = self._extract_location(java_node, file_path)
        children: List[ASTNode] = []

        # Recursively convert children
        if hasattr(java_node, 'children'):
            for child in java_node.children:
                if isinstance(child, Node):
                    children.append(self._convert_to_universal_ast(child, file_path))
                elif isinstance(child, list):
                    for item in child:
                        if isinstance(item, Node):
                            children.append(self._convert_to_universal_ast(item, file_path))

        # Extract attributes
        attributes = self._extract_attributes(java_node)

        return ASTNode(
            node_type=node_type,
            name=name,
            location=location,
            children=children,
            attributes=attributes,
            raw_node=None,  # Don't store raw node (not serializable)
        )

    def _map_node_type(self, java_node: Any) -> ASTNodeType:
        """Map javalang node type to universal AST node type."""
        type_name = type(java_node).__name__

        type_mapping = {
            'CompilationUnit': ASTNodeType.MODULE,
            'ClassDeclaration': ASTNodeType.CLASS,
            'InterfaceDeclaration': ASTNodeType.CLASS,
            'EnumDeclaration': ASTNodeType.CLASS,
            'MethodDeclaration': ASTNodeType.FUNCTION,
            'ConstructorDeclaration': ASTNodeType.FUNCTION,
            'FieldDeclaration': ASTNodeType.FIELD,
            'VariableDeclaration': ASTNodeType.VARIABLE_DECLARATION,
            'Import': ASTNodeType.IMPORT,
            'ReturnStatement': ASTNodeType.RETURN_STATEMENT,
            'IfStatement': ASTNodeType.IF_STATEMENT,
            'ForStatement': ASTNodeType.LOOP_STATEMENT,
            'WhileStatement': ASTNodeType.LOOP_STATEMENT,
            'TryStatement': ASTNodeType.TRY_CATCH,
            'ThrowStatement': ASTNodeType.THROW_STATEMENT,
            'MethodInvocation': ASTNodeType.CALL_EXPRESSION,
            'BinaryOperation': ASTNodeType.BINARY_EXPRESSION,
            'Literal': ASTNodeType.LITERAL,
            'MemberReference': ASTNodeType.MEMBER_ACCESS,
        }

        return type_mapping.get(type_name, ASTNodeType.UNKNOWN)

    def _extract_name(self, java_node: Any) -> Optional[str]:
        """Extract name from javalang node."""
        if hasattr(java_node, 'name'):
            return java_node.name
        if hasattr(java_node, 'member'):
            return java_node.member
        return None

    def _extract_location(self, java_node: Any, file_path: str) -> Optional[SourceLocation]:
        """Extract source location from javalang node."""
        if hasattr(java_node, 'position') and java_node.position:
            return SourceLocation(
                file_path=file_path,
                start_line=java_node.position.line,
                start_column=java_node.position.column,
                end_line=java_node.position.line,  # javalang doesn't provide end position
                end_column=java_node.position.column,
            )
        return None

    def _extract_attributes(self, java_node: Any) -> dict[str, Any]:
        """Extract attributes from javalang node."""
        attributes: dict[str, Any] = {}

        # Extract modifiers (public, private, static, etc.)
        if hasattr(java_node, 'modifiers'):
            attributes['modifiers'] = java_node.modifiers

        # Extract type information
        if hasattr(java_node, 'type'):
            attributes['type'] = str(java_node.type) if java_node.type else None

        # Extract return type (methods)
        if hasattr(java_node, 'return_type'):
            attributes['return_type'] = str(java_node.return_type) if java_node.return_type else 'void'

        # Extract parameters (methods)
        if hasattr(java_node, 'parameters') and java_node.parameters:
            attributes['parameters'] = [
                {
                    'name': p.name,
                    'type': str(p.type) if hasattr(p, 'type') else None
                }
                for p in java_node.parameters
            ]

        return attributes

    def _count_nodes(self, node: ASTNode) -> int:
        """Count total nodes in AST tree."""
        count = 1
        for child in node.children:
            count += self._count_nodes(child)
        return count
