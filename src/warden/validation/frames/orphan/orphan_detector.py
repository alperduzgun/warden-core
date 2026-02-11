"""
Orphan Code Detector - Strategy Pattern for Multi-Language Support.

Defines the interface for orphan detection and concrete implementations
for supported languages.

Strategies (in priority order):
1. LSPOrphanDetector - Cross-file semantic analysis via LSP (most accurate)
2. RustOrphanDetector - Fast single-file analysis via Rust+Tree-sitter
3. PythonOrphanDetector - Native AST for Python
4. UniversalOrphanDetector - Tree-sitter based for other languages
"""

import abc
import ast
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

import structlog

from warden.ast.application.provider_registry import ASTProviderRegistry
from warden.ast.domain.enums import ASTNodeType, CodeLanguage
from warden.ast.domain.models import ASTNode

# Try to import Rust extension
try:
    from warden import warden_core_rust
except ImportError:
    warden_core_rust = None

# LSP availability flag (checked at runtime)
LSP_AVAILABLE = False
try:
    from warden.lsp.manager import LSPManager
    LSP_AVAILABLE = True
except ImportError:
    pass

logger = structlog.get_logger(__name__)


@dataclass
class OrphanFinding:
    """Single orphan code finding."""

    orphan_type: str  # 'unused_import' | 'unreferenced_function' | 'dead_code'
    name: str  # Name of the orphan (import/function/class)
    line_number: int
    code_snippet: str
    reason: str


class AbstractOrphanDetector(abc.ABC):
    """
    Abstract base class for orphan code detectors.
    """

    def __init__(self, code: str, file_path: str) -> None:
        """
        Initialize detector.

        Args:
            code: Source code to analyze
            file_path: Path to the file (for context)
        """
        self.code = code
        self.file_path = file_path
        self.lines = code.split("\n")

    @abc.abstractmethod
    def detect_all(self) -> list[OrphanFinding]:
        """
        Detect all orphan code issues.

        Returns:
            List of OrphanFinding objects
        """
        pass

    def _get_line(self, line_num: int) -> str:
        """
        Get source code line by line number.

        Args:
            line_num: Line number (1-indexed)

        Returns:
            Source code line (stripped)
        """
        if 1 <= line_num <= len(self.lines):
            return self.lines[line_num - 1].strip()
        return ""


