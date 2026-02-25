"""
StaleSyncFrame — detects STALE_SYNC contract violations via DDG + LLM.

A STALE_SYNC occurs when two pipeline context fields are logically coupled
(usually updated together) but one is updated without the other in some
code paths, leaving them out of sync.

Detection algorithm:
1. ddg.co_write_candidates() → field pairs frequently written together
2. For each candidate, build a data flow context string
3. LLM verdict: stale_sync | intentional | unclear + confidence
4. confidence >= 0.5 and verdict == stale_sync → STALE_SYNC finding

This frame is ONLY active when contract_mode=True (opt-in).
LLM is required for the verdict step. Without LLM, all candidates are skipped.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
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

# Minimum co-write count to consider a pair a STALE_SYNC candidate
_MIN_CO_WRITES = 2

# LLM confidence threshold for reporting
_CONFIDENCE_THRESHOLD = 0.5

# Max candidates to send to LLM (avoid token explosion)
_MAX_CANDIDATES = 10

# Template path relative to the prompts/templates directory
_TEMPLATE_NAME = "data_flow_contract.txt"


def _load_template() -> str:
    """Load the data_flow_contract.txt prompt template."""
    template_dir = Path(__file__).parent.parent.parent.parent / "llm/prompts/templates"
    template_path = template_dir / _TEMPLATE_NAME
    if template_path.exists():
        return template_path.read_text(encoding="utf-8")
    # Fallback minimal template if file not found
    return (
        "Is this a STALE_SYNC? Field A: {field_a}, Field B: {field_b}. "
        'Respond: {{"verdict": "stale_sync"|"intentional"|"unclear", '
        '"confidence": 0.0, "reasoning": "..."}}'
    )


class StaleSyncFrame(ValidationFrame, DataFlowAware):
    """
    Detects STALE_SYNC contract violations.

    Finds field pairs that are usually written together but sometimes
    diverge, then asks LLM to verify if the divergence is a bug.

    This frame:
    - Requires DataFlowAware injection (DDG) to function
    - If DDG not injected -> graceful skip
    - Requires LLM service for verdict (without LLM, all candidates skip)
    - is_blocker=False (informational, v2.5.0 feature)
    - Runs once per project (first-call guard)
    """

    name: str = "Stale Sync Detector"
    description: str = "Detects STALE_SYNC contract violations via co-write pattern + LLM verdict"
    category: FrameCategory = FrameCategory.GLOBAL
    priority: FramePriority = FramePriority.MEDIUM
    scope: FrameScope = FrameScope.FILE_LEVEL
    is_blocker: bool = False
    supports_verification: bool = False

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self._ddg: DataDependencyGraph | None = None
        self._analyzed: bool = False
        self._template: str = _load_template()

    @property
    def frame_id(self) -> str:
        return "stale_sync"

    # DataFlowAware implementation
    def set_data_dependency_graph(self, ddg: DataDependencyGraph) -> None:
        """Inject the DataDependencyGraph into this frame."""
        self._ddg = ddg

    async def execute_async(self, code_file: CodeFile, context: PipelineContext | None = None) -> FrameResult:  # noqa: ARG002
        """
        Run STALE_SYNC analysis.

        NOTE: Like DeadDataFrame, this operates PROJECT-WIDE via the DDG.
        Only the first call runs analysis; subsequent calls return empty results.
        """
        start = time.monotonic()

        if self._ddg is None:
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

        # Step 1: Get co-write candidates from DDG
        candidates = self._ddg.co_write_candidates(min_co_writes=_MIN_CO_WRITES)

        if not candidates:
            return FrameResult(
                frame_id=self.frame_id,
                frame_name=self.name,
                status="passed",
                duration=time.monotonic() - start,
                issues_found=0,
                is_blocker=self.is_blocker,
                findings=[],
                metadata={"candidates_found": 0, "reason": "no_co_write_candidates"},
            )

        # Limit candidates to avoid token explosion
        candidate_items = list(candidates.items())[:_MAX_CANDIDATES]

        # Step 2: LLM verdict for each candidate
        finding_objects: list[Finding] = []
        analyzed_pairs: list[dict[str, Any]] = []
        llm_available = self._has_llm_service()

        for (field_a, field_b), info in candidate_items:
            verdict_info = await self._get_llm_verdict(field_a, field_b, info, llm_available)
            analyzed_pairs.append(
                {
                    "field_a": field_a,
                    "field_b": field_b,
                    "verdict": verdict_info.get("verdict"),
                    "confidence": verdict_info.get("confidence", 0.0),
                }
            )

            if (
                verdict_info.get("verdict") == "stale_sync"
                and verdict_info.get("confidence", 0.0) >= _CONFIDENCE_THRESHOLD
            ):
                finding_objects.append(self._make_finding(field_a, field_b, info, verdict_info))

        return FrameResult(
            frame_id=self.frame_id,
            frame_name=self.name,
            status="failed" if finding_objects else "passed",
            duration=time.monotonic() - start,
            issues_found=len(finding_objects),
            is_blocker=self.is_blocker,
            findings=finding_objects,
            metadata={
                "gap_type": "STALE_SYNC",
                "candidates_found": len(candidates),
                "candidates_analyzed": len(candidate_items),
                "llm_available": llm_available,
                "analyzed_pairs": analyzed_pairs,
            },
        )

    # -------------------------------------------------------------------------
    # LLM integration
    # -------------------------------------------------------------------------

    def _has_llm_service(self) -> bool:
        """Check if LLM service is available and ready."""
        return bool(getattr(self, "llm_service", None))

    async def _get_llm_verdict(
        self,
        field_a: str,
        field_b: str,
        info: dict[str, Any],
        llm_available: bool,
    ) -> dict[str, Any]:
        """
        Ask LLM if the diverging writes constitute a STALE_SYNC.

        Returns a dict with keys: verdict, confidence, reasoning.
        Returns {"verdict": "unclear", "confidence": 0.0} if LLM unavailable.
        """
        if not llm_available:
            return {"verdict": "unclear", "confidence": 0.0, "reasoning": "LLM not available"}

        co_write_funcs = info.get("co_write_funcs", [])
        a_only_writes = info.get("a_only_writes", [])
        b_only_writes = info.get("b_only_writes", [])

        # Format diverging write info
        a_only_funcs = [f"{w.func_name}@{w.file_path}:{w.line_no}" for w in a_only_writes[:5]]
        b_only_funcs = [f"{w.func_name}@{w.file_path}:{w.line_no}" for w in b_only_writes[:5]]

        prompt = self._template.format(
            field_a=field_a,
            field_b=field_b,
            co_write_count=len(co_write_funcs),
            co_write_funcs="\n".join(f"  - {f}" for f in co_write_funcs[:10]) or "  (none)",
            a_only_count=len(a_only_funcs),
            a_only_funcs="\n".join(f"  - {f}" for f in a_only_funcs) or "  (none)",
            b_only_count=len(b_only_funcs),
            b_only_funcs="\n".join(f"  - {f}" for f in b_only_funcs) or "  (none)",
        )

        try:
            response = await self.llm_service.complete_async(  # type: ignore[attr-defined]
                prompt=prompt,
                system_prompt=(
                    "You are a software architect. Respond only with a JSON object. "
                    "No markdown, no code blocks, no extra text."
                ),
                use_fast_tier=False,
            )
            raw = response.content if hasattr(response, "content") else str(response)
            return self._parse_verdict(raw)
        except Exception:
            return {"verdict": "unclear", "confidence": 0.0, "reasoning": "LLM call failed"}

    def _parse_verdict(self, raw: str) -> dict[str, Any]:
        """Parse LLM JSON response into a verdict dict."""
        try:
            # Strip markdown code fences if present
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                lines = cleaned.split("\n")
                cleaned = "\n".join(lines[1:-1]) if len(lines) > 2 else cleaned

            data = json.loads(cleaned)
            verdict = data.get("verdict", "unclear")
            confidence = float(data.get("confidence", 0.0))
            reasoning = str(data.get("reasoning", ""))

            if verdict not in ("stale_sync", "intentional", "unclear"):
                verdict = "unclear"
            confidence = max(0.0, min(1.0, confidence))

            return {"verdict": verdict, "confidence": confidence, "reasoning": reasoning}
        except (json.JSONDecodeError, ValueError, TypeError):
            return {"verdict": "unclear", "confidence": 0.0, "reasoning": f"parse_error: {raw[:100]}"}

    # -------------------------------------------------------------------------
    # Finding construction
    # -------------------------------------------------------------------------

    def _make_finding(
        self,
        field_a: str,
        field_b: str,
        info: dict[str, Any],
        verdict_info: dict[str, Any],
    ) -> Finding:
        """Create a STALE_SYNC Finding."""
        co_write_funcs = info.get("co_write_funcs", [])
        a_only_writes = info.get("a_only_writes", [])
        b_only_writes = info.get("b_only_writes", [])

        # Determine primary diverging location for finding
        primary_write = (a_only_writes or b_only_writes or [None])[0]
        location = f"{primary_write.file_path}:{primary_write.line_no}" if primary_write else "unknown"

        safe_a = field_a.replace(".", "-").replace("_", "-").upper()
        safe_b = field_b.replace(".", "-").replace("_", "-").upper()
        finding_id = f"CONTRACT-STALE-SYNC-{safe_a}-{safe_b}"

        confidence = verdict_info.get("confidence", 0.0)
        reasoning = verdict_info.get("reasoning", "")

        message = (
            f"[STALE_SYNC] Fields '{field_a}' and '{field_b}' are co-written in "
            f"{len(co_write_funcs)} function(s) but diverge: "
            f"{len(a_only_writes)} site(s) update only '{field_a}', "
            f"{len(b_only_writes)} site(s) update only '{field_b}' "
            f"(LLM confidence: {confidence:.2f})"
        )

        detail_lines = [
            f"Field A: {field_a}",
            f"Field B: {field_b}",
            f"Co-write functions: {', '.join(co_write_funcs[:5])}",
        ]
        if a_only_writes:
            detail_lines.append(
                f"'{field_a}' written without '{field_b}': "
                + ", ".join(f"{w.func_name}:{w.line_no}" for w in a_only_writes[:3])
            )
        if b_only_writes:
            detail_lines.append(
                f"'{field_b}' written without '{field_a}': "
                + ", ".join(f"{w.func_name}:{w.line_no}" for w in b_only_writes[:3])
            )
        if reasoning:
            detail_lines.append(f"LLM reasoning: {reasoning}")

        return Finding(
            id=finding_id,
            severity="high",
            message=message,
            location=location,
            detail="\n".join(detail_lines),
            line=primary_write.line_no if primary_write else 0,
            is_blocker=False,
        )
