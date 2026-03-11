"""Tests for detection_source field on Finding and related attribution logic.

Covers:
- TestFindingDetectionSource: field default, valid values, to_json serialization
- TestFrameResultCounts: llm_finding_count and deterministic_finding_count properties
- TestFindingsCacheDetectionSource: serialize/deserialize roundtrip for detection_source
- TestPipelineResultCounts: llmFindingCount and deterministicFindingCount in to_json
"""

from __future__ import annotations

from typing import Any

import pytest

from warden.pipeline.application.orchestrator.findings_cache import (
    _deserialize_finding,
    _serialize_finding,
)
from warden.validation.domain.frame import Finding, FrameResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_finding(
    id: str = "F001",
    severity: str = "high",
    message: str = "test message",
    location: str = "src/app.py:10",
    detection_source: str | None = None,
) -> Finding:
    return Finding(
        id=id,
        severity=severity,
        message=message,
        location=location,
        detection_source=detection_source,
    )


def _make_frame_result(findings: list[Finding]) -> FrameResult:
    return FrameResult(
        frame_id="security",
        frame_name="Security Analysis",
        status="failed" if findings else "passed",
        duration=0.1,
        issues_found=len(findings),
        is_blocker=False,
        findings=findings,
    )


# ===========================================================================
# TestFindingDetectionSource
# ===========================================================================


class TestFindingDetectionSource:
    """Field presence, default value, and JSON serialization."""

    def test_default_is_none(self) -> None:
        f = _make_finding()
        assert f.detection_source is None

    def test_set_rust_engine(self) -> None:
        f = _make_finding(detection_source="rust_engine")
        assert f.detection_source == "rust_engine"

    def test_set_regex(self) -> None:
        f = _make_finding(detection_source="regex")
        assert f.detection_source == "regex"

    def test_set_ast(self) -> None:
        f = _make_finding(detection_source="ast")
        assert f.detection_source == "ast"

    def test_set_taint(self) -> None:
        f = _make_finding(detection_source="taint")
        assert f.detection_source == "taint"

    def test_set_llm(self) -> None:
        f = _make_finding(detection_source="llm")
        assert f.detection_source == "llm"

    def test_set_llm_verified(self) -> None:
        f = _make_finding(detection_source="llm_verified")
        assert f.detection_source == "llm_verified"

    def test_to_json_omits_key_when_none(self) -> None:
        """When detection_source is None, detectionSource must not appear in JSON."""
        f = _make_finding()
        data = f.to_json()
        assert "detectionSource" not in data

    def test_to_json_includes_key_when_set(self) -> None:
        f = _make_finding(detection_source="llm")
        data = f.to_json()
        assert data["detectionSource"] == "llm"

    def test_to_json_rust_engine(self) -> None:
        f = _make_finding(detection_source="rust_engine")
        data = f.to_json()
        assert data["detectionSource"] == "rust_engine"

    def test_to_json_regex(self) -> None:
        f = _make_finding(detection_source="regex")
        data = f.to_json()
        assert data["detectionSource"] == "regex"


# ===========================================================================
# TestFrameResultCounts
# ===========================================================================


class TestFrameResultCounts:
    """llm_finding_count and deterministic_finding_count computed properties."""

    def test_no_findings_both_counts_zero(self) -> None:
        fr = _make_frame_result([])
        assert fr.llm_finding_count == 0
        assert fr.deterministic_finding_count == 0

    def test_all_none_source_are_deterministic(self) -> None:
        findings = [_make_finding(id=f"F{i}") for i in range(3)]
        fr = _make_frame_result(findings)
        assert fr.llm_finding_count == 0
        assert fr.deterministic_finding_count == 3

    def test_all_regex_are_deterministic(self) -> None:
        findings = [_make_finding(id=f"F{i}", detection_source="regex") for i in range(4)]
        fr = _make_frame_result(findings)
        assert fr.llm_finding_count == 0
        assert fr.deterministic_finding_count == 4

    def test_llm_source_counted_as_llm(self) -> None:
        findings = [_make_finding(id="F1", detection_source="llm")]
        fr = _make_frame_result(findings)
        assert fr.llm_finding_count == 1
        assert fr.deterministic_finding_count == 0

    def test_llm_verified_source_counted_as_llm(self) -> None:
        findings = [_make_finding(id="F1", detection_source="llm_verified")]
        fr = _make_frame_result(findings)
        assert fr.llm_finding_count == 1
        assert fr.deterministic_finding_count == 0

    def test_mixed_sources_counted_correctly(self) -> None:
        findings = [
            _make_finding(id="F1", detection_source="regex"),
            _make_finding(id="F2", detection_source="llm"),
            _make_finding(id="F3", detection_source="taint"),
            _make_finding(id="F4", detection_source="llm_verified"),
            _make_finding(id="F5"),  # None
            _make_finding(id="F6", detection_source="rust_engine"),
        ]
        fr = _make_frame_result(findings)
        assert fr.llm_finding_count == 2  # llm + llm_verified
        assert fr.deterministic_finding_count == 4  # regex + taint + None + rust_engine

    def test_counts_sum_to_total_findings(self) -> None:
        findings = [
            _make_finding(id="F1", detection_source="llm"),
            _make_finding(id="F2", detection_source="regex"),
            _make_finding(id="F3"),
        ]
        fr = _make_frame_result(findings)
        assert fr.llm_finding_count + fr.deterministic_finding_count == len(findings)

    def test_rust_engine_is_deterministic(self) -> None:
        findings = [_make_finding(id="F1", detection_source="rust_engine")]
        fr = _make_frame_result(findings)
        assert fr.deterministic_finding_count == 1
        assert fr.llm_finding_count == 0

    def test_taint_is_deterministic(self) -> None:
        findings = [_make_finding(id="F1", detection_source="taint")]
        fr = _make_frame_result(findings)
        assert fr.deterministic_finding_count == 1
        assert fr.llm_finding_count == 0

    def test_ast_is_deterministic(self) -> None:
        findings = [_make_finding(id="F1", detection_source="ast")]
        fr = _make_frame_result(findings)
        assert fr.deterministic_finding_count == 1
        assert fr.llm_finding_count == 0


