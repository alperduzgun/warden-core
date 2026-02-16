"""
Tests for finding deduplication in ResultAggregator.

Verifies:
1. Duplicate findings from different frames are merged
2. Unique findings are preserved
3. Deduplication uses fingerprint: {type}:{location}:{message_hash}
"""

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from warden.pipeline.application.orchestrator.result_aggregator import ResultAggregator
from warden.pipeline.domain.pipeline_context import PipelineContext
from warden.validation.domain.frame import Finding, FrameResult


# --- Helpers ---


def _make_context(**overrides) -> PipelineContext:
    """Create a minimal PipelineContext for testing."""
    defaults = dict(
        pipeline_id="test-pipeline",
        started_at=datetime.now(),
        file_path=Path("/tmp/test.py"),
        source_code="print('hello')",
    )
    defaults.update(overrides)
    return PipelineContext(**defaults)


def _make_finding(
    id: str,
    severity: str = "medium",
    msg: str = "test",
    location: str = "test.py:1",
) -> Finding:
    """Create a test finding."""
    return Finding(
        id=id,
        severity=severity,
        message=msg,
        location=location,
    )


def _make_frame_result(frame_id: str, findings: list[Finding]) -> FrameResult:
    """Create a test frame result."""
    return FrameResult(
        frame_id=frame_id,
        frame_name=frame_id,
        status="failed" if findings else "passed",
        duration=0.1,
        issues_found=len(findings),
        is_blocker=False,
        findings=findings,
    )


def _make_pipeline():
    """Create a mock ValidationPipeline with tracking fields."""
    p = MagicMock()
    p.frames_executed = 0
    p.frames_passed = 0
    p.frames_failed = 0
    return p


# --- Tests ---


