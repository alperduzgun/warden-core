"""
Orphan Code Detector - Strategy Pattern for Multi-Language Support.

Defines the interface for orphan detection and concrete implementations
for supported languages.

Strategies:
1. PythonOrphanDetector (Native AST)
2. TreeSitterOrphanDetector (Generic / Future)
"""

import abc
import ast
import os
from dataclasses import dataclass
from typing import List, Dict, Set, Tuple, Optional, Any
from pathlib import Path
import structlog

from warden.ast.domain.models import ASTNode
from warden.ast.domain.enums import ASTNodeType, CodeLanguage
from warden.ast.application.provider_registry import ASTProviderRegistry

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
    def detect_all(self) -> List[OrphanFinding]:
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

    def detect_all(self) -> List[OrphanFinding]:
        """
        Detect all orphan code issues using Python AST.
        """
        if self.tree is None:
            return []  # Can't analyze invalid syntax

        findings: List[OrphanFinding] = []

        # Detect unused imports
        findings.extend(self.detect_unused_imports())

        # Detect unreferenced functions/classes
        findings.extend(self.detect_unreferenced_definitions())

        # Detect dead code
        findings.extend(self.detect_dead_code())

        return findings

    def detect_unused_imports(self) -> List[OrphanFinding]:
        """Detect unused imports."""
        if self.tree is None:
            return []

        findings: List[OrphanFinding] = []

        # Find TYPE_CHECKING blocks (imports there are for type hints only)
        type_checking_lines: Set[int] = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.If):
                test = node.test
                # Check for `if TYPE_CHECKING:` or `if typing.TYPE_CHECKING:`
                is_type_checking = False
                if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
                    is_type_checking = True
                elif isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING":
                    is_type_checking = True
                
                if is_type_checking:
                    # Mark all lines in the body as type checking imports
                    for stmt in node.body:
                        for child in ast.walk(stmt):
                            if hasattr(child, 'lineno'):
                                type_checking_lines.add(child.lineno)

        # Collect all imports (excluding TYPE_CHECKING blocks)
        imports: Dict[str, Tuple[int, str]] = {}  # name -> (line_num, full_import)

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
        all_exports: Set[str] = set()
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
        references: Set[str] = set()

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
        for import_name, (line_num, import_stmt) in imports.items():
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

    def detect_unreferenced_definitions(self) -> List[OrphanFinding]:
        """Detect unreferenced functions and classes."""
        if self.tree is None:
            return []

        findings: List[OrphanFinding] = []

        # Collect all function/class definitions
        definitions: Dict[str, Tuple[int, str, str, ast.AST]] = {}  # name -> (line, type, code, node)

        for node in ast.walk(self.tree):
            if isinstance(node, ast.FunctionDef):
                line_num = node.lineno
                definitions[node.name] = (line_num, "function", f"def {node.name}", node)

            elif isinstance(node, ast.ClassDef):
                line_num = node.lineno
                definitions[node.name] = (line_num, "class", f"class {node.name}", node)

        # Collect all name references (excluding the definitions themselves)
        references: Set[str] = set()

        class ReferenceCollector(ast.NodeVisitor):
            def __init__(self) -> None:
                self.refs: Set[str] = set()
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
        for def_name, (line_num, def_type, def_code, node) in definitions.items():
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

    def detect_dead_code(self) -> List[OrphanFinding]:
        """Detect dead code (unreachable statements)."""
        if self.tree is None:
            return []

        findings: List[OrphanFinding] = []

        class DeadCodeFinder(ast.NodeVisitor):
            def __init__(self, detector: "PythonOrphanDetector") -> None:
                self.findings: List[OrphanFinding] = []
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

            def _check_block(self, statements: List[ast.stmt]) -> None:
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
                                name=f"unreachable_statement",
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

    def detect_all(self) -> List[OrphanFinding]:
        """
        Detect all orphan code issues using Universal AST.
        """
        findings: List[OrphanFinding] = []

        # 1. Collect all definitions (functions, classes, interfaces)
        definitions = self._collect_definitions(self.ast_root)

        # 2. Collect node IDs to exclude (definition sites) - using id() since ASTNode isn't hashable
        exclude_node_ids = set(
            id(node) for _, (_, _, node) in definitions.items()
        )

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

    def _collect_definitions(self, root: ASTNode) -> Dict[str, Tuple[int, str, ASTNode]]:
        """
        Collect function, class, and interface definitions.
        """
        definitions: Dict[str, Tuple[int, str, ASTNode]] = {}
        
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

    def _collect_references(self, root: ASTNode, exclude_node_ids: Set[int]) -> Set[str]:
        """
        Collect all identifier references, excluding definition sites.
        """
        references: Set[str] = set()

        def is_excluded(node: ASTNode) -> bool:
            # Check if this node's id is in the exclusion set
            return id(node) in exclude_node_ids

        def walk(node: ASTNode):
            if is_excluded(node):
                return

            if node.node_type == ASTNodeType.IDENTIFIER:
                if node.name:
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
        if isinstance(metadata, dict) and metadata.get("is_exported"):
            return True

        return False

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
    # Kept for backward compatibility during migration
    pass


class OrphanDetectorFactory:
    """
    Factory for creating the appropriate OrphanDetector strategy.
    
    Selection Logic:
    1. Python Native AST (if language is Python)
    2. Universal AST via TreeSitterProvider (for other supported languages)
    3. None (Unsupported language)
    """
    
    @staticmethod
    async def create_detector(code: str, file_path: str) -> Optional[AbstractOrphanDetector]:
        """
        Create detector instance based on file type.
        """
        _, ext = os.path.splitext(file_path)
        ext = ext.lower()
        
        # Python uses Native AST (more mature)
        if ext == ".py":
            return PythonOrphanDetector(code, file_path)
            
        # Non-Python uses Universal AST via TreeSitterProvider
        try:
            language = CodeLanguage.UNKNOWN
            if ext in [".ts", ".tsx"]:
                language = CodeLanguage.TYPESCRIPT
            elif ext in [".js", ".jsx"]:
                language = CodeLanguage.JAVASCRIPT
            elif ext == ".go":
                language = CodeLanguage.GO
            elif ext == ".java":
                language = CodeLanguage.JAVA
            elif ext == ".cs":
                language = CodeLanguage.CSHARP

            if language != CodeLanguage.UNKNOWN:
                registry = ASTProviderRegistry()
                provider = registry.get_provider(language)
                if provider:
                    parse_result = await provider.parse(code, language, file_path)
                    if parse_result.ast_root:
                        return UniversalOrphanDetector(code, file_path, parse_result.ast_root)
        except Exception as e:
            logger.warning("factory_universal_detector_failed", file=file_path, error=str(e))
            
        return None