class PythonOrphanDetector(AbstractOrphanDetector):
    """
    Python-specific orphan detector using native AST.
    """

    def __init__(self, code: str, file_path: str) -> None:
        super().__init__(code, file_path)

        # Parse AST
        try:
            self.tree = ast.parse(code)
        except SyntaxError:
            self.tree = None  # Invalid syntax - can't analyze

    def detect_all(self) -> list[OrphanFinding]:
        """
        Detect all orphan code issues using Python AST.
        """
        if self.tree is None:
            return []  # Can't analyze invalid syntax

        findings: list[OrphanFinding] = []

        # Detect unused imports
        findings.extend(self.detect_unused_imports())

        # Detect unreferenced functions/classes
        findings.extend(self.detect_unreferenced_definitions())

        # Detect dead code
        findings.extend(self.detect_dead_code())

        return findings

    def detect_unused_imports(self) -> list[OrphanFinding]:
        """Detect unused imports."""
        if self.tree is None:
            return []

        findings: list[OrphanFinding] = []

        # Find TYPE_CHECKING blocks (imports there are for type hints only)
        type_checking_lines: set[int] = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.If):
                test = node.test
                # Check for `if TYPE_CHECKING:` or `if typing.TYPE_CHECKING:`
                is_type_checking = False
                if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING" or isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING":
                    is_type_checking = True

                if is_type_checking:
                    # Mark all lines in the body as type checking imports
                    for stmt in node.body:
                        for child in ast.walk(stmt):
                            if hasattr(child, 'lineno'):
                                type_checking_lines.add(child.lineno)

        # Collect all imports (excluding TYPE_CHECKING blocks)
        imports: dict[str, tuple[int, str]] = {}  # name -> (line_num, full_import)

        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                # Skip if inside TYPE_CHECKING block
                if node.lineno in type_checking_lines:
                    continue
                for alias in node.names:
                    import_name = alias.asname if alias.asname else alias.name
                    line_num = node.lineno
                    imports[import_name] = (line_num, f"import {alias.name}")

            elif isinstance(node, ast.ImportFrom):
                # Skip if inside TYPE_CHECKING block
                if node.lineno in type_checking_lines:
                    continue
                module = node.module or ""
                for alias in node.names:
                    if alias.name == "*":
                        continue  # Can't track wildcard imports
                    import_name = alias.asname if alias.asname else alias.name
                    line_num = node.lineno
                    imports[import_name] = (
                        line_num,
                        f"from {module} import {alias.name}",
                    )

        # Extract __all__ list if present (for re-export detection)
        all_exports: set[str] = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "__all__":
                        if isinstance(node.value, ast.List):
                            for elt in node.value.elts:
                                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                    all_exports.add(elt.value)
                                elif isinstance(elt, ast.Str):  # Python 3.7 compat
                                    all_exports.add(elt.s)

        # Collect all name references (excluding import statements)
        references: set[str] = set()

        for node in ast.walk(self.tree):
            # Skip import nodes
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                continue

            # Collect Name references
            if isinstance(node, ast.Name):
                references.add(node.id)

            # Collect attribute references (e.g., module.function)
            elif isinstance(node, ast.Attribute):
                # Get the base name (e.g., 'os' in 'os.path.join')
                base = node.value
                while isinstance(base, ast.Attribute):
                    base = base.value
                if isinstance(base, ast.Name):
                    references.add(base.id)

        # Find unused imports (but skip if in __all__ - they're re-exports)
        for import_name, (line_num, _import_stmt) in imports.items():
            # Skip if name is in __all__ (re-exported)
            if import_name in all_exports:
                continue

            if import_name not in references:
                code_snippet = self._get_line(line_num)
                findings.append(
                    OrphanFinding(
                        orphan_type="unused_import",
                        name=import_name,
                        line_number=line_num,
                        code_snippet=code_snippet,
                        reason=f"Import '{import_name}' is never used in the code",
                    )
                )

        return findings

    def detect_unreferenced_definitions(self) -> list[OrphanFinding]:
        """Detect unreferenced functions and classes."""
        if self.tree is None:
            return []

        findings: list[OrphanFinding] = []

        # Collect all function/class definitions
        definitions: dict[str, tuple[int, str, str, ast.AST]] = {}  # name -> (line, type, code, node)

        for node in ast.walk(self.tree):
            if isinstance(node, ast.FunctionDef):
                line_num = node.lineno
                definitions[node.name] = (line_num, "function", f"def {node.name}", node)

            elif isinstance(node, ast.ClassDef):
                line_num = node.lineno
                definitions[node.name] = (line_num, "class", f"class {node.name}", node)

        # Collect all name references (excluding the definitions themselves)
        references: set[str] = set()

        class ReferenceCollector(ast.NodeVisitor):
            def __init__(self) -> None:
                self.refs: set[str] = set()
                self.in_definition = False
                self.current_def_name = ""

            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                old_in_def = self.in_definition
                old_def_name = self.current_def_name
                self.in_definition = True
                self.current_def_name = node.name
                self.generic_visit(node)
                self.in_definition = old_in_def
                self.current_def_name = old_def_name

            def visit_ClassDef(self, node: ast.ClassDef) -> None:
                old_in_def = self.in_definition
                old_def_name = self.current_def_name
                self.in_definition = True
                self.current_def_name = node.name
                self.generic_visit(node)
                self.in_definition = old_in_def
                self.current_def_name = old_def_name

            def visit_Name(self, node: ast.Name) -> None:
                # Don't count the definition itself
                if not (self.in_definition and node.id == self.current_def_name):
                    self.refs.add(node.id)
                self.generic_visit(node)

        collector = ReferenceCollector()
        collector.visit(self.tree)
        references = collector.refs

        # Find unreferenced definitions
        for def_name, (line_num, def_type, _def_code, node) in definitions.items():
            if def_name not in references:
                # Check if it's a special method/function (skip those)
                if def_name in ["main", "__init__", "__str__", "__repr__"]:
                    continue

                # Get accurate snippet including decorators
                code_snippet = self._get_definition_snippet(node)

                findings.append(
                    OrphanFinding(
                        orphan_type=f"unreferenced_{def_type}",
                        name=def_name,
                        line_number=line_num,
                        code_snippet=code_snippet,
                        reason=f"{def_type.capitalize()} '{def_name}' is defined but never called",
                    )
                )

        return findings

    def _get_definition_snippet(self, node: ast.AST) -> str:
        """
        Get full definition snippet including decorators.
        """
        if not hasattr(node, 'lineno'):
            return ""

        start_line = node.lineno
        end_line = getattr(node, 'end_lineno', start_line)

        # Include decorators if present
        if hasattr(node, 'decorator_list') and node.decorator_list:
            # Find the earliest line among decorators
            for dec in node.decorator_list:
                if hasattr(dec, 'lineno'):
                    start_line = min(start_line, dec.lineno)

        lines = []
        # Get lines from start_line to end_line (or limit to 20 lines)
        max_lines = 20
        current_line = start_line

        while current_line <= len(self.lines) and len(lines) < max_lines:
            line = self.lines[current_line - 1] # 0-indexed list
            lines.append(line)

            # Stop if we reach the end of the node
            if end_line and current_line >= end_line:
                break

            current_line += 1

        return "\n".join(lines).strip()

    def detect_dead_code(self) -> list[OrphanFinding]:
        """Detect dead code (unreachable statements)."""
        if self.tree is None:
            return []

        findings: list[OrphanFinding] = []

        class DeadCodeFinder(ast.NodeVisitor):
            def __init__(self, detector: "PythonOrphanDetector") -> None:
                self.findings: list[OrphanFinding] = []
                self.detector = detector

            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                """Check function body for dead code."""
                self._check_block(node.body)
                self.generic_visit(node)

            def visit_For(self, node: ast.For) -> None:
                """Check for loop body for dead code."""
                self._check_block(node.body)
                self._check_block(node.orelse)
                self.generic_visit(node)

            def visit_While(self, node: ast.While) -> None:
                """Check while loop body for dead code."""
                self._check_block(node.body)
                self._check_block(node.orelse)
                self.generic_visit(node)

            def visit_If(self, node: ast.If) -> None:
                """Check if statement branches for dead code."""
                self._check_block(node.body)
                self._check_block(node.orelse)
                self.generic_visit(node)

            def _check_block(self, statements: list[ast.stmt]) -> None:
                """
                Check a block of statements for dead code.
                """
                found_terminal = False
                terminal_line = 0

                for i, stmt in enumerate(statements):
                    # Check if this is a terminal statement
                    if self._is_terminal(stmt):
                        found_terminal = True
                        terminal_line = stmt.lineno

                    # If we found terminal and there are more statements
                    elif found_terminal and i > 0:
                        # This is dead code
                        line_num = stmt.lineno
                        code_snippet = self.detector._get_line(line_num)

                        self.findings.append(
                            OrphanFinding(
                                orphan_type="dead_code",
                                name="unreachable_statement",
                                line_number=line_num,
                                code_snippet=code_snippet,
                                reason=f"Unreachable code after terminal statement at line {terminal_line}",
                            )
                        )

                        # Only report the first dead statement in a block
                        break

            def _is_terminal(self, stmt: ast.stmt) -> bool:
                """Check if statement terminates execution."""
                return isinstance(
                    stmt, (ast.Return, ast.Break, ast.Continue, ast.Raise)
                )

        finder = DeadCodeFinder(self)
        finder.visit(self.tree)
        findings.extend(finder.findings)

        return findings



