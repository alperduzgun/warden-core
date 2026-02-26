"""
Architecture Frame - Structural gap detection from CodeGraph analysis.

Detects architectural gaps such as broken imports, circular dependencies,
orphan files, unreachable code, and missing mixin implementations.

Uses data from GapReport (populated in Phase 0.7) — no LLM calls by default.
Pure data transformation from pre-computed analysis results.

Opt-in LLM verification (use_llm_verification config) uses GraphQueryService
to collect evidence and LLM fast-tier to filter false positives on FP-prone
gap types (orphan, unreachable, missing_mixin).

Priority: HIGH
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from warden.shared.infrastructure.logging import get_logger
from warden.validation.domain.enums import (
    FrameApplicability,
    FrameCategory,
    FramePriority,
    FrameScope,
)
from warden.validation.domain.frame import (
    CodeFile,
    Finding,
    FrameResult,
    ValidationFrame,
)
from warden.validation.domain.mixins import CodeGraphAware

if TYPE_CHECKING:
    from warden.analysis.domain.code_graph import CodeGraph, GapReport
    from warden.analysis.services.graph_query_service import GraphQueryService
    from warden.pipeline.domain.pipeline_context import PipelineContext

logger = get_logger(__name__)

# Gap types eligible for LLM verification (FP-prone)
_LLM_VERIFIABLE_TYPES = frozenset({"orphan_file", "unreachable", "missing_mixin_impl"})

_LLM_VERIFICATION_PROMPT = """\
You are a Senior Code Architect. Determine if the following static analysis finding is a TRUE POSITIVE or FALSE POSITIVE.

Finding: {message}
File: {file_path}

{evidence}

{file_header}

