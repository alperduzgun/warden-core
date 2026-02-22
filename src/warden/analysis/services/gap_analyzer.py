"""
Gap Analyzer Service.

Analyzes CodeGraph and DependencyGraph for coverage gaps,
orphans, broken imports, circular dependencies, and unreachable code.

Chaos Fixes Applied:
- Gemini: Test files excluded from unreachable_from_entry (they're not reachable from main entry points by design)
- Y5: star_imports from CodeGraphBuilder
- O1: dynamic_imports from CodeGraphBuilder
- O6: unparseable_files from CodeGraphBuilder
- Y7: test_only_consumers detection
"""

from __future__ import annotations

import fnmatch
import re
from typing import Any

import structlog

from warden.analysis.domain.code_graph import (
    CodeGraph,
    EdgeRelation,
    GapReport,
    SymbolKind,
)

logger = structlog.get_logger(__name__)

# Test path pattern (same as builder)
_TEST_PATH_RE = re.compile(
    r"(^|/)tests?/|test_[^/]+\.py$|[^/]+_test\.py$|conftest\.py$|/fixtures/",
    re.IGNORECASE,
)


def _matches_framework_pattern(file_path: str, patterns: list[str]) -> bool:
    """Check if a file path matches any framework entry-point pattern.

    Supports both exact filename matches (e.g. "manage.py") and
    glob patterns (e.g. "*/migrations/*.py", "pages/**/*").
    """
    # Normalise separators
    normalized = file_path.replace("\\", "/")
    basename = normalized.rsplit("/", 1)[-1] if "/" in normalized else normalized

    for pattern in patterns:
        # Exact basename match (e.g. "manage.py", "urls.py")
        if "/" not in pattern and "*" not in pattern:
            if basename == pattern:
                return True
            continue
        # Convert ** to work with fnmatch (** matches any path segments)
        fn_pattern = pattern.replace("**/*", "*").replace("**/", "*/")
        # Glob match against full path
        if fnmatch.fnmatch(normalized, fn_pattern):
            return True
        # Also try matching the filename only for patterns like "settings/*.py"
        if fnmatch.fnmatch(basename, fn_pattern):
            return True
    return False