class UniversalOrphanDetector(AbstractOrphanDetector):
    """
    Language-agnostic orphan detector using Warden's Universal AST (ASTNode).
    """

    def __init__(self, code: str, file_path: str, ast_root: ASTNode) -> None:
        super().__init__(code, file_path)
        self.ast_root = ast_root

    def detect_all(self) -> list[OrphanFinding]:
        """
        Detect all orphan code issues using Universal AST.
        """
        findings: list[OrphanFinding] = []

        # 1. Collect all definitions (functions, classes, interfaces)
        definitions = self._collect_definitions(self.ast_root)

        # 2. Collect node IDs to exclude (definition sites) - using id() since ASTNode isn't hashable
        exclude_node_ids = {
            id(node) for _, (_, _, node) in definitions.items()
        }

        # 3. Collect all identifier references
        references = self._collect_references(self.ast_root, exclude_node_ids=exclude_node_ids)

        # 4. Find unreferenced definitions
        for name, (line_num, def_type, node) in definitions.items():
            if name not in references:
                # Check for skipped patterns (exported, main, etc.)
                if self._should_skip(name, node):
                    continue

                code_snippet = self._get_node_snippet(node)
                findings.append(
                    OrphanFinding(
                        orphan_type=f"unreferenced_{def_type.lower()}",
                        name=name,
                        line_number=line_num,
                        code_snippet=code_snippet,
                        reason=f"{def_type} '{name}' appears unused in this file",
                    )
                )

        return findings

    def _collect_definitions(self, root: ASTNode) -> dict[str, tuple[int, str, ASTNode]]:
        """
        Collect function, class, and interface definitions.
        """
        definitions: dict[str, tuple[int, str, ASTNode]] = {}

        # Types we consider as "definitions" that can be orphans
        target_types = {
            ASTNodeType.FUNCTION,
            ASTNodeType.CLASS,
            ASTNodeType.INTERFACE,
            ASTNodeType.METHOD
        }

        def walk(node: ASTNode):
            if node.node_type in target_types:
                name = node.name
                if name and not name.startswith("_"):
                    definitions[name] = (
                        node.location.start_line if node.location else 0,
                        node.node_type.value.capitalize(),
                        node
                    )

            for child in node.children:
                walk(child)

        walk(root)
        return definitions

    def _collect_references(self, root: ASTNode, exclude_node_ids: set[int]) -> set[str]:
        """
        Collect all identifier references, excluding definition sites.
        """
        references: set[str] = set()

        def is_excluded(node: ASTNode) -> bool:
            # Check if this node's id is in the exclusion set
            return id(node) in exclude_node_ids

        def walk(node: ASTNode):
            if is_excluded(node):
                return

            if node.node_type == ASTNodeType.IDENTIFIER and node.name:
                references.add(node.name)

            for child in node.children:
                walk(child)

        walk(root)
        return references

    def _should_skip(self, name: str, node: ASTNode) -> bool:
        """
        Check if definition should be skipped (e.g., main, exported).
        """
        skip_names = {"main", "init", "setup", "teardown", "constructor"}
        if name.lower() in skip_names:
            return True

        # In many languages (TS, Go), anything exported is effectively "used"
        # We check metadata if available (use getattr for safety)
        metadata = getattr(node, 'metadata', None) or {}
        return bool(isinstance(metadata, dict) and metadata.get("is_exported"))

    def _get_node_snippet(self, node: ASTNode) -> str:
        """
        Extract code snippet from source for a node.
        """
        if not node.location:
            return ""

        start = node.location.start_line - 1
        end = min(node.location.end_line, start + 5)

        lines = self.lines[start:end]
        return "\n".join(lines).strip()