QUESTION: Is this finding a true positive or false positive?
Return ONLY a JSON object: {{"is_true_positive": bool, "confidence": float, "reason": "..."}}
"""


@dataclass
class FileGaps:
    """Architectural gaps attributed to a single file."""

    broken_imports: list[str] = field(default_factory=list)
    in_circular_dep: list[list[str]] = field(default_factory=list)
    is_orphan: bool = False
    is_unreachable: bool = False
    is_unparseable: bool = False
    missing_mixin_impls: list[str] = field(default_factory=list)
    has_star_imports: bool = False
    has_dynamic_imports: bool = False


# Severity mapping for gap types
_SEVERITY_MAP: dict[str, str] = {
    "broken_import": "high",
    "circular_dep": "medium",
    "unparseable": "high",
    "missing_mixin_impl": "medium",
    "orphan_file": "low",
    "unreachable": "low",
    "star_import": "low",
    "dynamic_import": "low",
}

# Human-readable messages for gap types
_MESSAGE_MAP: dict[str, str] = {
    "broken_import": "Broken import: target '{}' cannot be resolved in the codebase",
    "circular_dep": "Circular dependency detected: {}",
    "unparseable": "File could not be parsed for static analysis",
    "missing_mixin_impl": "Mixin/ABC '{}' defined here has no implementors",
    "orphan_file": "Orphan file: no dependencies and no dependents",
    "unreachable": "File is unreachable from any entry point",
    "star_import": "Star import (from ... import *) limits static analysis",
    "dynamic_import": "Dynamic import limits static analysis",
}

# Detail/suggestion text for gap types
_DETAIL_MAP: dict[str, str] = {
    "broken_import": (
        "This file imports a module or symbol that does not exist in the project graph. "
        "Possible causes: deleted module, typo in import path, or third-party dependency "
        "not tracked. Fix the import or add the missing module."
    ),
    "circular_dep": (
        "This file is part of a circular dependency chain. Circular deps can cause "
        "import errors, hard-to-debug initialization order issues, and tight coupling. "
        "Consider extracting shared interfaces or using dependency injection."
    ),
    "unparseable": (
        "This file could not be parsed by the AST analyzer. "
        "It may contain syntax errors or unsupported constructs. "
        "No static analysis was performed on this file."
    ),
    "missing_mixin_impl": (
        "A mixin or abstract base class defined in this file has zero implementations. "
        "Either implement it or remove the dead abstraction."
    ),
    "orphan_file": (
        "This file has no import relationships with the rest of the codebase. "
        "It may be unused dead code. Consider removing it or integrating it."
    ),
    "unreachable": (
        "No execution path from any entry point reaches this file. "
        "It may be dead code or only reachable through dynamic imports. "
        "Consider removing it or adding an explicit entry point."
    ),
    "star_import": (
        "Star imports (from X import *) prevent accurate static analysis of symbol usage. "
        "Replace with explicit imports for better analysis coverage."
    ),
    "dynamic_import": (
        "Dynamic imports (importlib, __import__) cannot be resolved statically. "
        "This limits the accuracy of dependency and dead-code analysis."
    ),
}


class ArchitectureFrame(ValidationFrame, CodeGraphAware):
    """
    Architecture validation frame — detects structural gaps from CodeGraph.

    Transforms pre-computed GapReport data into per-file Finding objects.
    No LLM calls, no AST parsing — pure O(1) lookup per file after
    one-time O(N) index build on first invocation.
    """

    name = "Architecture Analysis"
    description = "Detects architectural gaps from CodeGraph: broken imports, circular deps, orphan files"
    category = FrameCategory.GLOBAL
    priority = FramePriority.HIGH
    scope = FrameScope.PROJECT_LEVEL
    is_blocker = False
    supports_verification = False  # Structural gap analysis from CodeGraph — not a security finding
    version = "1.0.0"
    author = "Warden Team"
    applicability = [FrameApplicability.ALL]

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self._file_gap_map: dict[str, FileGaps] | None = None
        self._build_attempted: bool = False
        self._graph_query_service: GraphQueryService | None = None
        self._use_llm_verification: bool = (config or {}).get("use_llm_verification", False)

        # CodeGraphAware: injected by FrameRunner before execution
        self._code_graph: CodeGraph | None = None
        self._gap_report: GapReport | None = None

    def set_code_graph(self, code_graph: Any, gap_report: Any) -> None:
        """CodeGraphAware implementation -- receive CodeGraph and GapReport."""
        self._code_graph = code_graph
        self._gap_report = gap_report

    async def execute_async(
        self,
        code_file: CodeFile,
        context: PipelineContext | None = None,
    ) -> FrameResult:
        start_time = time.perf_counter()

        # Lazy-build the file gap map on first call
        if not self._build_attempted:
            self._build_attempted = True
            # Prefer mixin-injected data; fall back to context for compatibility
            gap_report = self._gap_report or (getattr(context, "gap_report", None) if context else None)
            code_graph = self._code_graph or (getattr(context, "code_graph", None) if context else None)
            if gap_report is not None:
                self._file_gap_map = _build_file_gap_map(gap_report, code_graph)
                logger.info(
                    "architecture_gap_map_built",
                    files_with_gaps=len(self._file_gap_map),
                )
                # Initialise GraphQueryService for LLM verification
                if self._use_llm_verification and code_graph is not None:
                    try:
                        from warden.analysis.services.graph_query_service import (
                            GraphQueryService,
                        )

                        self._graph_query_service = GraphQueryService(code_graph, gap_report)
                    except Exception as e:
                        logger.warning("graph_query_service_init_failed", error=str(e))

        # No gap data available — graceful no-op
        if self._file_gap_map is None:
            return FrameResult(
                frame_id=self.frame_id,
                frame_name=self.name,
                status="passed",
                duration=time.perf_counter() - start_time,
                issues_found=0,
                is_blocker=False,
                findings=[],
                metadata={"reason": "no_gap_report"},
            )

        # O(1) lookup for this file
        norm_path = os.path.normpath(code_file.path)
        gaps = self._file_gap_map.get(norm_path)

        # Also try without leading src/ prefix for path normalization
        if gaps is None and norm_path.startswith("src" + os.sep):
            gaps = self._file_gap_map.get(norm_path[4:])  # len("src/") == 4
        if gaps is None and not norm_path.startswith("src" + os.sep):
            gaps = self._file_gap_map.get("src" + os.sep + norm_path)

        if gaps is None:
            return FrameResult(
                frame_id=self.frame_id,
                frame_name=self.name,
                status="passed",
                duration=time.perf_counter() - start_time,
                issues_found=0,
                is_blocker=False,
                findings=[],
            )

        findings = _gaps_to_findings(gaps, code_file, self.frame_id)

        # Opt-in: LLM verification for FP-prone findings
        if self._use_llm_verification and self._graph_query_service is not None and context is not None and findings:
            findings = await self._verify_findings_with_llm(findings, code_file, context)

        status = "passed"
        if any(f.severity in ("critical", "high") for f in findings) or findings:
            status = "warning"

        return FrameResult(
            frame_id=self.frame_id,
            frame_name=self.name,
            status=status,
            duration=time.perf_counter() - start_time,
            issues_found=len(findings),
            is_blocker=False,
            findings=findings,
            metadata={
                "broken_imports": len(gaps.broken_imports),
                "circular_deps": len(gaps.in_circular_dep),
                "is_orphan": gaps.is_orphan,
                "is_unreachable": gaps.is_unreachable,
                "is_unparseable": gaps.is_unparseable,
                "missing_mixin_impls": len(gaps.missing_mixin_impls),
                "has_star_imports": gaps.has_star_imports,
                "has_dynamic_imports": gaps.has_dynamic_imports,
                "llm_verified": self._use_llm_verification,
            },
        )

    async def _verify_findings_with_llm(
        self,
        findings: list[Finding],
        code_file: CodeFile,
        context: Any,
    ) -> list[Finding]:
        """Filter FP-prone findings using LLM with graph evidence.

        Only orphan_file, unreachable, and missing_mixin_impl findings
        are sent through LLM verification. All other finding types pass
        through unmodified.

        Returns:
            Filtered list with false positives removed.
        """
        llm_service = getattr(context, "llm_service", None)
        if llm_service is None:
            return findings

        verified: list[Finding] = []
        for finding in findings:
            gap_type = _finding_id_to_gap_type(finding.id)
            if gap_type not in _LLM_VERIFIABLE_TYPES:
                # Non-verifiable types pass through
                verified.append(finding)
                continue

            try:
                evidence = self._graph_query_service.collect_evidence(gap_type, code_file.path)
                evidence_str = self._graph_query_service.format_as_prompt(evidence)

                # Read first few lines for context
                file_header = ""
                if code_file.content:
                    header_lines = code_file.content.split("\n")[:10]
                    file_header = "File starts with:\n" + "\n".join(header_lines)

                prompt = _LLM_VERIFICATION_PROMPT.format(
                    message=finding.message,
                    file_path=code_file.path,
                    evidence=evidence_str,
                    file_header=file_header,
                )

                response = await llm_service.complete_async(
                    prompt,
                    system_prompt="You are a code architecture analyst. Return only valid JSON.",
                    use_fast_tier=True,
                    max_tokens=200,
                )

                if response and hasattr(response, "content") and response.content:
                    verdict = _parse_llm_verdict(response.content)
                    if verdict.get("is_true_positive", True):
                        verified.append(finding)
                    else:
                        logger.info(
                            "architecture_finding_filtered_by_llm",
                            finding_id=finding.id,
                            reason=verdict.get("reason", ""),
                            confidence=verdict.get("confidence", 0),
                        )
                else:
                    # LLM failed — keep finding (fail-open)
                    verified.append(finding)

            except Exception as e:
                logger.warning(
                    "architecture_llm_verification_error",
                    finding_id=finding.id,
                    error=str(e),
                )
                verified.append(finding)  # Fail-open

        return verified


def _build_file_gap_map(
    gap_report: GapReport,
    code_graph: CodeGraph | None,
) -> dict[str, FileGaps]:
    """
    Build a mapping from file path to FileGaps by attributing each gap
    to its source file.

    Returns:
        Dict mapping normalized file paths to their FileGaps.
    """
    file_map: dict[str, FileGaps] = {}

    def _ensure(path: str) -> FileGaps:
        norm = os.path.normpath(path)
        if norm not in file_map:
            file_map[norm] = FileGaps()
        return file_map[norm]

    # --- Direct file-level gaps ---

    for fp in gap_report.orphan_files:
        _ensure(fp).is_orphan = True

    for fp in gap_report.unreachable_from_entry:
        _ensure(fp).is_unreachable = True

    for fp in gap_report.unparseable_files:
        _ensure(fp).is_unparseable = True

    for fp in gap_report.star_imports:
        _ensure(fp).has_star_imports = True

    for fp in gap_report.dynamic_imports:
        _ensure(fp).has_dynamic_imports = True

    # --- Broken imports: attribute to the SOURCE file doing the import ---
    if code_graph is not None:
        broken_set = set(gap_report.broken_imports)
        if broken_set:
            from warden.analysis.domain.code_graph import EdgeRelation

            for edge in code_graph.edges:
                if edge.relation != EdgeRelation.IMPORTS:
                    continue
                if edge.target not in broken_set:
                    continue
                # Find source node's file_path
                source_node = code_graph.nodes.get(edge.source)
                if source_node and source_node.file_path:
                    _ensure(source_node.file_path).broken_imports.append(edge.target)

    # --- Circular deps: attribute to each file in the cycle ---
    if code_graph is not None:
        for cycle in gap_report.circular_deps:
            cycle_files: set[str] = set()
            for fqn in cycle:
                node = code_graph.nodes.get(fqn)
                if node and node.file_path:
                    cycle_files.add(node.file_path)
            for fp in cycle_files:
                _ensure(fp).in_circular_dep.append(cycle)
    else:
        # Without code_graph, try to treat cycle entries as file paths
        for cycle in gap_report.circular_deps:
            for entry in cycle:
                if os.sep in entry or entry.endswith(".py"):
                    _ensure(entry).in_circular_dep.append(cycle)

    # --- Missing mixin implementations: attribute to the file defining the mixin ---
    if code_graph is not None:
        for fqn in gap_report.missing_mixin_impl:
            node = code_graph.nodes.get(fqn)
            if node and node.file_path:
                _ensure(node.file_path).missing_mixin_impls.append(fqn)

    return file_map


def _gaps_to_findings(
    gaps: FileGaps,
    code_file: CodeFile,
    frame_id: str,
) -> list[Finding]:
    """Convert a FileGaps into a list of Finding objects for one file."""
    findings: list[Finding] = []
    idx = 0

    for target_fqn in gaps.broken_imports:
        findings.append(
            Finding(
                id=f"{frame_id}-broken-import-{idx}",
                severity=_SEVERITY_MAP["broken_import"],
                message=_MESSAGE_MAP["broken_import"].format(target_fqn),
                location=f"{code_file.path}:1",
                detail=_DETAIL_MAP["broken_import"],
                line=1,
            )
        )
        idx += 1

    for cycle in gaps.in_circular_dep:
        cycle_str = " -> ".join(cycle)
        findings.append(
            Finding(
                id=f"{frame_id}-circular-dep-{idx}",
                severity=_SEVERITY_MAP["circular_dep"],
                message=_MESSAGE_MAP["circular_dep"].format(cycle_str),
                location=f"{code_file.path}:1",
                detail=_DETAIL_MAP["circular_dep"],
                line=1,
            )
        )
        idx += 1

    if gaps.is_unparseable:
        findings.append(
            Finding(
                id=f"{frame_id}-unparseable-{idx}",
                severity=_SEVERITY_MAP["unparseable"],
                message=_MESSAGE_MAP["unparseable"],
                location=f"{code_file.path}:1",
                detail=_DETAIL_MAP["unparseable"],
                line=1,
            )
        )
        idx += 1

    for fqn in gaps.missing_mixin_impls:
        short_name = fqn.split("::")[-1] if "::" in fqn else fqn
        findings.append(
            Finding(
                id=f"{frame_id}-missing-mixin-impl-{idx}",
                severity=_SEVERITY_MAP["missing_mixin_impl"],
                message=_MESSAGE_MAP["missing_mixin_impl"].format(short_name),
                location=f"{code_file.path}:1",
                detail=_DETAIL_MAP["missing_mixin_impl"],
                line=1,
            )
        )
        idx += 1

    if gaps.is_orphan:
        findings.append(
            Finding(
                id=f"{frame_id}-orphan-file-{idx}",
                severity=_SEVERITY_MAP["orphan_file"],
                message=_MESSAGE_MAP["orphan_file"],
                location=f"{code_file.path}:1",
                detail=_DETAIL_MAP["orphan_file"],
                line=1,
            )
        )
        idx += 1

    if gaps.is_unreachable:
        findings.append(
            Finding(
                id=f"{frame_id}-unreachable-{idx}",
                severity=_SEVERITY_MAP["unreachable"],
                message=_MESSAGE_MAP["unreachable"],
                location=f"{code_file.path}:1",
                detail=_DETAIL_MAP["unreachable"],
                line=1,
            )
        )
        idx += 1

    if gaps.has_star_imports:
        findings.append(
            Finding(
                id=f"{frame_id}-star-import-{idx}",
                severity=_SEVERITY_MAP["star_import"],
                message=_MESSAGE_MAP["star_import"],
                location=f"{code_file.path}:1",
                detail=_DETAIL_MAP["star_import"],
                line=1,
            )
        )
        idx += 1

    if gaps.has_dynamic_imports:
        findings.append(
            Finding(
                id=f"{frame_id}-dynamic-import-{idx}",
                severity=_SEVERITY_MAP["dynamic_import"],
                message=_MESSAGE_MAP["dynamic_import"],
                location=f"{code_file.path}:1",
                detail=_DETAIL_MAP["dynamic_import"],
                line=1,
            )
        )
        idx += 1

    return findings


def _finding_id_to_gap_type(finding_id: str) -> str:
    """Extract gap type from a finding ID like 'architecture-orphan-file-0'."""
    # Strip frame prefix and trailing index
    parts = finding_id.split("-")
    if len(parts) >= 3:
        # Join middle parts: "orphan-file", "broken-import", "circular-dep", etc.
        gap_key = "-".join(parts[1:-1])
        # Normalise to underscore style matching _LLM_VERIFIABLE_TYPES
        return gap_key.replace("-", "_")
    return ""


def _parse_llm_verdict(content: str) -> dict[str, Any]:
    """Parse LLM JSON response, handling markdown code fences."""
    text = content.strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return {"is_true_positive": True, "confidence": 0.5, "reason": "parse_error"}
