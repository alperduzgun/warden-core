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

        # Collect all imports
        imports: Dict[str, Tuple[int, str]] = {}  # name -> (line_num, full_import)

        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    import_name = alias.asname if alias.asname else alias.name
                    line_num = node.lineno
                    imports[import_name] = (line_num, f"import {alias.name}")

            elif isinstance(node, ast.ImportFrom):
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

        # Find unused imports
        for import_name, (line_num, import_stmt) in imports.items():
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
                # Skip private functions (often used internally)
                if not node.name.startswith("_"):
                    line_num = node.lineno
                    definitions[node.name] = (line_num, "function", f"def {node.name}", node)

            elif isinstance(node, ast.ClassDef):
                # Skip private classes
                if not node.name.startswith("_"):
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
        # Get lines from start_line to end_line (or limit to 15 lines)
        max_lines = 15
        current_line = start_line
        
        while current_line <= len(self.lines) and len(lines) < max_lines:
            line = self.lines[current_line - 1] # 0-indexed list
            lines.append(line)
            
            # Stop if we found the end of definition (colon)
            # But handle multi-line args
            if line.strip().endswith(":") and current_line >= node.lineno:
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


class TreeSitterOrphanDetector(AbstractOrphanDetector):
    """
    Generic Tree Sitter based orphan detector for multiple languages.
    """
    
    def __init__(self, code: str, file_path: str) -> None:
        super().__init__(code, file_path)
        # TODO: Initialize tree-sitter parser here
        # self.parser = ...
    
    def detect_all(self) -> List[OrphanFinding]:
        """
        Detect orphan code using Tree Sitter.
        """
        # Placeholder implementation
        logger.warning(
            "tree_sitter_orphan_detection_not_implemented", 
            file=str(self.file_path)
        )
        return []


class OrphanDetectorFactory:
    """
    Factory for creating the appropriate OrphanDetector strategy.
    
    Selection Logic:
    1. Native Parser (if available for language)
    2. Tree Sitter (if available and configured)
    3. None (Not supported)
    """
    
    @staticmethod
    def create_detector(code: str, file_path: str) -> Optional[AbstractOrphanDetector]:
        """
        Create detector instance based on file type.
        """
        _, ext = os.path.splitext(file_path)
        ext = ext.lower()
        
        # Priority 1: Native Parsers
        if ext == ".py":
            return PythonOrphanDetector(code, file_path)
            
        # Priority 2: Tree Sitter (For JS/TS/Go etc.)
        supported_ts_extensions = [".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java"]
        if ext in supported_ts_extensions:
            # Check if tree-sitter is actually installed/available
            # For now, return the class, it will log warning
            return TreeSitterOrphanDetector(code, file_path)
            
        return None
