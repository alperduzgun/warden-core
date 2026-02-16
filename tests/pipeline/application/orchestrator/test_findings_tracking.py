"""
Tests for false positive tracking in PipelineContext.

Verifies:
1. False positives are populated after suppression rule matching
2. False positives are populated after verification drops findings
"""

from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from warden.pipeline.application.orchestrator.findings_post_processor import (
    FindingsPostProcessor,
)
from warden.pipeline.application.orchestrator.result_aggregator import ResultAggregator
from warden.pipeline.domain.models import PipelineConfig, ValidationPipeline
from warden.pipeline.domain.pipeline_context import PipelineContext
from warden.validation.domain.frame import Finding, FrameResult


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
    id: str, type: str = "sql_injection", severity: str = "high", location: str = "test.py:1"
) -> dict:
    """Create a finding dict for testing (matches what ResultAggregator expects)."""
    return {
        "id": id,
        "severity": severity,
        "type": type,
        "message": f"Found {type} vulnerability",
        "location": location,
        "file_context": location,  # Use location as file_context for suppression matching
        "detail": f"Details about {type}",
    }


def _make_frame_result(frame_id: str, findings: list[dict]) -> FrameResult:
    """Create a FrameResult object for testing."""
    return FrameResult(
        frame_id=frame_id,
        frame_name=frame_id,
        status="failed" if findings else "passed",
        duration=0.1,
        issues_found=len(findings),
        is_blocker=False,
        findings=findings,
    )


def _make_pipeline() -> ValidationPipeline:
    """Create a mock ValidationPipeline."""
    p = MagicMock(spec=ValidationPipeline)
    p.frames_executed = 1
    p.frames_passed = 0
    p.frames_failed = 1
    return p


class TestFalsePositiveTracking:
    """Test that false_positives are populated in PipelineContext."""

    def test_false_positives_populated_after_suppression(self):
        """Test that suppressed findings are tracked in context.false_positives."""
        # Arrange: Create context with frame_results
        ctx = _make_context()
        findings = [
            _make_finding("FIND-001", type="sql_injection", location="app.py:10"),
            _make_finding("FIND-002", type="xss", location="app.py:20"),
        ]

        frame_result = _make_frame_result("security", findings)
        ctx.frame_results = {
            "security": {
                "result": frame_result,
                "pre_violations": [],
                "post_violations": [],
            }
        }

        # Add suppression rule that matches the first finding
        ctx.suppression_rules = [
            {
                "issue_type": "sql_injection",
                "file_context": "app.py:10",
            }
        ]

        # Act: Run aggregation which applies suppression rules
        aggregator = ResultAggregator()
        pipeline = _make_pipeline()
        aggregator.store_validation_results(ctx, pipeline)

        # Assert: First finding should be in false_positives
        assert len(ctx.false_positives) == 1
        assert "FIND-001" in ctx.false_positives

        # Only the second finding should be in validated_issues
        assert len(ctx.validated_issues) == 1
        assert ctx.validated_issues[0]["id"] == "FIND-002"

    @pytest.mark.asyncio
    async def test_false_positives_populated_after_verification(self):
        """Test that dropped findings after verification are tracked in false_positives."""
        # Arrange: Create context with frame_results
        ctx = _make_context()
        findings = [
            _make_finding("FIND-001", type="sql_injection", location="app.py:10"),
            _make_finding("FIND-002", type="xss", location="app.py:20"),
            _make_finding("FIND-003", type="hardcoded_secret", location="app.py:30"),
        ]

        frame_result = _make_frame_result("security", findings)
        ctx.frame_results = {
            "security": {
                "result": frame_result,
                "pre_violations": [],
                "post_violations": [],
            }
        }

        # Mock LLM service and verifier to drop FIND-002
        mock_llm = MagicMock()
        mock_llm.complete_async = AsyncMock(return_value=MagicMock(content='{"is_true_positive": false}'))

        # Mock the verification service to only keep FIND-001 and FIND-003
        mock_verifier = MagicMock()
        mock_verifier.verify_findings_async = AsyncMock(
            return_value=[
                {"id": "FIND-001", "severity": "high"},
                {"id": "FIND-003", "severity": "high"},
            ]
        )

        # Create post processor and patch the verifier
        config = MagicMock(spec=PipelineConfig)
        config.memory_manager = None
        post_processor = FindingsPostProcessor(
            config=config,
            project_root=Path("/tmp"),
            llm_service=mock_llm,
        )

        # Patch the verifier creation to use our mock
        with patch(
            "warden.pipeline.application.orchestrator.findings_post_processor.FindingVerificationService"
        ) as mock_verif_cls:
            mock_verif_cls.return_value = mock_verifier

            # Act: Run verification
            await post_processor.verify_findings_async(ctx)

        # Assert: FIND-002 should be in false_positives (dropped by verifier)
        assert len(ctx.false_positives) >= 1
        assert "FIND-002" in ctx.false_positives

        # Only FIND-001 and FIND-003 should remain in findings
        assert len(ctx.findings) == 2
        finding_ids = {f.id if hasattr(f, "id") else f["id"] for f in ctx.findings}
        assert "FIND-001" in finding_ids
        assert "FIND-003" in finding_ids
        assert "FIND-002" not in finding_ids


class TestFalsePositivesIntegration:
    """Integration tests for false positive tracking."""

    def test_false_positives_empty_initially(self):
        """Test that context.false_positives starts empty."""
        ctx = _make_context()
        assert ctx.false_positives == []

    def test_multiple_suppression_rules(self):
        """Test that multiple suppression rules work correctly."""
        ctx = _make_context()
        findings = [
            _make_finding("FIND-001", type="sql_injection", location="app.py:10"),
            _make_finding("FIND-002", type="xss", location="app.py:20"),
            _make_finding("FIND-003", type="hardcoded_secret", location="config.py:5"),
        ]

        frame_result = _make_frame_result("security", findings)
        ctx.frame_results = {
            "security": {
                "result": frame_result,
                "pre_violations": [],
                "post_violations": [],
            }
        }

        # Suppress two findings
        ctx.suppression_rules = [
            {"issue_type": "sql_injection", "file_context": "app.py:10"},
            {"issue_type": "hardcoded_secret", "file_context": "config.py:5"},
        ]

        aggregator = ResultAggregator()
        pipeline = _make_pipeline()
        aggregator.store_validation_results(ctx, pipeline)

        # Assert: Two findings suppressed
        assert len(ctx.false_positives) == 2
        assert "FIND-001" in ctx.false_positives
        assert "FIND-003" in ctx.false_positives

        # Only FIND-002 remains
        assert len(ctx.validated_issues) == 1
        assert ctx.validated_issues[0]["id"] == "FIND-002"