class GapAnalyzer:
    """
    Analyzes CodeGraph for coverage gaps and missing relationships.

    Produces a GapReport with orphans, broken imports, circular deps,
    unreachable code, and coverage metrics.
    """

    def __init__(self, project_files: list[str] | None = None) -> None:
        """
        Args:
            project_files: List of all project file paths (relative) for coverage calculation.
        """
        self._project_files = project_files or []

    def analyze(
        self,
        code_graph: CodeGraph,
        dep_graph: Any | None = None,
        entry_points: list[str] | None = None,
        builder_meta: dict[str, Any] | None = None,
    ) -> GapReport:
        """
        Analyze code graph for gaps.

        Args:
            code_graph: The CodeGraph to analyze.
            dep_graph: Optional DependencyGraph for file-level analysis.
            entry_points: Optional list of entry point file paths.
            builder_meta: Optional metadata from CodeGraphBuilder
                         (star_imports, dynamic_imports, etc.)

        Returns:
            GapReport with all detected gaps.
        """
        logger.info("gap_analysis_started", nodes=len(code_graph.nodes), edges=len(code_graph.edges))

        report = GapReport()

        # Extract framework info from builder_meta for filtering
        detected_framework = ""
        framework_entry_patterns: list[str] = []
        if builder_meta:
            detected_framework = builder_meta.get("detected_framework", "")
            framework_entry_patterns = builder_meta.get("framework_entry_points", [])

        fw_excluded = 0

        # 1. Orphan files (in dependency graph but no edges)
        if dep_graph:
            raw_orphans = self._find_orphan_files(dep_graph)
            if framework_entry_patterns:
                report.orphan_files = [
                    f for f in raw_orphans if not _matches_framework_pattern(f, framework_entry_patterns)
                ]
                fw_excluded += len(raw_orphans) - len(report.orphan_files)
            else:
                report.orphan_files = raw_orphans

        # 2. Orphan symbols (in code graph but no edges)
        orphan_nodes = code_graph.find_orphan_symbols()
        report.orphan_symbols = [n.fqn for n in orphan_nodes]

        # 3. Broken imports (edge target not in graph)
        report.broken_imports = self._find_broken_imports(code_graph)

        # 4. Circular dependencies
        report.circular_deps = code_graph.find_circular_deps()

        # 5. Unreachable from entry points (Gemini fix: exclude test files)
        if entry_points:
            report.unreachable_from_entry = self._find_unreachable(dep_graph, entry_points, framework_entry_patterns)

        # 6. Missing mixin implementations
        report.missing_mixin_impl = self._find_missing_mixin_impl(code_graph)

        # 7. Coverage calculation
        report.coverage = self._calculate_coverage(code_graph)

        # 8. Test-only consumers (Y7)
        report.test_only_consumers = self._find_test_only_consumers(code_graph)

        # 9. Builder metadata (Y5, O1, Y6, O6)
        if builder_meta:
            report.star_imports = builder_meta.get("star_imports", [])
            report.dynamic_imports = builder_meta.get("dynamic_imports", [])
            report.type_checking_only = builder_meta.get("type_checking_imports", [])
            report.unparseable_files = builder_meta.get("unparseable_files", [])

        # 10. Framework metadata
        report.detected_framework = detected_framework
        report.framework_excluded_count = fw_excluded

        logger.info(
            "gap_analysis_completed",
            orphan_files=len(report.orphan_files),
            orphan_symbols=len(report.orphan_symbols),
            broken_imports=len(report.broken_imports),
            circular_deps=len(report.circular_deps),
            unreachable=len(report.unreachable_from_entry),
            coverage=f"{report.coverage:.1%}",
            detected_framework=detected_framework or "none",
            framework_excluded=fw_excluded,
        )

        return report

    def _find_orphan_files(self, dep_graph: Any) -> list[str]:
        """Find files that have no dependencies and no dependents."""
        all_nodes: set[str] = set()
        connected: set[str] = set()

        for src, deps in dep_graph._forward_graph.items():
            src_str = str(src)
            all_nodes.add(src_str)
            if deps:
                connected.add(src_str)
                connected.update(str(d) for d in deps)
            for d in deps:
                all_nodes.add(str(d))

        for tgt, dependents in dep_graph._reverse_graph.items():
            tgt_str = str(tgt)
            all_nodes.add(tgt_str)
            if dependents:
                connected.add(tgt_str)
                connected.update(str(d) for d in dependents)

        return sorted(all_nodes - connected)

    def _find_broken_imports(self, code_graph: CodeGraph) -> list[str]:
        """Find import edges whose target doesn't exist as a node."""
        broken = []
        known_fqns = set(code_graph.nodes.keys())
        # Also collect all module paths for matching
        known_modules = {n.module for n in code_graph.nodes.values() if n.module}

        for edge in code_graph.edges:
            if edge.relation != EdgeRelation.IMPORTS:
                continue
            target = edge.target
            # Target exists as FQN → OK
            if target in known_fqns:
                continue
            # Target exists as module → OK
            if target in known_modules:
                continue
            # Target is a known short name → OK
            if any(n.name == target for n in code_graph.nodes.values()):
                continue
            # Otherwise → broken import candidate
            # Skip stdlib/third-party (no dot in name is likely stdlib)
            if "." not in target and not target.startswith("src/"):
                continue
            broken.append(target)

        return sorted(set(broken))

    def _find_unreachable(
        self,
        dep_graph: Any | None,
        entry_points: list[str],
        framework_entry_patterns: list[str] | None = None,
    ) -> list[str]:
        """
        Find files unreachable from entry points via DFS.

        Gemini fix: Test files are excluded from the unreachable list
        because they are never reachable from main entry points by design.
        Test files should be treated as secondary entry points.

        Framework-aware: Files matching framework entry patterns are also
        excluded since they are implicitly reachable via the framework.
        """
        if not dep_graph:
            return []

        # Build adjacency from forward graph
        adj: dict[str, set[str]] = {}
        all_files: set[str] = set()

        for src, deps in dep_graph._forward_graph.items():
            src_str = str(src)
            all_files.add(src_str)
            adj.setdefault(src_str, set()).update(str(d) for d in deps)
            for d in deps:
                all_files.add(str(d))

        # DFS from entry points
        reachable: set[str] = set()
        stack = list(entry_points)

        # Also seed with framework entry point files found in the project
        if framework_entry_patterns:
            for f in all_files:
                if _matches_framework_pattern(f, framework_entry_patterns):
                    stack.append(f)

        while stack:
            current = stack.pop()
            if current in reachable:
                continue
            reachable.add(current)
            for neighbor in adj.get(current, set()):
                if neighbor not in reachable:
                    stack.append(neighbor)

        # Unreachable = all files - reachable - test files (Gemini fix)
        unreachable = []
        for f in sorted(all_files - reachable):
            # Gemini fix: skip test files — they're entry points themselves
            if _TEST_PATH_RE.search(f):
                continue
            # Skip framework-managed files
            if framework_entry_patterns and _matches_framework_pattern(f, framework_entry_patterns):
                continue
            unreachable.append(f)

        return unreachable

    def _find_missing_mixin_impl(self, code_graph: CodeGraph) -> list[str]:
        """Find mixins/interfaces/ABCs that have zero implementors."""
        missing = []
        for fqn, node in code_graph.nodes.items():
            if node.kind not in (SymbolKind.MIXIN, SymbolKind.INTERFACE):
                continue
            implementors = code_graph.who_implements(fqn)
            inheritors = code_graph.who_inherits(fqn)
            if not implementors and not inheritors:
                missing.append(fqn)
        return sorted(missing)

    def _calculate_coverage(self, code_graph: CodeGraph) -> float:
        """Calculate what percentage of project files are in the code graph."""
        if not self._project_files:
            return 0.0

        graph_files = {node.file_path for node in code_graph.nodes.values()}
        covered = sum(1 for f in self._project_files if f in graph_files)
        return covered / len(self._project_files) if self._project_files else 0.0

    def _find_test_only_consumers(self, code_graph: CodeGraph) -> dict[str, list[str]]:
        """
        Y7: Find symbols that are ONLY used by test files.

        Returns dict mapping symbol FQN → list of test file consumers.
        """
        test_only: dict[str, list[str]] = {}

        for fqn, node in code_graph.nodes.items():
            if node.is_test:
                continue  # Skip test symbols themselves

            # Get all consumers (including tests)
            all_users = code_graph.who_uses(fqn, include_tests=True)
            non_test_users = code_graph.who_uses(fqn, include_tests=False)

            # If there are test users but no non-test users
            if all_users and not non_test_users:
                test_consumers = []
                for edge in all_users:
                    source_node = code_graph.nodes.get(edge.source)
                    if source_node and source_node.is_test:
                        test_consumers.append(source_node.file_path)
                if test_consumers:
                    test_only[fqn] = sorted(set(test_consumers))

        return test_only