class TreeSitterOrphanDetector(AbstractOrphanDetector):
    # [DEPRECATED] Internal tree-sitter logic moved to TreeSitterProvider
    pass


class RustOrphanDetector(AbstractOrphanDetector):
    """
    High-performance orphan detector using Rust + Tree-sitter.

    Delegates parsing and extraction to the Rust extension (warden_core_rust).
    """

    def detect_all(self) -> list[OrphanFinding]:
        if not warden_core_rust:
            logger.warning("rust_orhan_detector_unavailable", reason="Extension not loaded")
            return []

        findings: list[OrphanFinding] = []

        # Use central Registry for language ID
        from warden.shared.languages.registry import LanguageRegistry
        lang_enum = LanguageRegistry.get_language_from_path(self.file_path)
        language = lang_enum.value if lang_enum != CodeLanguage.UNKNOWN else None

        if not language:
            return []

        try:
            # 1. Get Metadata (Definitions + References) from Rust
            meta = warden_core_rust.get_ast_metadata(self.code, language)

            # 2. Convert reference list to counts for fast lookup
            # This is a heuristic: "If name appears <= 1 time, it might be unused"
            # (1 time = the definition itself).
            from collections import Counter
            ref_counts = Counter(meta.references)

            # 3. Check Functions
            for func in meta.functions:
                if self._is_orphan(func.name, ref_counts):
                     # Double check specific suppression (e.g. main)
                    if self._should_skip(func.name):
                        continue

                    findings.append(OrphanFinding(
                        orphan_type="unreferenced_function",
                        name=func.name,
                        line_number=func.line_number,
                        code_snippet=func.code_snippet,
                        reason=f"Function '{func.name}' appears unused (ref_count={ref_counts[func.name]})"
                    ))

            # 4. Check Classes
            for cls in meta.classes:
                if self._is_orphan(cls.name, ref_counts):
                    findings.append(OrphanFinding(
                        orphan_type="unreferenced_class",
                        name=cls.name,
                        line_number=cls.line_number,
                        code_snippet=cls.code_snippet,
                        reason=f"Class '{cls.name}' appears unused (ref_count={ref_counts[cls.name]})"
                    ))

            # 5. Check Imports
            # Imports are tricky because "references" captures ALL identifiers.
            # If I import "foo", and use "foo", ref_count will be 2 (import + usage).
            # If I import "foo" and DON'T use it, ref_count is 1 (import only).
            # Limitation: Re-exports in __init__.py might be flagged if not careful.
            for imp in meta.imports:
                # Import names can be "os" or "join" (from os.path).
                # Tree-sitter query captures the local name.
                if self._is_orphan(imp.name, ref_counts):
                     findings.append(OrphanFinding(
                        orphan_type="unused_import",
                        name=imp.name,
                        line_number=imp.line_number,
                        code_snippet=imp.code_snippet,
                        reason=f"Import '{imp.name}' appears unused"
                    ))

        except Exception as e:
            logger.error("rust_orphan_detection_failed", file=self.file_path, error=str(e))

        return findings

    def _is_orphan(self, name: str, ref_counts: dict[str, int]) -> bool:
        """
        Check if a name is likely an orphan.
        Heuristic: If count <= 1, it's unused (only the definition/import site).
        """
        # If name is not in references (shouldn't happen if query is correct)
        count = ref_counts.get(name, 0)
        return count <= 1

    def _should_skip(self, name: str) -> bool:
        return name in ["main", "__init__", "__str__", "__repr__", "setup", "teardown"]


