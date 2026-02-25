"""
Tests for StaleSyncFrame.

Tests cover:
- DDG not injected → graceful skip
- already_analyzed guard
- No co-write candidates → skip
- LLM not available → all candidates produce unclear/skip
- LLM returns stale_sync + confidence >= 0.5 → finding
- LLM returns intentional → no finding
- LLM returns unclear/low confidence → no finding
- JSON parse errors in LLM response → graceful degradation
- Multiple candidates → findings only for confirmed pairs
- co_write_candidates() integration
- _parse_verdict edge cases
"""

from __future__ import annotations

import json
from collections import defaultdict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from warden.analysis.domain.data_dependency_graph import DataDependencyGraph, WriteNode
from warden.validation.domain.frame import CodeFile
from warden.validation.frames.stale_sync.stale_sync_frame import (
    StaleSyncFrame,
    _CONFIDENCE_THRESHOLD,
    _MIN_CO_WRITES,
)


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


def _make_code_file(path: str = "/project/src/foo.py") -> CodeFile:
    return CodeFile(path=path, content="", language="python")


def _make_ddg_with_co_writes() -> DataDependencyGraph:
    """DDG with a genuine STALE_SYNC candidate: findings + validated_issues."""
    ddg = DataDependencyGraph(
        writes=defaultdict(list),
        reads=defaultdict(list),
        init_fields=set(),
    )
    # findings and validated_issues written together in 3 functions
    for func in ["aggregate", "store_results", "finalize"]:
        ddg.writes["context.findings"].append(WriteNode("context.findings", "result_aggregator.py", 10, func, False))
        ddg.writes["context.validated_issues"].append(
            WriteNode("context.validated_issues", "result_aggregator.py", 11, func, False)
        )

    # But also: findings written alone in one extra function (diverging)
    ddg.writes["context.findings"].append(
        WriteNode("context.findings", "post_processor.py", 55, "filter_findings", False)
    )
    return ddg


def _make_ddg_no_candidates() -> DataDependencyGraph:
    """DDG where no pair has >= _MIN_CO_WRITES co-write functions."""
    ddg = DataDependencyGraph(
        writes=defaultdict(list),
        reads=defaultdict(list),
        init_fields=set(),
    )
    ddg.writes["context.findings"].append(WriteNode("context.findings", "agg.py", 1, "func_a", False))
    ddg.writes["context.validated_issues"].append(WriteNode("context.validated_issues", "agg.py", 2, "func_b", False))
    # No co-writes at all (each in a different function)
    return ddg


def _make_mock_llm(verdict: str, confidence: float, reasoning: str = "test") -> MagicMock:
    """Create a mock LLM service returning the given verdict."""
    response = MagicMock()
    response.content = json.dumps(
        {
            "verdict": verdict,
            "confidence": confidence,
            "reasoning": reasoning,
        }
    )
    mock_llm = AsyncMock()
    mock_llm.complete_async = AsyncMock(return_value=response)
    return mock_llm


# ---------------------------------------------------------------------------
# Unit: _parse_verdict
# ---------------------------------------------------------------------------


class TestParseVerdict:
    def test_valid_stale_sync(self):
        frame = StaleSyncFrame()
        raw = '{"verdict": "stale_sync", "confidence": 0.85, "reasoning": "fields are coupled"}'
        result = frame._parse_verdict(raw)
        assert result["verdict"] == "stale_sync"
        assert result["confidence"] == pytest.approx(0.85)

    def test_valid_intentional(self):
        frame = StaleSyncFrame()
        raw = '{"verdict": "intentional", "confidence": 0.9, "reasoning": "different purposes"}'
        result = frame._parse_verdict(raw)
        assert result["verdict"] == "intentional"

    def test_valid_unclear(self):
        frame = StaleSyncFrame()
        raw = '{"verdict": "unclear", "confidence": 0.3, "reasoning": "cannot determine"}'
        result = frame._parse_verdict(raw)
        assert result["verdict"] == "unclear"

    def test_invalid_verdict_normalized_to_unclear(self):
        frame = StaleSyncFrame()
        raw = '{"verdict": "bug", "confidence": 0.9}'
        result = frame._parse_verdict(raw)
        assert result["verdict"] == "unclear"

    def test_confidence_clamped_to_0_1(self):
        frame = StaleSyncFrame()
        raw = '{"verdict": "stale_sync", "confidence": 2.5}'
        result = frame._parse_verdict(raw)
        assert result["confidence"] == 1.0

        raw2 = '{"verdict": "stale_sync", "confidence": -0.5}'
        result2 = frame._parse_verdict(raw2)
        assert result2["confidence"] == 0.0

    def test_json_parse_error_returns_unclear(self):
        frame = StaleSyncFrame()
        result = frame._parse_verdict("not json at all {{{{")
        assert result["verdict"] == "unclear"
        assert result["confidence"] == 0.0

    def test_strips_markdown_code_fence(self):
        frame = StaleSyncFrame()
        raw = '```json\n{"verdict": "stale_sync", "confidence": 0.7, "reasoning": "ok"}\n```'
        result = frame._parse_verdict(raw)
        assert result["verdict"] == "stale_sync"
        assert result["confidence"] == pytest.approx(0.7)

    def test_missing_keys_use_defaults(self):
        frame = StaleSyncFrame()
        raw = '{"verdict": "stale_sync"}'
        result = frame._parse_verdict(raw)
        assert result["confidence"] == 0.0
        assert result["reasoning"] == ""


