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
    
    Supports: JavaScript, TypeScript, Go, Rust, Java, etc.
    Uses py-tree-sitter library for parsing.
    """
    
    # Language to tree-sitter module mapping
    LANGUAGE_MAP = {
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".go": "go",
        ".rs": "rust",
        ".java": "java",
        ".rb": "ruby",
        ".c": "c",
        ".cpp": "cpp",
        ".cs": "c_sharp",
        ".svelte": "svelte",
    }
    
    def __init__(self, code: str, file_path: str) -> None:
        super().__init__(code, file_path)
        self.tree = None
        self.parser = None
        self.language_name = None
        
        # Determine language from extension
        _, ext = os.path.splitext(file_path)
        self.language_name = self.LANGUAGE_MAP.get(ext.lower())
        
        if not self.language_name:
            logger.warning("tree_sitter_unsupported_extension", ext=ext)
            return
            
        # Try to load tree-sitter (with auto-install)
        try:
            import tree_sitter
        except ImportError:
            # Auto-install core tree-sitter
            logger.info("auto_installing_tree_sitter_core")
            try:
                import subprocess
                import sys
                result = subprocess.run(
                    [sys.executable, "-m", "pip", "install", "tree-sitter", "-q"],
                    capture_output=True,
                    text=True,
                    timeout=60
                )
                if result.returncode == 0:
                    logger.info("tree_sitter_core_installed")
                    import tree_sitter
                else:
                    logger.warning("tree_sitter_core_install_failed", error=result.stderr)
                    return
            except Exception as e:
                logger.warning("tree_sitter_auto_install_error", error=str(e))
                return
            
        try:
            # Try to load language-specific binding
            lang_capsule = self._load_language_module(self.language_name)
            
            if lang_capsule:
                # tree-sitter 0.21+ API: Parser() then set_language(Language(capsule))
                lang = tree_sitter.Language(lang_capsule)
                self.parser = tree_sitter.Parser()
                self.parser.language = lang
                self.tree = self.parser.parse(bytes(code, "utf8"))
                logger.debug(
                    "tree_sitter_parser_initialized",
                    language=self.language_name,
                    file=file_path
                )
            else:
                logger.warning(
                    "tree_sitter_language_not_installed",
                    language=self.language_name
                )
        except Exception as e:
            logger.warning(
                "tree_sitter_initialization_failed",
                language=self.language_name,
                error=str(e)
            )
    
    def _load_language_module(self, language_name: str) -> Optional[Any]:
        """
        Load tree-sitter language module dynamically.
        Auto-installs missing bindings if not found.
        """
        # Package name mapping
        package_map = {
            "javascript": "tree-sitter-javascript",
            "typescript": "tree-sitter-typescript",
            "go": "tree-sitter-go",
            "rust": "tree-sitter-rust",
            "java": "tree-sitter-java",
            "ruby": "tree-sitter-ruby",
            "c": "tree-sitter-c",
            "cpp": "tree-sitter-cpp",
            "c_sharp": "tree-sitter-c-sharp",
            "svelte": "tree-sitter-svelte",
        }
        
        def try_import():
            if language_name == "javascript":
                import tree_sitter_javascript as ts_js
                return ts_js.language()
            elif language_name == "typescript":
                import tree_sitter_typescript as ts_ts
                return ts_ts.language_typescript()
            elif language_name == "go":
                import tree_sitter_go as ts_go
                return ts_go.language()
            elif language_name == "rust":
                import tree_sitter_rust as ts_rust
                return ts_rust.language()
            elif language_name == "java":
                import tree_sitter_java as ts_java
                return ts_java.language()
            elif language_name == "ruby":
                import tree_sitter_ruby as ts_ruby
                return ts_ruby.language()
            elif language_name == "c":
                import tree_sitter_c as ts_c
                return ts_c.language()
            elif language_name == "cpp":
                import tree_sitter_cpp as ts_cpp
                return ts_cpp.language()
            elif language_name == "c_sharp":
                import tree_sitter_c_sharp as ts_cs
                return ts_cs.language()
            elif language_name == "svelte":
                import tree_sitter_svelte as ts_svelte
                return ts_svelte.language()
            return None
        
        try:
            return try_import()
        except ImportError:
            # Auto-install missing package
            package = package_map.get(language_name)
            if package:
                logger.info(
                    "auto_installing_tree_sitter_binding",
                    language=language_name,
                    package=package
                )
                try:
                    import subprocess
                    import sys
                    
                    # Install package
                    result = subprocess.run(
                        [sys.executable, "-m", "pip", "install", package, "-q"],
                        capture_output=True,
                        text=True,
                        timeout=60
                    )
                    
                    if result.returncode == 0:
                        logger.info(
                            "tree_sitter_binding_installed",
                            package=package
                        )
                        # Try import again after installation
                        return try_import()
                    else:
                        logger.warning(
                            "tree_sitter_install_failed",
                            package=package,
                            error=result.stderr
                        )
                except Exception as install_error:
                    logger.warning(
                        "tree_sitter_auto_install_error",
                        package=package,
                        error=str(install_error)
                    )
            return None
    
    def detect_all(self) -> List[OrphanFinding]:
        """
        Detect orphan code using Tree Sitter.
        """
        if not self.tree:
            return []
            
        findings: List[OrphanFinding] = []
        
        # Collect function/class definitions  
        definitions = self._collect_definitions(self.tree.root_node)
        
        # Collect all identifier references (excluding the definition names themselves)
        references = self._collect_references(self.tree.root_node, exclude_nodes=set(
            node for _, (_, _, node) in definitions.items()
        ))
        
        # Debug logging
        logger.debug(
            "tree_sitter_detection_stats",
            file=self.file_path,
            definitions_count=len(definitions),
            references_count=len(references),
            definition_names=list(definitions.keys())[:10]  # First 10
        )
        
        # Find unreferenced definitions
        skipped_count = 0
        for name, (line_num, def_type, node) in definitions.items():
            if name not in references:
                # Skip common patterns that are often exported/used externally
                if self._should_skip(name, node):
                    skipped_count += 1
                    continue
                    
                code_snippet = self._get_node_snippet(node)
                findings.append(
                    OrphanFinding(
                        orphan_type=f"unreferenced_{def_type}",
                        name=name,
                        line_number=line_num,
                        code_snippet=code_snippet,
                        reason=f"{def_type.capitalize()} '{name}' appears unused",
                    )
                )
        
        if skipped_count > 0:
            logger.debug(
                "tree_sitter_skipped_exports",
                file=self.file_path,
                skipped_count=skipped_count
            )
        
        return findings
    
    def _collect_definitions(self, node: Any) -> Dict[str, tuple]:
        """
        Collect function and class definitions from AST.
        """
        definitions: Dict[str, tuple] = {}
        
        # Node types for function/class definitions across languages
        def_types = {
            # JavaScript/TypeScript - traditional functions
            "function_declaration": "function",
            "method_definition": "method",
            "class_declaration": "class",
            # Go
            "function_declaration": "function",
            "method_declaration": "method",
            "type_declaration": "type",
            # Rust
            "function_item": "function",
            "impl_item": "impl",
            "struct_item": "struct",
            # Java
            "method_declaration": "method",
            "class_declaration": "class",
        }
        
        def walk(n):
            # Standard function/class declarations
            if n.type in def_types:
                name = self._extract_name(n)
                if name and not name.startswith("_"):
                    definitions[name] = (
                        n.start_point[0] + 1,
                        def_types[n.type],
                        n
                    )
            
            # TypeScript/JS: const myFunc = () => {} or const myFunc = function() {}
            elif n.type == "lexical_declaration" or n.type == "variable_declaration":
                for declarator in n.children:
                    if declarator.type == "variable_declarator":
                        # Check if value is a function
                        name_node = None
                        value_node = None
                        for child in declarator.children:
                            if child.type == "identifier":
                                name_node = child
                            elif child.type in ["arrow_function", "function_expression", "function"]:
                                value_node = child
                        
                        if name_node and value_node:
                            name = name_node.text.decode("utf8")
                            if not name.startswith("_"):
                                definitions[name] = (
                                    n.start_point[0] + 1,
                                    "function",
                                    n
                                )
            
            for child in n.children:
                walk(child)
        
        walk(node)
        return definitions
    
    def _collect_references(self, node: Any, exclude_nodes: set = None) -> set:
        """
        Collect all identifier references from AST.
        Excludes identifiers within nodes in exclude_nodes (definition sites).
        """
        references = set()
        exclude_nodes = exclude_nodes or set()
        
        def is_excluded(n):
            """Check if this node or any of its ancestors is in exclude set."""
            current = n
            while current:
                if current in exclude_nodes:
                    return True
                current = current.parent
            return False
        
        def walk(n):
            # Skip if this is a definition node (or child of one)
            if is_excluded(n):
                return
                
            # Identifier nodes represent name references
            if n.type == "identifier":
                references.add(n.text.decode("utf8"))
            elif n.type == "property_identifier":
                references.add(n.text.decode("utf8"))
            
            for child in n.children:
                walk(child)
        
        walk(node)
        return references
    
    def _extract_name(self, node: Any) -> Optional[str]:
        """
        Extract the name from a definition node.
        """
        # Look for identifier child
        for child in node.children:
            if child.type == "identifier":
                return child.text.decode("utf8")
            if child.type == "property_identifier":
                return child.text.decode("utf8")
            if child.type == "name":  # Go
                return child.text.decode("utf8")
        return None
    
    def _should_skip(self, name: str, node: Any) -> bool:
        """
        Check if definition should be skipped (exported, main, etc).
        """
        # Skip common exported/main patterns
        skip_names = {"main", "init", "setup", "teardown", "constructor"}
        if name.lower() in skip_names:
            return True
            
        # Skip if exported (has export keyword parent)
        parent = node.parent
        while parent:
            if parent.type in ["export_statement", "export_declaration"]:
                return True
            parent = parent.parent
            
        return False
    
    def _get_node_snippet(self, node: Any) -> str:
        """
        Get code snippet for a node.
        """
        start_line = node.start_point[0]
        end_line = min(node.end_point[0], start_line + 5)  # Max 5 lines
        
        lines = self.lines[start_line:end_line + 1]
        return "\n".join(lines).strip()


class OrphanDetectorFactory:
    """
    Factory for creating the appropriate OrphanDetector strategy.
    
    Selection Logic:
    1. Native Parser (if available for language)
    2. Tree Sitter (for other supported languages)
    3. None (Unsupported language)
    """
    
    @staticmethod
    def create_detector(code: str, file_path: str) -> Optional[AbstractOrphanDetector]:
        """
        Create detector instance based on file type.
        """
        _, ext = os.path.splitext(file_path)
        ext = ext.lower()
        
        # Priority 1: Native Parsers (faster, more accurate)
        if ext == ".py":
            return PythonOrphanDetector(code, file_path)
            
        # Priority 2: Tree Sitter (universal parser)
        if ext in TreeSitterOrphanDetector.LANGUAGE_MAP:
            detector = TreeSitterOrphanDetector(code, file_path)
            if detector.tree:  # Only return if parsing succeeded
                return detector
            # If tree-sitter failed, return None (graceful degradation)
            logger.info(
                "tree_sitter_fallback_failed",
                file=file_path,
                hint="Install tree-sitter bindings for this language"
            )
            
        return None