class LSPOrphanDetector(AbstractOrphanDetector):
    """
    LSP-powered orphan detector for cross-file reference analysis.

    Uses Language Server Protocol to find actual references across the codebase.
    More accurate than AST-based detection but requires LSP server.

    Advantages:
        - Cross-file reference detection (not just single file)
        - Semantic understanding (understands imports, re-exports)
        - Works with any LSP-supported language

    Limitations:
        - Requires LSP server to be installed and running
        - Slower than AST-based detection (needs to index project)
    """

    def __init__(
        self,
        code: str,
        file_path: str,
        lsp_client: 'LanguageServerClient',
        language: str
    ) -> None:
        super().__init__(code, file_path)
        self.lsp_client = lsp_client
        self.language = language
        self._symbols_cache: list[dict] | None = None

    def detect_all(self) -> list[OrphanFinding]:
        """
        Detect orphans using LSP - requires async wrapper.

        Note: This is a sync interface but LSP is async.
        Use detect_all_async() for proper async usage.
        """
        # For sync interface compatibility, return empty
        # Real detection happens in detect_all_async
        logger.warning("lsp_orphan_detector_sync_call", hint="use detect_all_async")
        return []

    async def detect_all_async(self) -> list[OrphanFinding]:
        """
        Detect all orphan code using LSP references.

        Strategy:
        1. Open document in LSP
        2. Get all symbols (functions, classes)
        3. For each symbol, find references
        4. If ref_count <= 1 (only definition), it's orphan
        """
        findings: list[OrphanFinding] = []

        try:
            # 1. Open document
            await self.lsp_client.open_document_async(
                self.file_path,
                self.language,
                self.code
            )

            # 2. Get symbols
            symbols = await self.lsp_client.get_document_symbols_async(self.file_path)
            if not symbols:
                logger.debug("lsp_no_symbols_found", file=self.file_path)
                return []

            # 3. Check each symbol for references
            for symbol in self._flatten_symbols(symbols):
                symbol_name = symbol.get("name", "")
                symbol_kind = symbol.get("kind", 0)

                # Skip non-function/class symbols
                if symbol_kind not in [6, 12, 5]:  # 6=Method, 12=Function, 5=Class
                    continue

                # Skip special methods
                if self._should_skip(symbol_name):
                    continue

                # Get position from symbol
                location = symbol.get("selectionRange") or symbol.get("location", {}).get("range", {})
                start = location.get("start", {})
                line = start.get("line", 0)
                character = start.get("character", 0)

                # 4. Find references
                refs = await self.lsp_client.find_references_async(
                    self.file_path,
                    line,
                    character,
                    include_declaration=False  # Don't count definition itself
                )

                # 5. If no references (excluding declaration), it's orphan
                if len(refs) == 0:
                    orphan_type = self._get_orphan_type(symbol_kind)
                    findings.append(OrphanFinding(
                        orphan_type=orphan_type,
                        name=symbol_name,
                        line_number=line + 1,  # Convert to 1-indexed
                        code_snippet=self._get_line(line + 1),
                        reason=f"{orphan_type.replace('_', ' ').title()} '{symbol_name}' has no references in codebase"
                    ))

            logger.info(
                "lsp_orphan_detection_complete",
                file=self.file_path,
                symbols_checked=len(symbols),
                orphans_found=len(findings)
            )

        except Exception as e:
            logger.error("lsp_orphan_detection_failed", file=self.file_path, error=str(e))

        finally:
            # Close document
            try:
                await self.lsp_client.close_document_async(self.file_path)
            except (ValueError, TypeError, AttributeError):  # AST operation may fail
                pass

        return findings

    def _flatten_symbols(self, symbols: list[dict]) -> list[dict]:
        """Flatten nested DocumentSymbol structure."""
        result = []
        for symbol in symbols:
            result.append(symbol)
            # DocumentSymbol has nested children
            children = symbol.get("children", [])
            if children:
                result.extend(self._flatten_symbols(children))
        return result

    def _get_orphan_type(self, symbol_kind: int) -> str:
        """Convert LSP SymbolKind to orphan type."""
        # LSP SymbolKind: 5=Class, 6=Method, 12=Function
        if symbol_kind == 5:
            return "unreferenced_class"
        elif symbol_kind in [6, 12]:
            return "unreferenced_function"
        return "unreferenced_symbol"

    def _should_skip(self, name: str) -> bool:
        """Skip special methods and entry points."""
        skip_names = {
            "main", "__init__", "__str__", "__repr__", "__eq__", "__hash__",
            "__enter__", "__exit__", "__aenter__", "__aexit__",
            "setup", "teardown", "setUp", "tearDown",
        }
        return name in skip_names or name.startswith("test_")