# ===========================================================================
# TestFindingsCacheDetectionSource
# ===========================================================================


class TestFindingsCacheDetectionSource:
    """detection_source survives serialize -> deserialize roundtrip."""

    def test_roundtrip_llm_source(self) -> None:
        f = _make_finding(detection_source="llm")
        d = _serialize_finding(f)
        restored = _deserialize_finding(d)
        assert restored.detection_source == "llm"

    def test_roundtrip_regex_source(self) -> None:
        f = _make_finding(detection_source="regex")
        d = _serialize_finding(f)
        restored = _deserialize_finding(d)
        assert restored.detection_source == "regex"

    def test_roundtrip_rust_engine_source(self) -> None:
        f = _make_finding(detection_source="rust_engine")
        d = _serialize_finding(f)
        restored = _deserialize_finding(d)
        assert restored.detection_source == "rust_engine"

    def test_roundtrip_none_source(self) -> None:
        f = _make_finding(detection_source=None)
        d = _serialize_finding(f)
        restored = _deserialize_finding(d)
        assert restored.detection_source is None

    def test_roundtrip_taint_source(self) -> None:
        f = _make_finding(detection_source="taint")
        d = _serialize_finding(f)
        restored = _deserialize_finding(d)
        assert restored.detection_source == "taint"

    def test_roundtrip_llm_verified_source(self) -> None:
        f = _make_finding(detection_source="llm_verified")
        d = _serialize_finding(f)
        restored = _deserialize_finding(d)
        assert restored.detection_source == "llm_verified"

    def test_serialize_includes_detection_source_key(self) -> None:
        f = _make_finding(detection_source="ast")
        d = _serialize_finding(f)
        assert "detection_source" in d
        assert d["detection_source"] == "ast"

    def test_serialize_none_persists_as_none(self) -> None:
        f = _make_finding(detection_source=None)
        d = _serialize_finding(f)
        assert "detection_source" in d
        assert d["detection_source"] is None

    def test_deserialize_missing_key_defaults_to_none(self) -> None:
        """Old cache entries without detection_source key deserialize gracefully."""
        d = _serialize_finding(_make_finding())
        del d["detection_source"]
        restored = _deserialize_finding(d)
        assert restored.detection_source is None


# ===========================================================================
# TestPipelineResultCounts
# ===========================================================================


class TestPipelineResultCounts:
    """PipelineResult.to_json includes llmFindingCount and deterministicFindingCount."""

    def _make_pipeline_result(self, frame_results: list[FrameResult]) -> Any:
        from datetime import datetime, timezone

        from warden.pipeline.domain.enums import PipelineStatus
        from warden.pipeline.domain.models import PipelineResult

        return PipelineResult(
            pipeline_id="test-pipeline",
            pipeline_name="Test Pipeline",
            status=PipelineStatus.COMPLETED,
            duration=1.0,
            total_frames=len(frame_results),
            frames_passed=len(frame_results),
            frames_failed=0,
            frames_skipped=0,
            total_findings=sum(fr.issues_found for fr in frame_results),
            critical_findings=0,
            high_findings=0,
            medium_findings=0,
            low_findings=0,
            frame_results=frame_results,
        )

    def test_empty_pipeline_both_counts_zero(self) -> None:
        pr = self._make_pipeline_result([])
        data = pr.to_json()
        assert data["llmFindingCount"] == 0
        assert data["deterministicFindingCount"] == 0

    def test_llm_findings_counted_across_frames(self) -> None:
        frame1 = _make_frame_result([
            _make_finding(id="F1", detection_source="llm"),
            _make_finding(id="F2", detection_source="regex"),
        ])
        frame2 = _make_frame_result([
            _make_finding(id="F3", detection_source="llm_verified"),
        ])
        pr = self._make_pipeline_result([frame1, frame2])
        data = pr.to_json()
        assert data["llmFindingCount"] == 2
        assert data["deterministicFindingCount"] == 1

    def test_all_deterministic(self) -> None:
        frame1 = _make_frame_result([
            _make_finding(id="F1", detection_source="rust_engine"),
            _make_finding(id="F2", detection_source="taint"),
            _make_finding(id="F3"),
        ])
        pr = self._make_pipeline_result([frame1])
        data = pr.to_json()
        assert data["llmFindingCount"] == 0
        assert data["deterministicFindingCount"] == 3

    def test_counts_sum_to_total_across_all_frames(self) -> None:
        frame1 = _make_frame_result([
            _make_finding(id="F1", detection_source="llm"),
            _make_finding(id="F2", detection_source="regex"),
        ])
        frame2 = _make_frame_result([
            _make_finding(id="F3", detection_source="rust_engine"),
            _make_finding(id="F4", detection_source="llm_verified"),
        ])
        pr = self._make_pipeline_result([frame1, frame2])
        data = pr.to_json()
        total = data["llmFindingCount"] + data["deterministicFindingCount"]
        assert total == 4
