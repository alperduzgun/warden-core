"""
Python Native AST Provider.

Uses Python's built-in ast module for parsing Python code.
Priority: NATIVE (highest priority for Python).
"""

import ast
import time
from typing import Any, Optional, Dict, List

from warden.ast.application.provider_interface import IASTProvider
from warden.ast.domain.models import (
    ASTNode,
    ASTProviderMetadata,
    ParseError,
    ParseResult,
    SourceLocation,
)
from warden.ast.domain.enums import (
    ASTNodeType,
    ASTProviderPriority,
    CodeLanguage,
    ParseStatus,
)


class PythonASTProvider(IASTProvider):
    """
    Native Python AST provider using built-in ast module.

    This is the highest priority provider for Python code.
    No external dependencies required - uses stdlib only.

    Advantages:
        - Native Python parsing (100% accurate)
        - No external dependencies
        - Fast performance
        - Rich type information

    Limitations:
        - Python only
        - Syntax must be valid Python
    """

    def __init__(self) -> None:
        """Initialize Python AST provider."""
        self._metadata = ASTProviderMetadata(
            name="python-native",
            priority=ASTProviderPriority.NATIVE,
            supported_languages=[CodeLanguage.PYTHON],
            version="1.0.0",
            description="Native Python AST parser using stdlib ast module",
            author="Warden Core Team",
            requires_installation=False,
        )

    @property
    def metadata(self) -> ASTProviderMetadata:
        """Get provider metadata."""
        return self._metadata

    async def parse(
        self,
        source_code: str,
        language: CodeLanguage,
        file_path: Optional[str] = None,
    ) -> ParseResult:
        """
        Parse Python source code.

        Args:
            source_code: Python source code
            language: Must be CodeLanguage.PYTHON
            file_path: Optional file path for error reporting

        Returns:
            ParseResult with AST and any errors
        """
        if language != CodeLanguage.PYTHON:
            return ParseResult(
                status=ParseStatus.UNSUPPORTED,
                language=language,
                provider_name=self.metadata.name,
                errors=[
                    ParseError(
                        message=f"Language {language.value} not supported by {self.metadata.name}",
                        severity="error",
                    )
                ],
            )

        start_time = time.time()
        errors: List[ParseError] = []

        try:
            # Parse Python code
            py_ast = ast.parse(source_code, filename=file_path or "<string>")

            # Convert to universal AST
            universal_ast = self._convert_to_universal_ast(py_ast, file_path or "<string>")

            parse_time_ms = (time.time() - start_time) * 1000

            return ParseResult(
                status=ParseStatus.SUCCESS,
                language=language,
                provider_name=self.metadata.name,
                ast_root=universal_ast,
                errors=[],
                warnings=[],
                parse_time_ms=parse_time_ms,
                file_path=file_path,
            )

        except SyntaxError as e:
            errors.append(
                ParseError(
                    message=f"Syntax error: {e.msg}",
                    location=SourceLocation(
                        file_path=file_path or "<string>",
                        start_line=e.lineno or 0,
                        start_column=e.offset or 0,
                        end_line=e.lineno or 0,
                        end_column=(e.offset or 0) + 1,
                    ) if e.lineno else None,
                    error_code="E0001",
                    severity="error",
                )
            )

            parse_time_ms = (time.time() - start_time) * 1000

            return ParseResult(
                status=ParseStatus.FAILED,
                language=language,
                provider_name=self.metadata.name,
                errors=errors,
                parse_time_ms=parse_time_ms,
                file_path=file_path,
            )

        except Exception as e:
            errors.append(
                ParseError(
                    message=f"Parse error: {str(e)}",
                    severity="error",
                )
            )

            parse_time_ms = (time.time() - start_time) * 1000

            return ParseResult(
                status=ParseStatus.FAILED,
                language=language,
                provider_name=self.metadata.name,
                errors=errors,
                parse_time_ms=parse_time_ms,
                file_path=file_path,
            )

    def supports_language(self, language: CodeLanguage) -> bool:
        """Check if provider supports a language."""
        return language == CodeLanguage.PYTHON

    async def validate(self) -> bool:
        """
        Validate provider is ready.

        Always returns True since ast module is stdlib.
        """
        return True

    def extract_dependencies(self, source_code: str, language: CodeLanguage) -> List[str]:
        """
        Extract Python dependencies (imports).
        
        Args:
            source_code: Python source code
            language: Must be CodeLanguage.PYTHON
            
        Returns:
            List of unique import strings
        """
        if language != CodeLanguage.PYTHON:
            return []
            
        try:
            tree = ast.parse(source_code)
            dependencies = set()
            
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        dependencies.add(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        dependencies.add(node.module)
                    # Handle relative imports if needed, but for now we just want the module name
                        
            return sorted(list(dependencies))
        except Exception:
            # Fallback for syntax errors in earlier Python versions or invalid code
            return []

    def _convert_to_universal_ast(self, py_node: ast.AST, file_path: str) -> ASTNode:
        """
        Convert Python AST to universal AST format.

        Args:
            py_node: Python ast.AST node
            file_path: Source file path

        Returns:
            Universal ASTNode
        """
        # Map Python AST node types to universal types
        node_type = self._map_node_type(py_node)

        # Extract node name if available
        name = None
        if hasattr(py_node, "name"):
            name = py_node.name
        elif isinstance(py_node, ast.FunctionDef):
            name = py_node.name
        elif isinstance(py_node, ast.ClassDef):
            name = py_node.name

        # Get source location
        location = None
        if hasattr(py_node, "lineno"):
            location = SourceLocation(
                file_path=file_path,
                start_line=py_node.lineno,
                start_column=getattr(py_node, "col_offset", 0),
                end_line=getattr(py_node, "end_lineno", py_node.lineno),
                end_column=getattr(py_node, "end_col_offset", 0),
            )

        # Extract value for literals
        value = None
        if isinstance(py_node, ast.Constant):
            value = py_node.value

        # Convert children
        children = []
        for _field, field_value in ast.iter_fields(py_node):
            if isinstance(field_value, list):
                for item in field_value:
                    if isinstance(item, ast.AST):
                        children.append(self._convert_to_universal_ast(item, file_path))
            elif isinstance(field_value, ast.AST):
                children.append(self._convert_to_universal_ast(field_value, file_path))

        # Extract additional attributes
        attributes: Dict[str, Any] = {}
        if isinstance(py_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            attributes["async"] = isinstance(py_node, ast.AsyncFunctionDef)
            attributes["decorators"] = [d.id if isinstance(d, ast.Name) else str(d) for d in py_node.decorator_list]
        elif isinstance(py_node, ast.Import):
            attributes["names"] = [alias.name for alias in py_node.names]
        elif isinstance(py_node, ast.ImportFrom):
            attributes["module"] = py_node.module
            attributes["names"] = [alias.name for alias in py_node.names]

        return ASTNode(
            node_type=node_type,
            name=name,
            value=value,
            location=location,
            children=children,
            attributes=attributes,
            raw_node=py_node,
        )

    def _map_node_type(self, py_node: ast.AST) -> ASTNodeType:
        """
        Map Python AST node type to universal node type.

        Args:
            py_node: Python AST node

        Returns:
            Universal ASTNodeType
        """
        node_type_map: Dict[type, ASTNodeType] = {
            ast.Module: ASTNodeType.MODULE,
            ast.ClassDef: ASTNodeType.CLASS,
            ast.FunctionDef: ASTNodeType.FUNCTION,
            ast.AsyncFunctionDef: ASTNodeType.FUNCTION,
            ast.Import: ASTNodeType.IMPORT,
            ast.ImportFrom: ASTNodeType.IMPORT,
            ast.Assign: ASTNodeType.ASSIGNMENT,
            ast.AnnAssign: ASTNodeType.ASSIGNMENT,
            ast.AugAssign: ASTNodeType.ASSIGNMENT,
            ast.Return: ASTNodeType.RETURN_STATEMENT,
            ast.If: ASTNodeType.IF_STATEMENT,
            ast.For: ASTNodeType.LOOP_STATEMENT,
            ast.AsyncFor: ASTNodeType.LOOP_STATEMENT,
            ast.While: ASTNodeType.LOOP_STATEMENT,
            ast.Try: ASTNodeType.TRY_CATCH,
            ast.Raise: ASTNodeType.THROW_STATEMENT,
            ast.Call: ASTNodeType.CALL_EXPRESSION,
            ast.BinOp: ASTNodeType.BINARY_EXPRESSION,
            ast.UnaryOp: ASTNodeType.UNARY_EXPRESSION,
            ast.Constant: ASTNodeType.LITERAL,
            ast.Name: ASTNodeType.IDENTIFIER,
            ast.Attribute: ASTNodeType.MEMBER_ACCESS,
            ast.Subscript: ASTNodeType.ARRAY_ACCESS,
        }

        return node_type_map.get(type(py_node), ASTNodeType.UNKNOWN)
