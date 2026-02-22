"""
Code Graph Builder.

Builds a symbol-level CodeGraph from AST cache data.
Zero LLM cost — purely deterministic AST traversal.

Chaos Fixes Applied:
- K1: FQN keys (file_path::ClassName) to prevent symbol collision
- K3: Python-first strategy, multi-language explicit "unresolved" marker
- Y1: __init__.py re-export chain tracing
- Y5: Star import detection
- Y6: TYPE_CHECKING import → runtime=False edge
- Y7: Test file detection (is_test flag)
- O1: Dynamic import detection (importlib pattern)
- Gemini mixin fix: bases with Mixin/Aware in name → IMPLEMENTS (not decorators)
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import structlog

from warden.analysis.domain.code_graph import (
    CodeGraph,
    EdgeRelation,
    SymbolEdge,
    SymbolKind,
    SymbolNode,
)
from warden.ast.domain.enums import ASTNodeType, ParseStatus
from warden.ast.domain.models import ASTNode

logger = structlog.get_logger(__name__)

# Patterns for test file detection (Y7)
_TEST_PATH_PATTERNS = re.compile(
    r"(^|/)tests?/|test_[^/]+\.py$|[^/]+_test\.py$|conftest\.py$|/fixtures/",
    re.IGNORECASE,
)

# Patterns for dynamic import detection (O1)
_DYNAMIC_IMPORT_RE = re.compile(
    r"importlib\.import_module|__import__\(|importlib\.util\.find_spec",
)

# Mixin/ABC name patterns (Gemini fix)
_MIXIN_NAME_RE = re.compile(r"Mixin|Aware|ABC$|Interface$|Protocol$|Abstract")


class CodeGraphBuilder:
    """
    Builds CodeGraph from AST cache.

    Phase 1 supports Python only (K3 fix). Other languages get
    "unresolved" markers in the gap report.
    """

    def __init__(
        self,
        ast_cache: dict[str, Any],
        project_root: Path | None = None,
    ) -> None:
        self._ast_cache = ast_cache
        self._project_root = project_root or Path.cwd()
        self._graph = CodeGraph()

        # Tracking for gap analysis
        self.star_import_files: list[str] = []  # Y5
        self.dynamic_import_files: list[str] = []  # O1
        self.type_checking_imports: list[str] = []  # Y6
        self.unparseable_files: list[str] = []  # O6

    def build(self, dependency_graph: Any | None = None) -> CodeGraph:
        """
        Build CodeGraph from AST cache.

        Args:
            dependency_graph: Optional DependencyGraph for file-level edges.

        Returns:
            Populated CodeGraph.
        """
        logger.info("code_graph_build_started", files=len(self._ast_cache))

        for file_path, parse_result in self._ast_cache.items():
            rel_path = self._relative_path(file_path)
            is_test = bool(_TEST_PATH_PATTERNS.search(rel_path))

            # Check if parse_result is a ParseResult object with ast_root
            ast_root = self._extract_ast_root(parse_result)
            if ast_root is None:
                self.unparseable_files.append(rel_path)
                continue

            # Only process Python files for now (K3: Python-first)
            language = self._get_language(parse_result)
            if language and language != "python":
                continue

            # Extract symbols from AST
            self._process_file(rel_path, ast_root, is_test, file_path)

        # Process __init__.py re-exports (Y1)
        self._process_re_exports()

        # Add file-level IMPORTS edges from dependency graph
        if dependency_graph:
            self._add_dependency_edges(dependency_graph)

        stats = self._graph.stats()
        logger.info(
            "code_graph_build_completed",
            nodes=stats["total_nodes"],
            edges=stats["total_edges"],
            test_nodes=stats["test_nodes"],
            type_checking_edges=stats["type_checking_edges"],
        )

        return self._graph

    def _extract_ast_root(self, parse_result: Any) -> ASTNode | None:
        """Extract ASTNode from parse result, handling different formats."""
        if parse_result is None:
            return None

        # ParseResult object
        if hasattr(parse_result, "ast_root"):
            if hasattr(parse_result, "status"):
                status = parse_result.status
                if hasattr(status, "value"):
                    status = status.value
                if status == ParseStatus.FAILED.value:
                    return None
            return parse_result.ast_root

        # Direct ASTNode
        if isinstance(parse_result, ASTNode):
            return parse_result

        # Dict format (legacy)
        if isinstance(parse_result, dict):
            return parse_result.get("ast_root")

        return None

    def _get_language(self, parse_result: Any) -> str | None:
        """Extract language string from parse result."""
        if hasattr(parse_result, "language"):
            lang = parse_result.language
            return lang.value if hasattr(lang, "value") else str(lang)
        return None

    def _relative_path(self, file_path: str) -> str:
        """Convert absolute path to relative."""
        try:
            return str(Path(file_path).relative_to(self._project_root))
        except ValueError:
            return file_path

    def _make_fqn(self, file_path: str, symbol_name: str) -> str:
        """
        Create FQN key (K1 fix).

        Format: "relative/path.py::ClassName"
        For methods: "relative/path.py::ClassName.method_name"
        """
        return f"{file_path}::{symbol_name}"

    def _process_file(
        self,
        rel_path: str,
        ast_root: ASTNode,
        is_test: bool,
        original_path: str,
    ) -> None:
        """Process a single file's AST and extract symbols/edges."""
        # Check source code for dynamic imports (O1)
        source = self._get_source_for_path(original_path)
        if source and _DYNAMIC_IMPORT_RE.search(source):
            self.dynamic_import_files.append(rel_path)

        # Track if we're inside TYPE_CHECKING block
        in_type_checking = False

        for child in ast_root.children:
            # Detect TYPE_CHECKING block (Y6)
            if child.node_type == ASTNodeType.IF_STATEMENT:
                if self._is_type_checking_block(child):
                    in_type_checking = True
                    self._process_type_checking_imports(child, rel_path, is_test)
                    in_type_checking = False
                    continue

            if child.node_type in (ASTNodeType.CLASS, ASTNodeType.ENUM):
                self._process_class(rel_path, child, is_test, in_type_checking)
            elif child.node_type == ASTNodeType.FUNCTION:
                self._process_function(rel_path, child, is_test, parent_class=None)
            elif child.node_type == ASTNodeType.IMPORT:
                self._process_import(rel_path, child, is_test, runtime=not in_type_checking)

    def _process_class(
        self,
        file_path: str,
        node: ASTNode,
        is_test: bool,
        in_type_checking: bool,
    ) -> None:
        """Process a class definition node."""
        class_name = node.name or ""
        if not class_name:
            return

        fqn = self._make_fqn(file_path, class_name)

        # Determine kind based on bases (Gemini fix)
        bases = node.attributes.get("bases", [])
        kind = SymbolKind.CLASS
        if any(_MIXIN_NAME_RE.search(b) for b in bases if isinstance(b, str)):
            kind = SymbolKind.MIXIN
        elif any(b in ("ABC", "Protocol") for b in bases):
            kind = SymbolKind.INTERFACE

        # Also check the class name itself for mixin patterns
        if _MIXIN_NAME_RE.search(class_name):
            kind = SymbolKind.MIXIN

        module = self._path_to_module(file_path)

        decorators = node.attributes.get("decorators", [])

        symbol = SymbolNode(
            fqn=fqn,
            name=class_name,
            kind=kind,
            file_path=file_path,
            line=node.location.start_line if node.location else 0,
            module=module,
            is_test=is_test,
            bases=bases,
            metadata={"decorators": decorators} if decorators else {},
        )
        self._graph.add_node(symbol)

        # DEFINES edge: file -> class
        self._graph.add_edge(
            SymbolEdge(
                source=file_path,
                target=fqn,
                relation=EdgeRelation.DEFINES,
            )
        )

        # Process bases for INHERITS / IMPLEMENTS edges (Gemini fix)
        for base_name in bases:
            if not isinstance(base_name, str):
                continue

            # Gemini fix: Mixin/Aware in base name → IMPLEMENTS edge
            if _MIXIN_NAME_RE.search(base_name):
                relation = EdgeRelation.IMPLEMENTS
            else:
                relation = EdgeRelation.INHERITS

            # Target FQN is unresolved (just the base name for now)
            # The builder will try to resolve within the graph later
            self._graph.add_edge(
                SymbolEdge(
                    source=fqn,
                    target=base_name,  # Will be resolved if target exists
                    relation=relation,
                    runtime=not in_type_checking,
                )
            )

        # Process methods inside class
        for child in node.children:
            if child.node_type in (ASTNodeType.FUNCTION, ASTNodeType.METHOD):
                self._process_function(file_path, child, is_test, parent_class=class_name)

    def _process_function(
        self,
        file_path: str,
        node: ASTNode,
        is_test: bool,
        parent_class: str | None,
    ) -> None:
        """Process a function/method definition node."""
        func_name = node.name or ""
        if not func_name:
            return

        # Build FQN
        if parent_class:
            full_name = f"{parent_class}.{func_name}"
            kind = SymbolKind.METHOD
        else:
            full_name = func_name
            kind = SymbolKind.FUNCTION

        fqn = self._make_fqn(file_path, full_name)
        module = self._path_to_module(file_path)
        decorators = node.attributes.get("decorators", [])

        symbol = SymbolNode(
            fqn=fqn,
            name=func_name,
            kind=kind,
            file_path=file_path,
            line=node.location.start_line if node.location else 0,
            module=module,
            is_test=is_test,
            metadata={"decorators": decorators} if decorators else {},
        )
        self._graph.add_node(symbol)

        # DEFINES edge
        if parent_class:
            parent_fqn = self._make_fqn(file_path, parent_class)
            self._graph.add_edge(
                SymbolEdge(
                    source=parent_fqn,
                    target=fqn,
                    relation=EdgeRelation.DEFINES,
                )
            )

        # Extract CALLS edges from CALL_EXPRESSION children
        self._extract_calls(fqn, node)

    def _extract_calls(self, caller_fqn: str, node: ASTNode) -> None:
        """Recursively find call expressions in a function body."""
        for child in node.children:
            if child.node_type == ASTNodeType.CALL_EXPRESSION:
                callee_name = child.name or child.value or ""
                if callee_name and callee_name not in (
                    "print",
                    "len",
                    "range",
                    "str",
                    "int",
                    "float",
                    "bool",
                    "list",
                    "dict",
                    "set",
                    "tuple",
                    "type",
                    "isinstance",
                    "hasattr",
                    "getattr",
                    "super",
                ):
                    self._graph.add_edge(
                        SymbolEdge(
                            source=caller_fqn,
                            target=callee_name,
                            relation=EdgeRelation.CALLS,
                        )
                    )
            # Recurse into child nodes
            self._extract_calls(caller_fqn, child)

    def _process_import(
        self,
        file_path: str,
        node: ASTNode,
        is_test: bool,
        runtime: bool = True,
    ) -> None:
        """Process an import statement node."""
        names = node.attributes.get("names", [])
        module = node.attributes.get("module", "")

        # Y5: Detect star imports
        if "*" in names:
            self.star_import_files.append(file_path)

        # Create IMPORTS edges at symbol level
        for name in names:
            if name == "*":
                continue  # Star imports can't create precise edges
            target = f"{module}.{name}" if module else name
            self._graph.add_edge(
                SymbolEdge(
                    source=file_path,
                    target=target,
                    relation=EdgeRelation.IMPORTS,
                    runtime=runtime,
                )
            )

    def _process_type_checking_imports(
        self,
        if_node: ASTNode,
        file_path: str,
        is_test: bool,
    ) -> None:
        """Process imports inside TYPE_CHECKING block (Y6)."""
        self.type_checking_imports.append(file_path)
        for child in if_node.children:
            if child.node_type == ASTNodeType.IMPORT:
                self._process_import(file_path, child, is_test, runtime=False)

    def _is_type_checking_block(self, node: ASTNode) -> bool:
        """Check if an if-statement is `if TYPE_CHECKING:`."""
        # The condition is typically the first child or in the name
        if node.name and "TYPE_CHECKING" in node.name:
            return True
        if node.value and "TYPE_CHECKING" in str(node.value):
            return True
        # Check children for identifier
        for child in node.children:
            if child.node_type == ASTNodeType.IDENTIFIER and child.name == "TYPE_CHECKING":
                return True
        return False

    def _process_re_exports(self) -> None:
        """
        Y1: Process __init__.py files to trace re-export chains.

        Finds import statements in __init__.py and creates RE_EXPORTS edges.
        """
        for file_path, parse_result in self._ast_cache.items():
            rel_path = self._relative_path(file_path)
            if not rel_path.endswith("__init__.py"):
                continue

            ast_root = self._extract_ast_root(parse_result)
            if ast_root is None:
                continue

            for child in ast_root.children:
                if child.node_type != ASTNodeType.IMPORT:
                    continue

                module = child.attributes.get("module", "")
                names = child.attributes.get("names", [])

                # Only relative imports (from .X import Y)
                if not module:
                    continue

                for name in names:
                    if name == "*":
                        continue
                    # This __init__.py re-exports 'name' from 'module'
                    self._graph.add_edge(
                        SymbolEdge(
                            source=rel_path,
                            target=f"{module}.{name}" if module else name,
                            relation=EdgeRelation.RE_EXPORTS,
                        )
                    )

    def _add_dependency_edges(self, dependency_graph: Any) -> None:
        """Add file-level edges from DependencyGraph."""
        for src, deps in dependency_graph._forward_graph.items():
            src_rel = self._relative_path(str(src))
            for dep in deps:
                dep_rel = self._relative_path(str(dep))
                self._graph.add_edge(
                    SymbolEdge(
                        source=src_rel,
                        target=dep_rel,
                        relation=EdgeRelation.IMPORTS,
                    )
                )

    def _path_to_module(self, file_path: str) -> str:
        """Convert file path to Python module notation."""
        # src/warden/analysis/taint/service.py → warden.analysis.taint.service
        module = file_path.replace("/", ".").replace("\\", ".")
        if module.endswith(".py"):
            module = module[:-3]
        # Strip src/ prefix if present
        if module.startswith("src."):
            module = module[4:]
        # Strip __init__
        if module.endswith(".__init__"):
            module = module[:-9]
        return module

    def _get_source_for_path(self, file_path: str) -> str | None:
        """Try to read source from AST cache or disk for pattern matching."""
        parse_result = self._ast_cache.get(file_path)
        if parse_result and hasattr(parse_result, "file_path"):
            try:
                with open(file_path, encoding="utf-8", errors="ignore") as f:
                    return f.read(8192)  # First 8KB is enough for import patterns
            except OSError:
                pass
        return None
