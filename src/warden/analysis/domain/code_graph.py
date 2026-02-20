"""
Code Graph Domain Models.

Symbol-level dependency graph extracted purely from AST.
Zero LLM cost, zero new dependencies.

Chaos Fixes Applied:
- K1: FQN keys (file_path::ClassName) to prevent symbol collision
- Y6: runtime flag on edges (TYPE_CHECKING filter)
- Y7: is_test flag on nodes, who_uses(include_tests) parameter
- Y5: star_imports tracking in GapReport
- O1: dynamic_imports tracking in GapReport
- O6: unparseable_files tracking in GapReport
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field

from warden.shared.domain.base_model import BaseDomainModel


class SymbolKind(str, Enum):
    """Kind of code symbol."""

    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"
    MIXIN = "mixin"
    INTERFACE = "interface"
    MODULE = "module"


class EdgeRelation(str, Enum):
    """Relation type between symbols."""

    DEFINES = "defines"  # file -> class/function
    INHERITS = "inherits"  # class -> parent class
    IMPLEMENTS = "implements"  # class -> mixin/interface
    CALLS = "calls"  # function -> function
    IMPORTS = "imports"  # file -> file (symbol-level)
    RE_EXPORTS = "re_exports"  # __init__.py re-export chain


class SymbolNode(BaseDomainModel):
    """
    A code symbol: class, function, method, mixin.

    Key format (K1 fix): "file_path::ClassName" to prevent collision.
    Example: "src/warden/llm/config.py::Config"
    """

    fqn: str  # Fully qualified name (key in graph)
    name: str  # Short name ("Config")
    kind: SymbolKind
    file_path: str  # Relative path from project root
    line: int = 0
    module: str = ""  # Python module path (warden.llm.config)
    is_test: bool = False  # Y7: Test file flag
    bases: list[str] = Field(default_factory=list)  # Parent classes
    metadata: dict[str, Any] = Field(default_factory=dict)


class SymbolEdge(BaseDomainModel):
    """
    A directed relationship between symbols.

    Y6 fix: runtime flag for TYPE_CHECKING imports.
    """

    source: str  # FQN of source symbol
    target: str  # FQN of target symbol
    relation: EdgeRelation
    runtime: bool = True  # Y6: False if TYPE_CHECKING only
    metadata: dict[str, Any] = Field(default_factory=dict)


class CodeGraph(BaseDomainModel):
    """
    Project-wide symbol relationship graph.

    Nodes keyed by FQN (K1 fix) to prevent collision.
    """

    schema_version: str = "1.0.0"
    nodes: dict[str, SymbolNode] = Field(default_factory=dict)
    edges: list[SymbolEdge] = Field(default_factory=list)

    def add_node(self, node: SymbolNode) -> None:
        """Add a symbol node keyed by FQN."""
        self.nodes[node.fqn] = node

    def add_edge(self, edge: SymbolEdge) -> None:
        """Add a symbol edge."""
        self.edges.append(edge)

    def who_uses(self, symbol_fqn: str, *, include_tests: bool = False) -> list[SymbolEdge]:
        """
        Find all edges where target matches the given symbol.

        Y7 fix: Excludes test-file sources by default.

        Args:
            symbol_fqn: FQN of the symbol to search for.
            include_tests: If True, include edges from test files.

        Returns:
            List of edges pointing to this symbol.
        """
        results = []
        for edge in self.edges:
            if edge.target != symbol_fqn:
                continue
            if not include_tests:
                source_node = self.nodes.get(edge.source)
                if source_node and source_node.is_test:
                    continue
            results.append(edge)
        return results

    def who_inherits(self, class_fqn: str) -> list[SymbolNode]:
        """Find all classes that inherit from the given class."""
        child_fqns = {
            e.source for e in self.edges if e.target == class_fqn and e.relation == EdgeRelation.INHERITS
        }
        return [self.nodes[fqn] for fqn in child_fqns if fqn in self.nodes]

    def who_implements(self, mixin_fqn: str) -> list[SymbolNode]:
        """Find all classes that implement the given mixin/interface."""
        impl_fqns = {
            e.source for e in self.edges if e.target == mixin_fqn and e.relation == EdgeRelation.IMPLEMENTS
        }
        return [self.nodes[fqn] for fqn in impl_fqns if fqn in self.nodes]

    def get_dependency_chain(self, symbol_fqn: str, max_depth: int = 5) -> list[list[SymbolEdge]]:
        """
        Get dependency chains starting from a symbol (BFS).

        Returns list of paths (each path is a list of edges).
        """
        chains: list[list[SymbolEdge]] = []
        queue: list[tuple[str, list[SymbolEdge]]] = [(symbol_fqn, [])]
        visited: set[str] = set()

        while queue:
            current, path = queue.pop(0)
            if current in visited or len(path) >= max_depth:
                continue
            visited.add(current)

            outgoing = [e for e in self.edges if e.source == current]
            for edge in outgoing:
                new_path = [*path, edge]
                chains.append(new_path)
                queue.append((edge.target, new_path))

        return chains

    def find_orphan_symbols(self) -> list[SymbolNode]:
        """Find symbols with zero edges (neither source nor target)."""
        connected = set()
        for edge in self.edges:
            connected.add(edge.source)
            connected.add(edge.target)
        return [node for fqn, node in self.nodes.items() if fqn not in connected]

    def find_circular_deps(self) -> list[list[str]]:
        """Detect circular dependency cycles via DFS."""
        cycles: list[list[str]] = []
        visited: set[str] = set()
        rec_stack: set[str] = set()

        adj: dict[str, list[str]] = {}
        for edge in self.edges:
            if edge.relation in (EdgeRelation.INHERITS, EdgeRelation.IMPLEMENTS, EdgeRelation.IMPORTS):
                adj.setdefault(edge.source, []).append(edge.target)

        def _dfs(node: str, path: list[str]) -> None:
            visited.add(node)
            rec_stack.add(node)
            path.append(node)

            for neighbor in adj.get(node, []):
                if neighbor not in visited:
                    _dfs(neighbor, path)
                elif neighbor in rec_stack:
                    # Extract cycle
                    cycle_start = path.index(neighbor)
                    cycle = path[cycle_start:] + [neighbor]
                    if cycle not in cycles:
                        cycles.append(cycle)

            path.pop()
            rec_stack.discard(node)

        for node_fqn in adj:
            if node_fqn not in visited:
                _dfs(node_fqn, [])

        return cycles

    def get_symbol_by_name(self, name: str) -> SymbolNode | None:
        """Find first symbol matching short name."""
        for node in self.nodes.values():
            if node.name == name:
                return node
        return None

    def get_symbols_by_name(self, name: str) -> list[SymbolNode]:
        """Find all symbols matching short name (handles K1 collision)."""
        return [node for node in self.nodes.values() if node.name == name]

    def get_runtime_edges(self) -> list[SymbolEdge]:
        """Y6: Filter to only runtime edges (exclude TYPE_CHECKING)."""
        return [e for e in self.edges if e.runtime]

    def stats(self) -> dict[str, int]:
        """Get graph statistics."""
        return {
            "total_nodes": len(self.nodes),
            "total_edges": len(self.edges),
            "classes": sum(1 for n in self.nodes.values() if n.kind == SymbolKind.CLASS),
            "functions": sum(1 for n in self.nodes.values() if n.kind in (SymbolKind.FUNCTION, SymbolKind.METHOD)),
            "test_nodes": sum(1 for n in self.nodes.values() if n.is_test),
            "type_checking_edges": sum(1 for e in self.edges if not e.runtime),
        }


class GapReport(BaseDomainModel):
    """
    Analysis of missing/incomplete code graph coverage.

    Extended with chaos analysis fields: Y5, O1, O6, Y7.
    """

    orphan_files: list[str] = Field(default_factory=list)
    orphan_symbols: list[str] = Field(default_factory=list)
    broken_imports: list[str] = Field(default_factory=list)
    circular_deps: list[list[str]] = Field(default_factory=list)
    unreachable_from_entry: list[str] = Field(default_factory=list)
    missing_mixin_impl: list[str] = Field(default_factory=list)
    shadow_re_exports: list[str] = Field(default_factory=list)
    coverage: float = 0.0

    # Chaos analysis additions
    star_imports: list[str] = Field(default_factory=list)  # Y5
    dynamic_imports: list[str] = Field(default_factory=list)  # O1
    type_checking_only: list[str] = Field(default_factory=list)  # Y6
    unparseable_files: list[str] = Field(default_factory=list)  # O6
    test_only_consumers: dict[str, list[str]] = Field(default_factory=dict)  # Y7

    def has_critical_gaps(self) -> bool:
        """Check if there are critical gaps that should block CI."""
        return bool(self.broken_imports) or (
            self.coverage > 0 and len(self.unreachable_from_entry) > 0.2 * (1 / max(self.coverage, 0.01))
        )

    def summary(self) -> dict[str, Any]:
        """Get summary statistics."""
        return {
            "orphan_files": len(self.orphan_files),
            "orphan_symbols": len(self.orphan_symbols),
            "broken_imports": len(self.broken_imports),
            "circular_deps": len(self.circular_deps),
            "unreachable_from_entry": len(self.unreachable_from_entry),
            "missing_mixin_impl": len(self.missing_mixin_impl),
            "star_imports": len(self.star_imports),
            "dynamic_imports": len(self.dynamic_imports),
            "unparseable_files": len(self.unparseable_files),
            "coverage": self.coverage,
        }
