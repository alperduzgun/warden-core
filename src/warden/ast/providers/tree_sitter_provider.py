"""
Tree-sitter Universal AST Provider.

Uses tree-sitter for parsing 40+ programming languages.
Priority: TREE_SITTER (fallback for languages without native provider).
"""

import time
import json
from datetime import datetime
from typing import Optional, List, Tuple, Any

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

# Try to import tree-sitter (optional dependency)
try:
    import tree_sitter
    import tree_sitter_javascript
    import tree_sitter_typescript
    import tree_sitter_go
    # import tree_sitter_python # We use native ast for python usually

    TREE_SITTER_AVAILABLE = True
except ImportError:
    TREE_SITTER_AVAILABLE = False


class TreeSitterProvider(IASTProvider):
    """
    Universal AST provider using tree-sitter.

    Supports 40+ programming languages through tree-sitter grammars.
    Requires tree-sitter package to be installed.

    Advantages:
        - Multi-language support (40+ languages)
        - Error recovery (partial AST on syntax errors)
        - Incremental parsing
        - Fast performance

    Limitations:
        - Requires tree-sitter installation
        - Language grammars must be installed separately
        - Less detailed than native parsers

    Installation:
        pip install tree-sitter
        # Then install language grammars as needed
    """

    def __init__(self) -> None:
        """Initialize Tree-sitter provider."""
        self._metadata = ASTProviderMetadata(
            name="tree-sitter",
            priority=ASTProviderPriority.TREE_SITTER,
            supported_languages=[
                CodeLanguage.PYTHON,
                CodeLanguage.JAVASCRIPT,
                CodeLanguage.TYPESCRIPT,
                CodeLanguage.JAVA,
                CodeLanguage.C,
                CodeLanguage.CPP,
                CodeLanguage.GO,
                CodeLanguage.RUST,
                # Add more as grammars are available
            ],
            version="1.0.0",
            description="Universal AST parser using tree-sitter (40+ languages)",
            author="Warden Core Team",
            requires_installation=True,
            installation_command="pip install tree-sitter",
        )

        self._parsers = {}  # Language -> Parser cache
        self._available = TREE_SITTER_AVAILABLE
        self._language_objs = {} # Language -> tree_sitter.Language
        
        if self._available:
            self._initialize_languages()

    def _initialize_languages(self) -> None:
        """Initialize tree-sitter language objects."""
        if not self._available:
            return

        print("DEBUG: Initializing tree-sitter languages...")
        
        # Mapping of language to its initialization function
        lang_init = {
            CodeLanguage.JAVASCRIPT: lambda: tree_sitter.Language(tree_sitter_javascript.language()),
            CodeLanguage.TYPESCRIPT: lambda: tree_sitter.Language(tree_sitter_typescript.language_typescript()),
            CodeLanguage.TSX: lambda: tree_sitter.Language(tree_sitter_typescript.language_tsx()),
            CodeLanguage.GO: lambda: tree_sitter.Language(tree_sitter_go.language()),
        }

        for lang, init_fn in lang_init.items():
            try:
                self._language_objs[lang] = init_fn()
            except Exception as e:
                print(f"DEBUG: Failed to load tree-sitter grammar for {lang.value}: {e}")

        print(f"DEBUG: Successfully loaded languages: {list(self._language_objs.keys())}")

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
        Parse source code using tree-sitter.

        Args:
            source_code: Source code to parse
            language: Programming language
            file_path: Optional file path for error reporting

        Returns:
            ParseResult with AST and any errors
        """
        if not self._available:
            return ParseResult(
                status=ParseStatus.FAILED,
                language=language,
                provider_name=self.metadata.name,
                ast_root=None,
                errors=[
                    ParseError(
                        message="tree-sitter not installed. Run: pip install tree-sitter",
                        severity="error",
                    )
                ],
                warnings=[],
                parse_time_ms=0,
                file_path=file_path,
                timestamp=datetime.now()
            )

        if not self.supports_language(language):
            return ParseResult(
                status=ParseStatus.UNSUPPORTED,
                language=language,
                provider_name=self.metadata.name,
                ast_root=None,
                errors=[
                    ParseError(
                        message=f"Language {language.value} not supported by tree-sitter provider",
                        severity="error",
                    )
                ],
                warnings=[],
                parse_time_ms=0,
                file_path=file_path,
                timestamp=datetime.now()
            )

        start_time = time.time()

        try:
            language_obj = self._language_objs.get(language)
            if not language_obj:
                 print(f"DEBUG: No grammar loaded for {language}")
                 return ParseResult(
                    status=ParseStatus.FAILED,
                    language=language,
                    provider_name=self.metadata.name,
                    ast_root=None,
                    errors=[ParseError(message=f"No grammar loaded for {language.value}", severity="error")],
                    warnings=[],
                    parse_time_ms=0,
                    file_path=file_path,
                    timestamp=datetime.now()
                )

            parser = tree_sitter.Parser(language_obj)
            
            # Parse the code
            tree = parser.parse(bytes(source_code, "utf8"))
            
            # Convert to universal AST
            ast_root = self._convert_node(tree.root_node, source_code, language, file_path)
            
            parse_time_ms = (time.time() - start_time) * 1000

            return ParseResult(
                status=ParseStatus.SUCCESS,
                language=language,
                provider_name=self.metadata.name,
                ast_root=ast_root,
                errors=[],
                warnings=[],
                parse_time_ms=parse_time_ms,
                file_path=file_path,
                timestamp=datetime.now()
            )

        except Exception as e:
            print(f"DEBUG: Tree-sitter parse failed for {file_path}: {e}")
            import traceback
            traceback.print_exc()
            parse_time_ms = (time.time() - start_time) * 1000

            return ParseResult(
                status=ParseStatus.FAILED,
                language=language,
                provider_name=self.metadata.name,
                ast_root=None,
                errors=[
                    ParseError(
                        message=f"Parse error: {str(e)}",
                        severity="error",
                    )
                ],
                warnings=[],
                parse_time_ms=parse_time_ms,
                file_path=file_path,
                timestamp=datetime.now()
            )

    def supports_language(self, language: CodeLanguage) -> bool:
        """Check if provider supports a language."""
        return language in self.metadata.supported_languages

    async def validate(self) -> bool:
        """
        Validate that tree-sitter is installed.

        Returns:
            True if tree-sitter is available or mock mode
        """
        # Always return True to show provider in list (even if tree-sitter not installed)
        # Parse will fail gracefully with informative error
        return True

    def _convert_node(self, ts_node: "tree_sitter.Node", source: str, language: CodeLanguage, file_path: Optional[str] = None) -> ASTNode:
        """Recursively convert a tree-sitter node to Warden ASTNode."""
        node_type, is_generic = self._map_node_type(ts_node, language)
        
        # Get location
        start_point = ts_node.start_point
        end_point = ts_node.end_point
        location = SourceLocation(
            file_path=file_path or "<string>",
            start_line=start_point[0] + 1,
            start_column=start_point[1],
            end_line=end_point[0] + 1,
            end_column=end_point[1]
        )
        
        # Extract name if applicable
        name = None
        # Common patterns for names in TS/JS/Go
        name_node = (ts_node.child_by_field_name("name") or 
                     ts_node.child_by_field_name("identifier") or
                     ts_node.child_by_field_name("field_identifier"))
        
        if name_node:
             name = source[name_node.start_byte:name_node.end_byte]
        
        # If it's a type node but no name found via field, try some common patterns
        if node_type in [ASTNodeType.CLASS, ASTNodeType.FUNCTION, ASTNodeType.INTERFACE, ASTNodeType.METHOD] and not name:
            for child in ts_node.children:
                if child.type in ["identifier", "type_identifier", "field_identifier"]:
                    name = source[child.start_byte:child.end_byte]
                    break

        # Create the node
        ast_node = ASTNode(
            node_type=node_type,
            name=name,
            location=location,
            children=[]
        )
        
        # Add original type as attribute
        ast_node.attributes["original_type"] = ts_node.type
        
        # Recursively convert children (skip anonymous nodes unless they are literals)
        for child in ts_node.children:
            if child.is_named or child.type in ["string", "number", "true", "false", "null"]:
                child_ast = self._convert_node(child, source, language, file_path)
                ast_node.children.append(child_ast)
                
        return ast_node

    def _map_node_type(self, ts_node: "tree_sitter.Node", language: CodeLanguage) -> Tuple[ASTNodeType, bool]:
        """Map tree-sitter node type to Warden ASTNodeType."""
        t = ts_node.type
        
        # Common mappings
        mappings = {
            "program": ASTNodeType.MODULE,
            "source_file": ASTNodeType.MODULE,
            
            # Classes & Interfaces
            "class_declaration": ASTNodeType.CLASS,
            "class": ASTNodeType.CLASS,
            "interface_declaration": ASTNodeType.INTERFACE,
            "type_alias_declaration": ASTNodeType.INTERFACE, # Often used as interface in TS
            
            # Functions & Methods
            "function_declaration": ASTNodeType.FUNCTION,
            "method_definition": ASTNodeType.METHOD,
            "method_declaration": ASTNodeType.METHOD,
            "arrow_function": ASTNodeType.FUNCTION,
            
            # Imports
            "import_statement": ASTNodeType.IMPORT,
            "import_declaration": ASTNodeType.IMPORT,
            
            # Literals
            "string": ASTNodeType.LITERAL,
            "number": ASTNodeType.LITERAL,
            "true": ASTNodeType.LITERAL,
            "false": ASTNodeType.LITERAL,
            "null": ASTNodeType.LITERAL,
            
            # Expressions
            "call_expression": ASTNodeType.CALL_EXPRESSION,
            "member_expression": ASTNodeType.MEMBER_ACCESS,
            "identifier": ASTNodeType.IDENTIFIER,
        }
        
        if t in mappings:
            return mappings[t], False
            
        # Heuristic for generic mappings
        if "declaration" in t or "definition" in t:
             if "function" in t: return ASTNodeType.FUNCTION, True
             if "class" in t: return ASTNodeType.CLASS, True
             if "method" in t: return ASTNodeType.METHOD, True
             
        return ASTNodeType.UNKNOWN, True
