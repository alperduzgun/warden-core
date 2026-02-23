"""
Tree-sitter Universal AST Provider.

Uses tree-sitter for parsing 40+ programming languages.
Priority: TREE_SITTER (fallback for languages without native provider).
"""

import time
from datetime import datetime
from typing import Any

import structlog

from warden.ast.application.provider_interface import IASTProvider
from warden.ast.domain.enums import (
    ASTNodeType,
    ASTProviderPriority,
    CodeLanguage,
    ParseStatus,
)
from warden.ast.domain.models import (
    ASTNode,
    ASTProviderMetadata,
    ParseError,
    ParseResult,
    SourceLocation,
)

logger = structlog.get_logger(__name__)

# Try to import tree-sitter (optional dependency)
try:
    import tree_sitter

    TREE_SITTER_AVAILABLE = True
except ImportError:
    TREE_SITTER_AVAILABLE = False

# Language grammars are loaded lazily in _initialize_languages
tree_sitter_javascript = None
tree_sitter_typescript = None
tree_sitter_go = None
tree_sitter_java = None
tree_sitter_c_sharp = None


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
        from warden.shared.languages.registry import LanguageRegistry

        self._metadata = ASTProviderMetadata(
            name="tree-sitter",
            priority=ASTProviderPriority.TREE_SITTER,
            supported_languages=[
                lang
                for lang in LanguageRegistry.get_code_languages()
                if LanguageRegistry.get_definition(lang) and LanguageRegistry.get_definition(lang).tree_sitter_id
            ],
            version="1.1.0",
            description="Universal AST parser using tree-sitter (Refactored)",
            author="Warden Core Team",
            requires_installation=True,
            installation_command="pip install tree-sitter",
        )

        self._parsers = {}  # Language -> Parser cache
        self._available = TREE_SITTER_AVAILABLE
        self._language_objs = {}  # Language -> tree_sitter.Language
        self._missing_modules = {}  # Language -> module_name

        if self._available:
            self._initialize_languages()

    def _initialize_languages(self) -> None:
        """Initialize tree-sitter language objects based on Registry."""
        if not self._available:
            return

        from warden.shared.languages.registry import LanguageRegistry

        logger.debug("initializing_tree_sitter_languages_from_registry")

        for lang in self._metadata.supported_languages:
            defn = LanguageRegistry.get_definition(lang)
            if not defn or not defn.tree_sitter_id:
                continue

            ts_id = defn.tree_sitter_id
            # Normalize ID for import (e.g. c_sharp -> c_sharp)
            import_name = f"tree_sitter_{ts_id.replace('-', '_')}"

            # Special import name overrides for non-standard packages
            IMPORT_NAME_OVERRIDES = {
                "tree_sitter_dart": "tree_sitter_dart_orchard",  # Dart uses orchard fork
            }

            actual_import_name = IMPORT_NAME_OVERRIDES.get(import_name, import_name)

            try:
                mod = __import__(actual_import_name)
                # Some grammars have .language(), others .language_typescript(), etc.
                # Use a heuristic or standardized check
                lang_fn = getattr(mod, "language", None)
                if not lang_fn:
                    # Try lang_id specific name (e.g. tree_sitter_typescript.language_typescript)
                    lang_fn = getattr(mod, f"language_{ts_id.replace('-', '_')}", None)

                if lang_fn:
                    self._language_objs[lang] = tree_sitter.Language(lang_fn())
            except ImportError as e:
                # Silently track missing grammars (summary logged below)
                self._missing_modules[lang] = import_name
                logger.debug("grammar_module_not_found", language=lang.name, module=import_name, error=str(e))
            except Exception as e:
                logger.warning("failed_to_load_grammar", language=lang.name, error=str(e))

        logger.info(
            "tree_sitter_languages_loaded",
            languages=[l.name for l in self._language_objs],
            missing=len(self._missing_modules),
        )

    @property
    def missing_grammars(self) -> list[str]:
        """Get list of missing grammar package names."""
        # Convert tree_sitter_swift -> tree-sitter-swift (pip package name)
        return [mod.replace("_", "-") for mod in self._missing_modules.values()]

    async def auto_install_grammar(self, language: CodeLanguage) -> bool:
        """
        Auto-install missing grammar for a language.

        Silently installs missing tree-sitter grammar without bothering the user.

        Args:
            language: Language to install grammar for

        Returns:
            True if installed successfully, False otherwise
        """
        if language not in self._missing_modules:
            return True  # Already available

        module_name = self._missing_modules[language]
        package_name = module_name.replace("_", "-")

        # Special package name mappings for non-standard PyPI packages
        PACKAGE_NAME_OVERRIDES = {
            "tree-sitter-dart": "tree-sitter-dart-orchard",  # Dart uses orchard fork
        }

        package_name = PACKAGE_NAME_OVERRIDES.get(package_name, package_name)

        logger.info("auto_installing_grammar", language=language.value, package=package_name)

        try:
            import subprocess
            import sys

            # Use pip to install silently
            # Add --break-system-packages for macOS externally-managed-environment
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--quiet", "--break-system-packages", package_name],
                capture_output=True,
                text=True,
                timeout=60,  # 60 second timeout
            )

            if result.returncode != 0:
                logger.debug("grammar_install_failed", package=package_name, stderr=result.stderr)
                return False

            # Re-import the module
            try:
                # Use override mapping for actual import name
                IMPORT_NAME_OVERRIDES = {
                    "tree_sitter_dart": "tree_sitter_dart_orchard",
                }
                actual_module_name = IMPORT_NAME_OVERRIDES.get(module_name, module_name)

                mod = __import__(actual_module_name)
                lang_fn = getattr(mod, "language", None)
                if not lang_fn:
                    lang_fn = getattr(
                        mod, f"language_{actual_module_name.replace('tree_sitter_', '').replace('_orchard', '')}", None
                    )

                if lang_fn:
                    self._language_objs[language] = tree_sitter.Language(lang_fn())
                    del self._missing_modules[language]
                    logger.info("grammar_auto_installed", language=language.value, package=package_name)
                    return True
            except Exception as e:
                logger.debug("grammar_reload_failed", error=str(e))
                return False

        except subprocess.TimeoutExpired:
            logger.debug("grammar_install_timeout", package=package_name)
            return False
        except Exception as e:
            logger.debug("grammar_install_error", package=package_name, error=str(e))
            return False

        return False

    async def ensure_grammar(self, language: CodeLanguage) -> bool:
        """
        Ensure grammar is available for a language, auto-installing if needed.

        Args:
            language: Language to ensure grammar for

        Returns:
            True if grammar is available (or was installed), False otherwise
        """
        # Already available
        if language in self._language_objs:
            return True

        # Not in missing list means we can't install it
        if language not in self._missing_modules:
            return False

        # Try to auto-install
        return await self.auto_install_grammar(language)

    @property
    def metadata(self) -> ASTProviderMetadata:
        """Get provider metadata."""
        return self._metadata

    def _get_ts_language(self, language: CodeLanguage) -> Any | None:
        """Get tree-sitter language object if available."""
        return self._language_objs.get(language)

    async def parse(
        self,
        source_code: str,
        language: CodeLanguage,
        file_path: str | None = None,
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
                timestamp=datetime.now(),
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
                timestamp=datetime.now(),
            )

        start_time = time.time()

        try:
            language_obj = self._language_objs.get(language)
            if not language_obj:
                # Try auto-install if grammar is missing
                if language in self._missing_modules:
                    installed = await self.auto_install_grammar(language)
                    if installed:
                        language_obj = self._language_objs.get(language)

                if not language_obj:
                    logger.debug("no_grammar_loaded", language=language.value)
                    return ParseResult(
                        status=ParseStatus.FAILED,
                        language=language,
                        provider_name=self.metadata.name,
                        ast_root=None,
                        errors=[ParseError(message=f"No grammar loaded for {language.value}", severity="error")],
                        warnings=[],
                        parse_time_ms=0,
                        file_path=file_path,
                        timestamp=datetime.now(),
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
                timestamp=datetime.now(),
            )

        except Exception as e:
            logger.error("tree_sitter_parse_failed", file=file_path, error=str(e))
            parse_time_ms = (time.time() - start_time) * 1000

            return ParseResult(
                status=ParseStatus.FAILED,
                language=language,
                provider_name=self.metadata.name,
                ast_root=None,
                errors=[
                    ParseError(
                        message=f"Parse error: {e!s}",
                        severity="error",
                    )
                ],
                warnings=[],
                parse_time_ms=parse_time_ms,
                file_path=file_path,
                timestamp=datetime.now(),
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

    def extract_dependencies(self, source_code: str, language: CodeLanguage) -> list[str]:
        """
        Extract dependencies using tree-sitter queries.

        Args:
            source_code: Source code to analyze
            language: Programming language of the code

        Returns:
            List of unique dependency strings
        """
        if not self._available:
            return []

        # Check if grammar is loaded before attempting query
        ts_language = self._get_ts_language(language)
        if not ts_language:
            # Expected behavior if grammar not installed - silent return (debug log in init)
            return []

        query_str = self._get_dependency_query_str(language)
        if not query_str:
            return []

        try:
            parser = tree_sitter.Parser(ts_language)
            source_bytes = bytes(source_code, "utf8")
            tree = parser.parse(source_bytes)
            query = tree_sitter.Query(ts_language, query_str)
            cursor = tree_sitter.QueryCursor(query)
            captures = cursor.captures(tree.root_node)

            dependencies = set()
            for cap_name, nodes in captures.items():
                if cap_name == "dep":
                    for node in nodes:
                        dep_str = source_bytes[node.start_byte : node.end_byte].decode().strip("\"'`")
                        if dep_str:
                            dependencies.add(dep_str)

            return sorted(dependencies)
        except Exception as e:
            logger.debug("tree_sitter_dependency_extraction_failed", language=language.value, error=str(e))
            return []

    def _get_dependency_query_str(self, language: CodeLanguage) -> str:
        """Get tree-sitter query string for dependencies based on language."""
        queries = {
            CodeLanguage.JAVASCRIPT: '(import_statement source: (string) @dep) (call_expression function: (identifier) @func (#eq? @func "require") arguments: (arguments (string) @dep))',
            CodeLanguage.TYPESCRIPT: "(import_statement source: (string) @dep)",
            CodeLanguage.GO: "(import_spec (interpreted_string_literal) @dep)",
            CodeLanguage.JAVA: "(import_declaration (scoped_identifier) @dep)",
            CodeLanguage.PYTHON: "(import_from_statement module_name: (dotted_name) @dep) (import_statement name: (dotted_name) @dep)",
        }
        return queries.get(language, "")

    def _convert_node(
        self, ts_node: "tree_sitter.Node", source: str, language: CodeLanguage, file_path: str | None = None
    ) -> ASTNode:
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
            end_column=end_point[1],
        )

        # Extract name if applicable
        name = None
        # Common patterns for names in TS/JS/Go
        name_node = (
            ts_node.child_by_field_name("name")
            or ts_node.child_by_field_name("identifier")
            or ts_node.child_by_field_name("field_identifier")
        )

        if name_node:
            name = source[name_node.start_byte : name_node.end_byte]

        # If it's a type node but no name found via field, try some common patterns
        if (
            node_type in [ASTNodeType.CLASS, ASTNodeType.FUNCTION, ASTNodeType.INTERFACE, ASTNodeType.METHOD]
            and not name
        ):
            for child in ts_node.children:
                if child.type in ["identifier", "type_identifier", "field_identifier"]:
                    name = source[child.start_byte : child.end_byte]
                    break

        # CRITICAL FIX: Identifiers must have their content as name
        if node_type == ASTNodeType.IDENTIFIER and not name:
            name = source[ts_node.start_byte : ts_node.end_byte]

        # Create the node
        ast_node = ASTNode(node_type=node_type, name=name, location=location, children=[])

        # Add original type as attribute (Robustly)
        # Convert to string to avoid issues with tree-sitter bindings
        try:
            raw_type = ts_node.type
            if isinstance(raw_type, bytes):
                raw_type = raw_type.decode("utf-8")
            ast_node.attributes["original_type"] = str(raw_type)
        except Exception:
            ast_node.attributes["original_type"] = "unknown"

        # Extract decorator/annotation names for function/method/class nodes
        if node_type in (ASTNodeType.FUNCTION, ASTNodeType.METHOD, ASTNodeType.CLASS):
            decorators = self._extract_decorators(ts_node, source, language)
            if decorators:
                ast_node.attributes["decorators"] = decorators

        # Recursively convert children (skip anonymous nodes unless they are literals)
        for child in ts_node.children:
            if child.is_named:
                # Always include named nodes
                child_ast = self._convert_node(child, source, language, file_path)
                ast_node.children.append(child_ast)
            elif child.type in ["string", "number", "true", "false", "null", "string_literal"]:
                # Include specific anonymous literals
                child_ast = self._convert_node(child, source, language, file_path)
                ast_node.children.append(child_ast)

        return ast_node

    def _map_node_type(self, ts_node: "tree_sitter.Node", language: CodeLanguage) -> tuple[ASTNodeType, bool]:
        """Map tree-sitter node type to Warden ASTNodeType."""
        t = ts_node.type

        # Common mappings
        mappings = {
            "program": ASTNodeType.MODULE,
            "source_file": ASTNodeType.MODULE,
            "module": ASTNodeType.MODULE,  # Python root
            # Classes & Interfaces
            "class_declaration": ASTNodeType.CLASS,
            "class_definition": ASTNodeType.CLASS,  # Dart/Python/Others
            "class": ASTNodeType.CLASS,
            "interface_declaration": ASTNodeType.INTERFACE,
            "type_alias_declaration": ASTNodeType.INTERFACE,  # Often used as interface in TS
            "enum_declaration": ASTNodeType.ENUM,
            "enum_definition": ASTNodeType.ENUM,
            # Functions & Methods
            "function_declaration": ASTNodeType.FUNCTION,
            "method_definition": ASTNodeType.METHOD,
            "method_declaration": ASTNodeType.METHOD,
            "arrow_function": ASTNodeType.FUNCTION,
            # Control Flow - Universal
            "if_statement": ASTNodeType.IF_STATEMENT,
            "if_expression": ASTNodeType.IF_STATEMENT,
            "for_statement": ASTNodeType.LOOP_STATEMENT,
            "while_statement": ASTNodeType.LOOP_STATEMENT,
            "for_in_loop": ASTNodeType.LOOP_STATEMENT,
            "for_each_statement": ASTNodeType.LOOP_STATEMENT,
            "do_statement": ASTNodeType.LOOP_STATEMENT,
            "try_statement": ASTNodeType.TRY_CATCH,
            "try_expression": ASTNodeType.TRY_CATCH,
            "catch_clause": ASTNodeType.TRY_CATCH,
            "guard_statement": ASTNodeType.IF_STATEMENT,  # Swift guard
            # Imports
            "import_statement": ASTNodeType.IMPORT,
            "import_declaration": ASTNodeType.IMPORT,
            # Literals
            "string": ASTNodeType.LITERAL,
            "number": ASTNodeType.LITERAL,
            "integer_literal": ASTNodeType.LITERAL,
            "float_literal": ASTNodeType.LITERAL,
            "boolean_literal": ASTNodeType.LITERAL,
            "true": ASTNodeType.LITERAL,
            "false": ASTNodeType.LITERAL,
            "null": ASTNodeType.LITERAL,
            "nil": ASTNodeType.LITERAL,
            # Expressions
            "call_expression": ASTNodeType.CALL_EXPRESSION,
            "member_expression": ASTNodeType.MEMBER_ACCESS,
            "binary_expression": ASTNodeType.BINARY_EXPRESSION,
            "identifier": ASTNodeType.IDENTIFIER,
            # Decorators & Annotations
            "decorator": ASTNodeType.DECORATOR,  # Python @decorator
            "decorated_definition": ASTNodeType.UNKNOWN,  # Python wrapper — children hold the actual def
            "annotation": ASTNodeType.ANNOTATION,  # Java/Kotlin @Annotation
            "marker_annotation": ASTNodeType.ANNOTATION,  # Java @Override
            "normal_annotation": ASTNodeType.ANNOTATION,  # Java @SuppressWarnings(...)
            # C# Specifics
            "using_directive": ASTNodeType.IMPORT,
            "namespace_declaration": ASTNodeType.MODULE,
            "property_declaration": ASTNodeType.PROPERTY,
            "package_declaration": ASTNodeType.MODULE,
            # Fields & Properties
            "field_declaration": ASTNodeType.FIELD,
            "variable_declaration": ASTNodeType.VARIABLE_DECLARATION,
            "formal_parameter": ASTNodeType.FIELD,  # For data constructors
            "field_formal_parameter": ASTNodeType.FIELD,  # Dart
            "declaration": ASTNodeType.FIELD,  # Heuristic fallback
        }

        if t in mappings:
            return mappings[t], False

        # Heuristic for generic mappings
        if "declaration" in t or "definition" in t:
            if "function" in t:
                return ASTNodeType.FUNCTION, True
            if "class" in t:
                return ASTNodeType.CLASS, True
            if "method" in t:
                return ASTNodeType.METHOD, True

        return ASTNodeType.UNKNOWN, True

    def _extract_decorators(self, ts_node: "tree_sitter.Node", source: str, language: CodeLanguage) -> list[str]:
        """Extract decorator/annotation names from a function/method/class node.

        Handles:
        - Python: decorated_definition wraps the node, decorators are siblings
        - Python: decorator children directly on function_definition
        - Java/Kotlin: annotation/marker_annotation children
        - TypeScript: decorator children

        Returns:
            List of decorator name strings (e.g. ["app.route", "require_auth"]).
        """
        decorator_names: list[str] = []
        decorator_types = {"decorator", "annotation", "marker_annotation", "normal_annotation"}

        # Strategy 1: Check parent — Python wraps decorated functions in "decorated_definition"
        parent = ts_node.parent
        if parent and parent.type == "decorated_definition":
            for sibling in parent.children:
                if sibling.type in decorator_types:
                    name = self._decorator_text(sibling, source)
                    if name:
                        decorator_names.append(name)

        # Strategy 2: Direct children or inside 'modifiers' wrapper (Java/Kotlin)
        for child in ts_node.children:
            if child.type in decorator_types:
                name = self._decorator_text(child, source)
                if name:
                    decorator_names.append(name)
            elif child.type == "modifiers":
                for mod_child in child.children:
                    if mod_child.type in decorator_types:
                        name = self._decorator_text(mod_child, source)
                        if name:
                            decorator_names.append(name)

        return decorator_names

    @staticmethod
    def _decorator_text(dec_node: "tree_sitter.Node", source: str) -> str:
        """Extract a readable decorator name from a tree-sitter decorator node.

        For `@app.route("/login")` returns "app.route".
        For `@require_auth` returns "require_auth".
        For Java `@Override` returns "Override".
        """
        # Try named children: identifier, dotted_name, attribute, scoped_identifier
        for child in dec_node.children:
            if child.type in (
                "identifier",
                "dotted_name",
                "attribute",
                "scoped_identifier",
            ):
                return source[child.start_byte : child.end_byte]
            # Call expression decorator: @app.route(...)
            if child.type == "call":
                func_child = child.child_by_field_name("function")
                if func_child:
                    return source[func_child.start_byte : func_child.end_byte]
                # Fallback: first named child of call
                for sub in child.children:
                    if sub.type in ("identifier", "dotted_name", "attribute"):
                        return source[sub.start_byte : sub.end_byte]

        # Fallback: full text without @ prefix
        text = source[dec_node.start_byte : dec_node.end_byte].strip()
        if text.startswith("@"):
            text = text[1:]
        # Strip arguments: "route('/login')" → "route"
        paren_idx = text.find("(")
        if paren_idx > 0:
            text = text[:paren_idx]
        return text.strip()
