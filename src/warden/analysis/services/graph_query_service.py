"""
Graph Query Service.

Thin layer over CodeGraph that collects evidence for LLM-based
finding verification. Each gap type has a specialised evidence
collector that assembles the relevant graph neighbourhood.

Zero new dependencies — only wraps existing CodeGraph queries.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from warden.analysis.domain.code_graph import CodeGraph, GapReport

logger = structlog.get_logger(__name__)

# Gap types that benefit from LLM verification (FP-prone)
VERIFIABLE_GAP_TYPES = frozenset({
    "orphan_file",
    "unreachable",
    "missing_mixin_impl",
})


class GraphQueryService:
    """Collects graph evidence for LLM verification of architecture findings."""

    def __init__(
        self,
        code_graph: CodeGraph,
        gap_report: GapReport,
    ) -> None:
        self._graph = code_graph
        self._gap = gap_report

    def collect_evidence(
        self,
        finding_type: str,
        file_path: str,
    ) -> dict[str, Any]:
        """Collect graph-based evidence relevant to a specific finding type.

        Args:
            finding_type: One of the VERIFIABLE_GAP_TYPES.
            file_path: Relative file path the finding pertains to.

        Returns:
            Evidence dict ready for LLM prompt injection.
        """
        if finding_type == "orphan_file":
            return self._evidence_orphan(file_path)
        if finding_type == "unreachable":
            return self._evidence_unreachable(file_path)
        if finding_type == "missing_mixin_impl":
            return self._evidence_missing_mixin(file_path)
        return {}

    def format_as_prompt(self, evidence: dict[str, Any]) -> str:
        """Format collected evidence into a concise LLM prompt section."""
        if not evidence:
            return ""

        lines = ["[GRAPH EVIDENCE]:"]
        for key, value in evidence.items():
            if isinstance(value, list):
                lines.append(f"- {key}: {', '.join(str(v) for v in value[:10])}")
            else:
                lines.append(f"- {key}: {value}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Per-type evidence collectors
    # ------------------------------------------------------------------

    def _evidence_orphan(self, file_path: str) -> dict[str, Any]:
        """Evidence for an orphan file finding."""
        # Count direct references (who_uses for any symbol in this file)
        file_symbols = [
            n for n in self._graph.nodes.values()
            if n.file_path == file_path
        ]
        direct_refs = 0
        for sym in file_symbols:
            direct_refs += len(self._graph.who_uses(sym.fqn, include_tests=True))

        # Check for dynamic importers
        has_dynamic_importers = len(self._gap.dynamic_imports) > 0

        # Check if file is in star import targets
        has_star_importers = file_path in self._gap.star_imports

        # Framework info
        detected_framework = self._gap.detected_framework

        return {
            "direct_references_who_uses": direct_refs,
            "symbols_in_file": len(file_symbols),
            "project_has_dynamic_importers": has_dynamic_importers,
            "file_in_star_import_sources": has_star_importers,
            "detected_framework": detected_framework or "none",
            "dynamic_import_files": self._gap.dynamic_imports[:5],
        }

    def _evidence_unreachable(self, file_path: str) -> dict[str, Any]:
        """Evidence for an unreachable file finding."""
        # Find symbols defined in this file
        file_symbols = [
            n for n in self._graph.nodes.values()
            if n.file_path == file_path
        ]

        # Check if any symbol is used (even by tests)
        used_by_anyone = False
        test_users = 0
        for sym in file_symbols:
            uses = self._graph.who_uses(sym.fqn, include_tests=True)
            if uses:
                used_by_anyone = True
            test_uses = self._graph.who_uses(sym.fqn, include_tests=True)
            non_test_uses = self._graph.who_uses(sym.fqn, include_tests=False)
            test_users += len(test_uses) - len(non_test_uses)

        # Check dynamic imports in the project
        has_dynamic_importers = len(self._gap.dynamic_imports) > 0

        # Decorator metadata on symbols
        decorators: list[str] = []
        for sym in file_symbols:
            decs = sym.metadata.get("decorators", [])
            decorators.extend(decs)

        return {
            "symbols_in_file": len(file_symbols),
            "used_by_anyone": used_by_anyone,
            "test_only_users": test_users,
            "project_has_dynamic_importers": has_dynamic_importers,
            "detected_framework": self._gap.detected_framework or "none",
            "decorators_found": decorators[:10],
        }

    def _evidence_missing_mixin(self, file_path: str) -> dict[str, Any]:
        """Evidence for a missing mixin implementation finding."""
        # Find mixin/interface symbols in this file
        from warden.analysis.domain.code_graph import SymbolKind

        mixin_symbols = [
            n for n in self._graph.nodes.values()
            if n.file_path == file_path
            and n.kind in (SymbolKind.MIXIN, SymbolKind.INTERFACE)
        ]

        evidence: dict[str, Any] = {
            "mixin_count_in_file": len(mixin_symbols),
            "detected_framework": self._gap.detected_framework or "none",
        }

        # For each mixin, check inheritors/implementors (including by short name)
        for sym in mixin_symbols:
            inheritors = self._graph.who_inherits(sym.fqn)
            implementors = self._graph.who_implements(sym.fqn)
            # Also check by short name (cross-file resolution)
            by_name = self._graph.get_symbols_by_name(sym.name)
            evidence[f"mixin_{sym.name}"] = {
                "inheritors": len(inheritors),
                "implementors": len(implementors),
                "same_name_symbols": len(by_name),
                "bases": sym.bases,
            }

        return evidence