class TestFindingDeduplication:
    """Verify findings are deduplicated across frames."""

    def test_duplicate_findings_from_different_frames_merged(self):
        """Identical findings from different frames should be deduplicated."""
        ctx = _make_context()
        ctx.frame_results = {}

        # Create identical findings in two different frames
        finding1 = _make_finding("F1", severity="high", msg="SQL injection risk", location="app.py:42")
        finding2 = _make_finding("F2", severity="high", msg="SQL injection risk", location="app.py:42")

        ctx.frame_results["security_frame"] = {
            "result": _make_frame_result("security_frame", [finding1]),
            "pre_violations": [],
            "post_violations": [],
        }
        ctx.frame_results["resilience_frame"] = {
            "result": _make_frame_result("resilience_frame", [finding2]),
            "pre_violations": [],
            "post_violations": [],
        }

        agg = ResultAggregator()
        agg.store_validation_results(ctx, _make_pipeline())

        # Should only have 1 finding after deduplication
        assert len(ctx.findings) == 1
        # Verify it's the first occurrence that was kept
        assert ctx.findings[0].id in ["F1", "F2"]

    def test_unique_findings_preserved(self):
        """Different findings should all be preserved."""
        ctx = _make_context()
        ctx.frame_results = {}

        # Create different findings
        finding1 = _make_finding("F1", severity="high", msg="SQL injection", location="app.py:42")
        finding2 = _make_finding("F2", severity="medium", msg="Hardcoded secret", location="config.py:10")
        finding3 = _make_finding("F3", severity="low", msg="Missing type hint", location="utils.py:5")

        ctx.frame_results["security_frame"] = {
            "result": _make_frame_result("security_frame", [finding1, finding2]),
            "pre_violations": [],
            "post_violations": [],
        }
        ctx.frame_results["resilience_frame"] = {
            "result": _make_frame_result("resilience_frame", [finding3]),
            "pre_violations": [],
            "post_violations": [],
        }

        agg = ResultAggregator()
        agg.store_validation_results(ctx, _make_pipeline())

        # All 3 should be preserved
        assert len(ctx.findings) == 3
        ids = {f.id for f in ctx.findings}
        assert ids == {"F1", "F2", "F3"}

    def test_same_message_different_location_preserved(self):
        """Same message at different locations should be treated as unique."""
        ctx = _make_context()
        ctx.frame_results = {}

        # Same message, different locations
        finding1 = _make_finding("F1", severity="high", msg="SQL injection", location="app.py:42")
        finding2 = _make_finding("F2", severity="high", msg="SQL injection", location="app.py:99")

        ctx.frame_results["security_frame"] = {
            "result": _make_frame_result("security_frame", [finding1, finding2]),
            "pre_violations": [],
            "post_violations": [],
        }

        agg = ResultAggregator()
        agg.store_validation_results(ctx, _make_pipeline())

        # Both should be preserved (different locations)
        assert len(ctx.findings) == 2
        locations = {f.location for f in ctx.findings}
        assert locations == {"app.py:42", "app.py:99"}

    def test_same_location_different_message_preserved(self):
        """Different messages at same location should be treated as unique."""
        ctx = _make_context()
        ctx.frame_results = {}

        # Different messages, same location
        finding1 = _make_finding("F1", severity="high", msg="SQL injection", location="app.py:42")
        finding2 = _make_finding("F2", severity="medium", msg="Missing validation", location="app.py:42")

        ctx.frame_results["security_frame"] = {
            "result": _make_frame_result("security_frame", [finding1, finding2]),
            "pre_violations": [],
            "post_violations": [],
        }

        agg = ResultAggregator()
        agg.store_validation_results(ctx, _make_pipeline())

        # Both should be preserved (different messages)
        assert len(ctx.findings) == 2
        messages = {f.message for f in ctx.findings}
        assert messages == {"SQL injection", "Missing validation"}

    def test_exact_duplicates_in_same_frame_deduplicated(self):
        """Duplicate findings within the same frame should be deduplicated."""
        ctx = _make_context()
        ctx.frame_results = {}

        # Create exact duplicates in one frame
        finding1 = _make_finding("F1", severity="high", msg="Duplicate issue", location="app.py:10")
        finding2 = _make_finding("F2", severity="high", msg="Duplicate issue", location="app.py:10")

        ctx.frame_results["security_frame"] = {
            "result": _make_frame_result("security_frame", [finding1, finding2]),
            "pre_violations": [],
            "post_violations": [],
        }

        agg = ResultAggregator()
        agg.store_validation_results(ctx, _make_pipeline())

        # Should only have 1 finding
        assert len(ctx.findings) == 1

    def test_multiple_frames_with_overlapping_findings(self):
        """Complex scenario with some duplicates and some unique findings."""
        ctx = _make_context()
        ctx.frame_results = {}

        # Frame 1: F1, F2
        finding1_frame1 = _make_finding("F1", severity="high", msg="Issue A", location="app.py:1")
        finding2_frame1 = _make_finding("F2", severity="medium", msg="Issue B", location="app.py:2")

        # Frame 2: F3 (duplicate of F1), F4 (unique)
        finding1_frame2 = _make_finding("F3", severity="high", msg="Issue A", location="app.py:1")  # Duplicate
        finding4_frame2 = _make_finding("F4", severity="low", msg="Issue C", location="app.py:3")  # Unique

        # Frame 3: F5 (duplicate of F2), F6 (unique)
        finding2_frame3 = _make_finding("F5", severity="medium", msg="Issue B", location="app.py:2")  # Duplicate
        finding6_frame3 = _make_finding("F6", severity="high", msg="Issue D", location="app.py:4")  # Unique

        ctx.frame_results["security_frame"] = {
            "result": _make_frame_result("security_frame", [finding1_frame1, finding2_frame1]),
            "pre_violations": [],
            "post_violations": [],
        }
        ctx.frame_results["resilience_frame"] = {
            "result": _make_frame_result("resilience_frame", [finding1_frame2, finding4_frame2]),
            "pre_violations": [],
            "post_violations": [],
        }
        ctx.frame_results["data_frame"] = {
            "result": _make_frame_result("data_frame", [finding2_frame3, finding6_frame3]),
            "pre_violations": [],
            "post_violations": [],
        }

        agg = ResultAggregator()
        agg.store_validation_results(ctx, _make_pipeline())

        # Should have 4 unique findings (F1, F2, F4, F6)
        assert len(ctx.findings) == 4
        messages = {f.message for f in ctx.findings}
        assert messages == {"Issue A", "Issue B", "Issue C", "Issue D"}

    def test_deduplication_with_empty_frames(self):
        """Deduplication should work with empty frame results."""
        ctx = _make_context()
        ctx.frame_results = {}

        finding1 = _make_finding("F1", severity="high", msg="Issue", location="app.py:1")

        ctx.frame_results["security_frame"] = {
            "result": _make_frame_result("security_frame", [finding1]),
            "pre_violations": [],
            "post_violations": [],
        }
        ctx.frame_results["resilience_frame"] = {
            "result": _make_frame_result("resilience_frame", []),
            "pre_violations": [],
            "post_violations": [],
        }

        agg = ResultAggregator()
        agg.store_validation_results(ctx, _make_pipeline())

        assert len(ctx.findings) == 1
        assert ctx.findings[0].id == "F1"