# ---------------------------------------------------------------------------
# Integration: execute_async
# ---------------------------------------------------------------------------


class TestStaleSyncFrameExecute:
    @pytest.mark.asyncio
    async def test_ddg_not_injected_graceful_skip(self):
        frame = StaleSyncFrame()
        result = await frame.execute_async(_make_code_file())
        assert result.status == "passed"
        assert result.issues_found == 0
        assert result.metadata.get("reason") == "DDG not injected"

    @pytest.mark.asyncio
    async def test_already_analyzed_guard(self):
        frame = StaleSyncFrame()
        frame.set_data_dependency_graph(_make_ddg_with_co_writes())
        await frame.execute_async(_make_code_file())  # First call
        second = await frame.execute_async(_make_code_file())
        assert second.metadata.get("reason") == "already_analyzed"
        assert second.issues_found == 0

    @pytest.mark.asyncio
    async def test_no_candidates_returns_passed(self):
        frame = StaleSyncFrame()
        frame.set_data_dependency_graph(_make_ddg_no_candidates())
        result = await frame.execute_async(_make_code_file())
        assert result.status == "passed"
        assert result.issues_found == 0
        assert result.metadata.get("reason") == "no_co_write_candidates"

    @pytest.mark.asyncio
    async def test_llm_not_available_no_findings(self):
        frame = StaleSyncFrame()
        frame.set_data_dependency_graph(_make_ddg_with_co_writes())
        # No llm_service set
        result = await frame.execute_async(_make_code_file())
        assert result.status == "passed"
        assert result.issues_found == 0
        assert result.metadata.get("llm_available") is False

    @pytest.mark.asyncio
    async def test_llm_stale_sync_high_confidence_creates_finding(self):
        frame = StaleSyncFrame()
        frame.set_data_dependency_graph(_make_ddg_with_co_writes())
        frame.llm_service = _make_mock_llm("stale_sync", 0.85, "fields are coupled")

        result = await frame.execute_async(_make_code_file())
        assert result.status == "failed"
        assert result.issues_found == 1

        finding = result.findings[0]
        assert "STALE-SYNC" in finding.id
        assert finding.severity == "high"
        assert finding.is_blocker is False
        assert "context.findings" in finding.message or "context.validated_issues" in finding.message

    @pytest.mark.asyncio
    async def test_llm_intentional_no_finding(self):
        frame = StaleSyncFrame()
        frame.set_data_dependency_graph(_make_ddg_with_co_writes())
        frame.llm_service = _make_mock_llm("intentional", 0.9, "different lifecycle")

        result = await frame.execute_async(_make_code_file())
        assert result.status == "passed"
        assert result.issues_found == 0

    @pytest.mark.asyncio
    async def test_llm_unclear_no_finding(self):
        frame = StaleSyncFrame()
        frame.set_data_dependency_graph(_make_ddg_with_co_writes())
        frame.llm_service = _make_mock_llm("unclear", 0.3, "cannot tell")

        result = await frame.execute_async(_make_code_file())
        assert result.status == "passed"
        assert result.issues_found == 0

    @pytest.mark.asyncio
    async def test_llm_stale_sync_low_confidence_no_finding(self):
        """stale_sync verdict but confidence < threshold → skip."""
        frame = StaleSyncFrame()
        frame.set_data_dependency_graph(_make_ddg_with_co_writes())
        frame.llm_service = _make_mock_llm("stale_sync", _CONFIDENCE_THRESHOLD - 0.01, "borderline")

        result = await frame.execute_async(_make_code_file())
        assert result.status == "passed"
        assert result.issues_found == 0

    @pytest.mark.asyncio
    async def test_llm_exception_graceful_degradation(self):
        frame = StaleSyncFrame()
        frame.set_data_dependency_graph(_make_ddg_with_co_writes())

        # LLM raises exception
        mock_llm = AsyncMock()
        mock_llm.complete_async = AsyncMock(side_effect=RuntimeError("LLM timeout"))
        frame.llm_service = mock_llm

        result = await frame.execute_async(_make_code_file())
        assert result.status == "passed"  # Graceful degradation
        assert result.issues_found == 0

    @pytest.mark.asyncio
    async def test_finding_structure_and_metadata(self):
        frame = StaleSyncFrame()
        frame.set_data_dependency_graph(_make_ddg_with_co_writes())
        frame.llm_service = _make_mock_llm("stale_sync", 0.9, "fields are always coupled")

        result = await frame.execute_async(_make_code_file())
        assert result.issues_found == 1

        finding = result.findings[0]
        assert finding.id.startswith("CONTRACT-STALE-SYNC-")
        assert "0.90" in finding.message or "0.9" in finding.message  # confidence in message
        assert "fields are always coupled" in finding.detail

        meta = result.metadata
        assert meta["gap_type"] == "STALE_SYNC"
        assert meta["candidates_found"] >= 1
        assert meta["llm_available"] is True

    @pytest.mark.asyncio
    async def test_frame_properties(self):
        frame = StaleSyncFrame()
        assert frame.frame_id == "stale_sync"
        assert frame.is_blocker is False
        assert frame.supports_verification is False