# Type hint for LSP client (avoid circular import)
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from warden.lsp.client import LanguageServerClient


class OrphanDetectorFactory:
    """
    Factory for creating the appropriate OrphanDetector strategy.

    Selection Logic (priority order):
    1. LSP (if available) - Cross-file semantic analysis
    2. Rust+Tree-sitter (if available) - Fast single-file analysis
    3. Python Native AST (for Python files)
    4. Universal AST via TreeSitterProvider (fallback)
    5. None (Unsupported language)

    Config Options:
        use_lsp: bool - Enable LSP-based detection (default: False for speed)
        project_root: str - Project root for LSP initialization
    """

    # Language to LSP language ID mapping
    LANGUAGE_ID_MAP: dict[str, str] = {
        ".py": "python",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".js": "javascript",
        ".jsx": "javascript",
        ".rs": "rust",
        ".go": "go",
    }

    @staticmethod
    async def create_detector(
        code: str,
        file_path: str,
        use_lsp: bool = False,
        project_root: str | None = None
    ) -> AbstractOrphanDetector | None:
        """
        Create detector instance based on file type and available backends.

        Args:
            code: Source code content
            file_path: Path to the file
            use_lsp: Enable LSP for cross-file analysis (slower but more accurate)
            project_root: Project root for LSP (required if use_lsp=True)

        Returns:
            Appropriate OrphanDetector or None if unsupported
        """
        _, ext = os.path.splitext(file_path)
        ext = ext.lower()

        # 1. Try LSP if enabled and available
        if use_lsp and LSP_AVAILABLE and project_root:
            lsp_detector = await OrphanDetectorFactory._try_create_lsp_detector(
                code, file_path, ext, project_root
            )
            if lsp_detector:
                return lsp_detector

        # 2. Python-specific handling
        if ext == ".py":
            # Prefer Rust if available for speed
            if warden_core_rust:
                return RustOrphanDetector(code, file_path)
            return PythonOrphanDetector(code, file_path)

        # 3. Non-Python uses Rust or Universal AST
        try:
            from warden.shared.languages.registry import LanguageRegistry
            language = LanguageRegistry.get_language_from_path(file_path)

            if language != CodeLanguage.UNKNOWN:
                # Prefer Rust for supported languages
                if warden_core_rust and language in [
                    CodeLanguage.TYPESCRIPT,
                    CodeLanguage.JAVASCRIPT,
                    CodeLanguage.GO,
                    CodeLanguage.JAVA
                ]:
                    return RustOrphanDetector(code, file_path)

                # Fallback to Universal AST
                registry = ASTProviderRegistry()
                provider = registry.get_provider(language)
                if provider:
                    parse_result = await provider.parse(code, language, file_path)
                    if parse_result.ast_root:
                        return UniversalOrphanDetector(code, file_path, parse_result.ast_root)

        except Exception as e:
            logger.warning("factory_universal_detector_failed", file=file_path, error=str(e))

        return None

    @staticmethod
    async def _try_create_lsp_detector(
        code: str,
        file_path: str,
        ext: str,
        project_root: str
    ) -> LSPOrphanDetector | None:
        """
        Try to create an LSP-based detector.

        Returns None if LSP is not available for the language.
        """
        language_id = OrphanDetectorFactory.LANGUAGE_ID_MAP.get(ext)
        if not language_id:
            return None

        try:
            from warden.lsp.manager import LSPManager

            manager = LSPManager.get_instance()
            if not manager.is_available(language_id):
                logger.debug("lsp_not_available", language=language_id)
                return None

            client = await manager.get_client_async(language_id, project_root)
            if not client:
                return None

            logger.info("lsp_orphan_detector_created", language=language_id, file=file_path)
            return LSPOrphanDetector(code, file_path, client, language_id)

        except Exception as e:
            logger.warning("lsp_detector_creation_failed", error=str(e))
            return None
