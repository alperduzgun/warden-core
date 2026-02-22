"""
Tests for warden.pipeline.application.orchestrator.pipeline_result_builder

Covers:
1. build — PipelineResult DTO construction from PipelineContext
2. _collect_findings — finding aggregation strategy
3. _is_review_required — review_required flag detection
"""

from unittest.mock import patch

from warden.pipeline.application.orchestrator.pipeline_result_builder import (
    PipelineResultBuilder,
)
from warden.pipeline.domain.enums import ExecutionStrategy, PipelineStatus
from warden.pipeline.domain.models import PipelineConfig

from .conftest import make_context, make_finding, make_frame_result, make_pipeline


def _make_builder(config=None, frames=None):
    """Create a PipelineResultBuilder with defaults."""
    return PipelineResultBuilder(
        config=config or PipelineConfig(),
        frames=frames or [],
    )


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------


class TestBuild:
    """PipelineResult DTO construction."""

    def test_empty_pipeline(self):
        """No findings → all zeroes, COMPLETED."""
        ctx = make_context()
        ctx.frame_results = {}
        ctx.findings = []
        pipeline = make_pipeline(status=PipelineStatus.COMPLETED)

        builder = _make_builder()
        result = builder.build(ctx, pipeline)

        assert result.total_findings == 0
        assert result.critical_findings == 0
        assert result.high_findings == 0
        assert result.medium_findings == 0
        assert result.low_findings == 0
        assert result.status == PipelineStatus.COMPLETED

    def test_severity_counting(self):
        """1 critical + 2 high + 1 medium → correct counts."""
        ctx = make_context()
        findings = [
            make_finding("C1", severity="critical"),
            make_finding("H1", severity="high"),
            make_finding("H2", severity="high"),
            make_finding("M1", severity="medium"),
        ]
        ctx.findings = findings
        ctx.frame_results = {}
        pipeline = make_pipeline()

        builder = _make_builder()
        result = builder.build(ctx, pipeline)

        assert result.total_findings == 4
        assert result.critical_findings == 1
        assert result.high_findings == 2
        assert result.medium_findings == 1
        assert result.low_findings == 0

    def test_quality_score_calculated_when_zero(self):
        """score=0.0 → falls back to calculate_base_score then calculate_quality_score."""
        ctx = make_context()
        ctx.quality_score_before = 0.0
        ctx.findings = [make_finding("F1")]
        ctx.frame_results = {}
        pipeline = make_pipeline()

        with patch(
            "warden.shared.utils.quality_calculator.calculate_quality_score",
            return_value=7.5,
        ) as mock_calc:
            builder = _make_builder()
            result = builder.build(ctx, pipeline)

            mock_calc.assert_called_once()
            assert result.quality_score == 7.5

    def test_quality_score_preserved_when_nonzero(self):
        """score=8.5 → used as base, findings applied on top."""
        ctx = make_context()
        ctx.quality_score_before = 8.5
        ctx.findings = []
        ctx.frame_results = {}
        pipeline = make_pipeline()

        builder = _make_builder()
        result = builder.build(ctx, pipeline)

        # No findings → score stays at base
        assert result.quality_score == 8.5

    def test_quality_score_5_is_not_overridden(self):
        """score=5.0 is a legitimate value and must NOT be replaced."""
        ctx = make_context()
        ctx.quality_score_before = 5.0
        ctx.findings = []
        ctx.frame_results = {}
        pipeline = make_pipeline()

        builder = _make_builder()
        result = builder.build(ctx, pipeline)

        assert result.quality_score == 5.0

    def test_quality_score_none_falls_back_to_base(self):
        """score=None → calculate_base_score from linter metrics."""
        ctx = make_context()
        ctx.quality_score_before = None
        ctx.findings = []
        ctx.frame_results = {}
        pipeline = make_pipeline()

        builder = _make_builder()
        result = builder.build(ctx, pipeline)

        # No linter_metrics → base is 10.0, no findings → 10.0
        assert result.quality_score == 10.0

    def test_metadata_includes_strategy_and_scan_id(self):
        """Verify metadata fields are populated."""
        ctx = make_context()
        ctx.findings = []
        ctx.frame_results = {}
        pipeline = make_pipeline()

        config = PipelineConfig(strategy=ExecutionStrategy.PARALLEL, fail_fast=False)
        builder = _make_builder(config=config)
        result = builder.build(ctx, pipeline, scan_id="scan-123")

        assert result.metadata["strategy"] == "parallel"
        assert result.metadata["fail_fast"] is False
        assert result.metadata["scan_id"] == "scan-123"


# ---------------------------------------------------------------------------
# _collect_findings
# ---------------------------------------------------------------------------


class TestCollectFindings:
    """Finding aggregation strategy."""

    def test_prefers_context_findings(self):
        """context.findings populated → used directly."""
        ctx = make_context()
        ctx.findings = [make_finding("F1"), make_finding("F2")]

        frame_results = [make_frame_result("sec", [make_finding("X1")])]

        result = PipelineResultBuilder._collect_findings(ctx, frame_results)

        assert len(result) == 2
        assert result[0].id == "F1"

    def test_aggregates_from_frame_results(self):
        """context.findings empty → aggregate from frames."""
        ctx = make_context()
        ctx.findings = []

        fr1 = make_frame_result("sec", [make_finding("S1")])
        fr2 = make_frame_result("res", [make_finding("R1"), make_finding("R2")])

        result = PipelineResultBuilder._collect_findings(ctx, [fr1, fr2])

        assert len(result) == 3
        ids = {f.id for f in result}
        assert ids == {"S1", "R1", "R2"}

    def test_empty_returns_empty(self):
        """Both empty → []."""
        ctx = make_context()
        ctx.findings = []

        result = PipelineResultBuilder._collect_findings(ctx, [])

        assert result == []


# ---------------------------------------------------------------------------
# _is_review_required
# ---------------------------------------------------------------------------


class TestIsReviewRequired:
    """Review-required flag detection."""

    def test_dict_finding_review_required(self):
        """Dict with review_required=True → True."""
        finding = {
            "id": "F1",
            "verification_metadata": {"review_required": True},
        }
        assert PipelineResultBuilder._is_review_required(finding) is True

    def test_dict_finding_no_review(self):
        """Dict without review_required → False."""
        finding = {"id": "F1", "severity": "medium"}
        assert PipelineResultBuilder._is_review_required(finding) is False

    def test_finding_object_review_required(self):
        """Finding object with verification_metadata.review_required → True."""
        f = make_finding("F1")
        f.verification_metadata = {"review_required": True}
        assert PipelineResultBuilder._is_review_required(f) is True

    def test_finding_object_no_metadata(self):
        """Finding object without verification_metadata → False."""
        f = make_finding("F1")
        assert PipelineResultBuilder._is_review_required(f) is False