# ---------------------------------------------------------------------------
# Unit: co_write_candidates() via DDG
# ---------------------------------------------------------------------------


class TestCoWriteCandidates:
    def test_candidate_detected(self):
        ddg = _make_ddg_with_co_writes()
        candidates = ddg.co_write_candidates(min_co_writes=_MIN_CO_WRITES)
        # The pair (context.findings, context.validated_issues) should be a candidate
        assert len(candidates) >= 1
        pair_keys = set(candidates.keys())
        assert any(
            ("context.findings" in p and "context.validated_issues" in p) for p in [tuple(sorted(k)) for k in pair_keys]
        )

    def test_no_candidates_when_below_min_co_writes(self):
        ddg = _make_ddg_no_candidates()
        candidates = ddg.co_write_candidates(min_co_writes=_MIN_CO_WRITES)
        assert len(candidates) == 0

    def test_no_diverging_writes_not_a_candidate(self):
        """If always written together with no diverging writes → not a STALE_SYNC candidate."""
        ddg = DataDependencyGraph(
            writes=defaultdict(list),
            reads=defaultdict(list),
            init_fields=set(),
        )
        # A and B always written in the same functions, never separately
        for func in ["func1", "func2", "func3"]:
            ddg.writes["context.a"].append(WriteNode("context.a", "file.py", 1, func, False))
            ddg.writes["context.b"].append(WriteNode("context.b", "file.py", 2, func, False))

        candidates = ddg.co_write_candidates(min_co_writes=2)
        # No diverging writes → not a candidate
        assert len(candidates) == 0

    def test_candidate_info_structure(self):
        ddg = _make_ddg_with_co_writes()
        candidates = ddg.co_write_candidates(min_co_writes=_MIN_CO_WRITES)

        for (field_a, field_b), info in candidates.items():
            assert "co_write_funcs" in info
            assert "a_only_writes" in info
            assert "b_only_writes" in info
            assert len(info["co_write_funcs"]) >= _MIN_CO_WRITES
            # At least one side must have diverging writes
            assert info["a_only_writes"] or info["b_only_writes"]

    def test_min_co_writes_param_respected(self):
        ddg = _make_ddg_with_co_writes()
        # With min_co_writes=4, the 3 co-write functions shouldn't qualify
        candidates_strict = ddg.co_write_candidates(min_co_writes=4)
        candidates_loose = ddg.co_write_candidates(min_co_writes=2)
        assert len(candidates_strict) <= len(candidates_loose)

    def test_empty_ddg_no_candidates(self):
        ddg = DataDependencyGraph(
            writes=defaultdict(list),
            reads=defaultdict(list),
            init_fields=set(),
        )
        candidates = ddg.co_write_candidates()
        assert len(candidates) == 0
