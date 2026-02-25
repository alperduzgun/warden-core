"""
DeadDataFrame — detects DEAD_WRITE, MISSING_WRITE, NEVER_POPULATED contract violations.

This frame is ONLY active when contract_mode=True (opt-in).
It operates on project-wide DataDependencyGraph, not per-file analysis.
No LLM required — pure deterministic analysis.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from warden.validation.domain.enums import (
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
from warden.validation.domain.mixins import DataFlowAware

if TYPE_CHECKING:
    from warden.analysis.domain.data_dependency_graph import DataDependencyGraph
    from warden.pipeline.domain.pipeline_context import PipelineContext


# Severity mapping per gap type
_GAP_SEVERITY: dict[str, str] = {
    "DEAD_WRITE": "medium",
    "MISSING_WRITE": "high",
    "NEVER_POPULATED": "medium",
}


class DeadDataFrame(ValidationFrame, DataFlowAware):
    """
    Detects data flow contract violations using the DataDependencyGraph.

    Gap types:
    - DEAD_WRITE: context field written but never read anywhere
    - MISSING_WRITE: context field read but never written anywhere
    - NEVER_POPULATED: Optional field declared in PipelineContext but never written

    This frame:
    - Requires DataFlowAware injection to function
    - If DDG not injected -> graceful skip (status="passed", issues_found=0)
    - is_blocker=False (non-blocking, informational)
    - No LLM calls
    """

    name: str = "Dead Data Detector"
    description: str = "Detects DEAD_WRITE, MISSING_WRITE, NEVER_POPULATED contract violations"
    category: FrameCategory = FrameCategory.GLOBAL
    priority: FramePriority = FramePriority.LOW
    scope: FrameScope = FrameScope.FILE_LEVEL
    is_blocker: bool = False
    supports_verification: bool = False  # Findings are structural, not security-focused

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self._ddg: DataDependencyGraph | None = None
        self._analyzed: bool = False

    @property
    def frame_id(self) -> str:
        return "dead_data"

    # DataFlowAware implementation
    def set_data_dependency_graph(self, ddg: DataDependencyGraph) -> None:
        """Inject the DataDependencyGraph into this frame."""
        self._ddg = ddg

    async def execute_async(self, code_file: CodeFile, context: PipelineContext | None = None) -> FrameResult:
        """
        Run contract analysis.

        NOTE: This frame operates on the PROJECT-WIDE DDG, not per-file.
        The code_file argument is used only for FrameResult construction.
        Only runs analysis on the FIRST file call (guard: self._analyzed).
        Subsequent calls return passed with 0 issues.
        """
        start = time.monotonic()

        if self._ddg is None:
            # No DDG injected — graceful skip
            return FrameResult(
                frame_id=self.frame_id,
                frame_name=self.name,
                status="passed",
                duration=time.monotonic() - start,
                issues_found=0,
                is_blocker=self.is_blocker,
                findings=[],
                metadata={"skipped": True, "reason": "DDG not injected"},
            )

        if self._analyzed:
            # Already ran — subsequent files get empty result
            return FrameResult(
                frame_id=self.frame_id,
                frame_name=self.name,
                status="passed",
                duration=time.monotonic() - start,
                issues_found=0,
                is_blocker=self.is_blocker,
                findings=[],
                metadata={"skipped": True, "reason": "already_analyzed"},
            )

        self._analyzed = True
        findings_dicts: list[dict[str, Any]] = []
        findings_dicts.extend(self._analyze_dead_writes())
        findings_dicts.extend(self._analyze_missing_writes())
        findings_dicts.extend(self._analyze_never_populated())

        # Convert finding dicts to Finding objects
        finding_objects = [self._dict_to_finding(f) for f in findings_dicts]

        return FrameResult(
            frame_id=self.frame_id,
            frame_name=self.name,
            status="failed" if finding_objects else "passed",
            duration=time.monotonic() - start,
            issues_found=len(finding_objects),
            is_blocker=self.is_blocker,
            findings=finding_objects,
            metadata={
                "gap_types_checked": ["DEAD_WRITE", "MISSING_WRITE", "NEVER_POPULATED"],
                "dead_write_count": sum(1 for f in findings_dicts if f.get("gap_type") == "DEAD_WRITE"),
                "missing_write_count": sum(1 for f in findings_dicts if f.get("gap_type") == "MISSING_WRITE"),
                "never_populated_count": sum(1 for f in findings_dicts if f.get("gap_type") == "NEVER_POPULATED"),
            },
        )

    def _analyze_dead_writes(self) -> list[dict[str, Any]]:
        """Returns list of Finding dicts for DEAD_WRITE gaps."""
        assert self._ddg is not None
        findings = []
        for field_name, write_nodes in self._ddg.dead_writes().items():
            first_write = write_nodes[0]
            details = {
                "write_locations": [
                    {"file": w.file_path, "line": w.line_no, "func": w.func_name, "conditional": w.is_conditional}
                    for w in write_nodes
                ],
                "read_locations": [],
            }
            findings.append(
                self._make_finding(
                    gap_type="DEAD_WRITE",
                    field_name=field_name,
                    file_path=first_write.file_path,
                    line_no=first_write.line_no,
                    details=details,
                )
            )
        return findings

    def _analyze_missing_writes(self) -> list[dict[str, Any]]:
        """Returns list of Finding dicts for MISSING_WRITE gaps."""
        assert self._ddg is not None
        findings = []
        for field_name, read_nodes in self._ddg.missing_writes().items():
            first_read = read_nodes[0]
            details = {
                "write_locations": [],
                "read_locations": [{"file": r.file_path, "line": r.line_no, "func": r.func_name} for r in read_nodes],
            }
            findings.append(
                self._make_finding(
                    gap_type="MISSING_WRITE",
                    field_name=field_name,
                    file_path=first_read.file_path,
                    line_no=first_read.line_no,
                    details=details,
                )
            )
        return findings

    def _analyze_never_populated(self) -> list[dict[str, Any]]:
        """Returns list of Finding dicts for NEVER_POPULATED gaps."""
        assert self._ddg is not None
        findings = []
        for field_name in sorted(self._ddg.never_populated()):
            details: dict[str, Any] = {
                "write_locations": [],
                "read_locations": [],
                "note": "Field declared in PipelineContext but never assigned a value",
            }
            findings.append(
                self._make_finding(
                    gap_type="NEVER_POPULATED",
                    field_name=field_name,
                    file_path="pipeline_context.py",
                    line_no=0,
                    details=details,
                )
            )
        return findings

    def _make_finding(
        self,
        gap_type: str,
        field_name: str,
        file_path: str,
        line_no: int,
        details: dict[str, Any],
    ) -> dict[str, Any]:
        """Create a standardized Finding dict."""
        safe_field = field_name.replace(".", "-").replace("_", "-").upper()
        severity = _GAP_SEVERITY.get(gap_type, "medium")

        message_templates = {
            "DEAD_WRITE": f"[DEAD_WRITE] context field '{field_name}' is written but never read anywhere",
            "MISSING_WRITE": f"[MISSING_WRITE] context field '{field_name}' is read but never written anywhere",
            "NEVER_POPULATED": (
                f"[NEVER_POPULATED] context field '{field_name}' is declared in PipelineContext"
                " but never assigned a value"
            ),
        }

        return {
            "id": f"CONTRACT-{gap_type.replace('_', '-')}-{safe_field}",
            "type": "contract_violation",
            "gap_type": gap_type,
            "severity": severity,
            "message": message_templates.get(gap_type, f"[{gap_type}] contract violation on '{field_name}'"),
            "field_name": field_name,
            "file": file_path,
            "line": line_no,
            "details": details,
            "frame": self.frame_id,
            "category": "contract_violation",
            "confidence": 0.95,
        }

    def _dict_to_finding(self, d: dict[str, Any]) -> Finding:
        """Convert a finding dict to a Finding dataclass."""
        location = f"{d.get('file', 'unknown')}:{d.get('line', 0)}"
        return Finding(
            id=d["id"],
            severity=d["severity"],
            message=d["message"],
            location=location,
            detail=str(d.get("details", "")),
            line=d.get("line", 0),
            is_blocker=False,
        )
