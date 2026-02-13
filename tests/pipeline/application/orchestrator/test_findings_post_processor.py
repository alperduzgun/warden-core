"""
Tests for warden.pipeline.application.orchestrator.findings_post_processor

Covers:
1. verify_findings_async — LLM-based false positive reduction
2. apply_baseline — filtering known issues from baseline.json
3. ensure_state_consistency — pipeline/context state reconciliation
4. _normalize_path — relative/absolute path handling
"""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from warden.pipeline.application.orchestrator.findings_post_processor import (
    FindingsPostProcessor,
)
from warden.pipeline.domain.enums import PipelineStatus
from warden.pipeline.domain.models import PipelineConfig

from .conftest import make_context, make_finding, make_frame_result, make_pipeline


def _make_processor(project_root=None, **kwargs):
    """Create a FindingsPostProcessor with defaults."""
    return FindingsPostProcessor(
        config=kwargs.pop("config", PipelineConfig()),
        project_root=project_root or Path("/tmp/project"),
        **kwargs,
    )


# ---------------------------------------------------------------------------
# verify_findings_async
# ---------------------------------------------------------------------------


class TestVerifyFindingsAsync:
    """LLM-based false positive reduction."""

    @pytest.mark.asyncio
    async def test_drops_false_positives(self):
        """Findings rejected by verifier are removed."""
        ctx = make_context()
        f1 = make_finding("F1")
        f2 = make_finding("F2")
        fr = make_frame_result("sec", [f1, f2])
        ctx.frame_results = {"sec": {"result": fr}}

        # Verifier returns only F1 (F2 is a false positive)
        mock_verifier = AsyncMock()
        mock_verifier.verify_findings_async.return_value = [
            {"id": "F1", "severity": "medium", "message": "ok"}
        ]

        proc = _make_processor(llm_service=MagicMock())

        with patch(
            "warden.pipeline.application.orchestrator.findings_post_processor.FindingVerificationService",
            return_value=mock_verifier,
        ):
            await proc.verify_findings_async(ctx)

        assert len(fr.findings) == 1
        assert fr.findings[0].id == "F1"
        assert len(ctx.findings) == 1

    @pytest.mark.asyncio
    async def test_keeps_all_when_verified(self):
        """All findings survive when verifier keeps them."""
        ctx = make_context()
        f1 = make_finding("F1")
        f2 = make_finding("F2")
        fr = make_frame_result("sec", [f1, f2])
        ctx.frame_results = {"sec": {"result": fr}}

        mock_verifier = AsyncMock()
        mock_verifier.verify_findings_async.return_value = [
            {"id": "F1", "severity": "medium", "message": "ok"},
            {"id": "F2", "severity": "medium", "message": "ok"},
        ]

        proc = _make_processor(llm_service=MagicMock())

        with patch(
            "warden.pipeline.application.orchestrator.findings_post_processor.FindingVerificationService",
            return_value=mock_verifier,
        ):
            await proc.verify_findings_async(ctx)

        assert len(fr.findings) == 2
        assert len(ctx.findings) == 2

    @pytest.mark.asyncio
    async def test_empty_frame_results(self):
        """No findings — verify completes without error."""
        ctx = make_context()
        ctx.frame_results = {"sec": {"result": make_frame_result("sec", [])}}

        proc = _make_processor(llm_service=MagicMock())

        with patch(
            "warden.pipeline.application.orchestrator.findings_post_processor.FindingVerificationService"
        ):
            await proc.verify_findings_async(ctx)

        assert ctx.findings == []

    @pytest.mark.asyncio
    async def test_syncs_context_findings_globally(self):
        """context.findings = union of survivors across all frames."""
        ctx = make_context()
        fr1 = make_frame_result("sec", [make_finding("S1")])
        fr2 = make_frame_result("res", [make_finding("R1"), make_finding("R2")])
        ctx.frame_results = {
            "sec": {"result": fr1},
            "res": {"result": fr2},
        }

        mock_verifier = AsyncMock()
        # Verifier keeps S1, drops R2
        mock_verifier.verify_findings_async.side_effect = [
            [{"id": "S1", "severity": "medium", "message": "ok"}],
            [{"id": "R1", "severity": "medium", "message": "ok"}],
        ]

        proc = _make_processor(llm_service=MagicMock())

        with patch(
            "warden.pipeline.application.orchestrator.findings_post_processor.FindingVerificationService",
            return_value=mock_verifier,
        ):
            await proc.verify_findings_async(ctx)

        assert len(ctx.findings) == 2
        ids = {f.id for f in ctx.findings}
        assert ids == {"S1", "R1"}

    @pytest.mark.asyncio
    async def test_progress_callback_called(self):
        """Progress callback receives 'progress_update' event."""
        ctx = make_context()
        ctx.findings = [make_finding("F1")]
        ctx.frame_results = {
            "sec": {"result": make_frame_result("sec", [make_finding("F1")])}
        }

        callback = MagicMock()
        mock_verifier = AsyncMock()
        mock_verifier.verify_findings_async.return_value = [
            {"id": "F1", "severity": "medium", "message": "ok"}
        ]

        proc = _make_processor(llm_service=MagicMock(), progress_callback=callback)

        with patch(
            "warden.pipeline.application.orchestrator.findings_post_processor.FindingVerificationService",
            return_value=mock_verifier,
        ):
            await proc.verify_findings_async(ctx)

        callback.assert_called()
        args = callback.call_args_list[0]
        assert args[0][0] == "progress_update"

    @pytest.mark.asyncio
    async def test_exception_swallowed(self):
        """Verifier exception doesn't propagate — method completes."""
        ctx = make_context()
        ctx.frame_results = {
            "sec": {"result": make_frame_result("sec", [make_finding("F1")])}
        }

        proc = _make_processor(llm_service=MagicMock())

        with patch(
            "warden.pipeline.application.orchestrator.findings_post_processor.FindingVerificationService",
            side_effect=RuntimeError("boom"),
        ):
            # Should not raise
            await proc.verify_findings_async(ctx)


# ---------------------------------------------------------------------------
# apply_baseline
# ---------------------------------------------------------------------------


class TestApplyBaseline:
    """Filter known issues present in baseline.json."""

    def test_filters_known_issues(self, tmp_path):
        """Findings matching baseline rule+path are removed."""
        baseline = {
            "frame_results": [
                {
                    "findings": [
                        {"rule_id": "SEC-001", "file_path": "app.py"},
                    ]
                }
            ]
        }
        warden_dir = tmp_path / ".warden"
        warden_dir.mkdir()
        (warden_dir / "baseline.json").write_text(json.dumps(baseline))

        ctx = make_context(project_root=tmp_path)
        f1 = make_finding("SEC-001")
        f1.rule_id = "SEC-001"
        f1.file_path = "app.py"
        fr = make_frame_result("sec", [f1])
        ctx.frame_results = {"sec": {"result": fr}}

        proc = _make_processor(project_root=tmp_path)
        proc.apply_baseline(ctx)

        assert len(fr.findings) == 0

    def test_no_baseline_file_no_op(self, tmp_path):
        """No baseline.json — context unchanged."""
        ctx = make_context(project_root=tmp_path)
        f1 = make_finding("F1")
        fr = make_frame_result("sec", [f1])
        ctx.frame_results = {"sec": {"result": fr}}

        proc = _make_processor(project_root=tmp_path)
        proc.apply_baseline(ctx)

        assert len(fr.findings) == 1

    def test_empty_known_issues(self, tmp_path):
        """Baseline exists but has empty findings — no filtering."""
        baseline = {"frame_results": [{"findings": []}]}
        warden_dir = tmp_path / ".warden"
        warden_dir.mkdir()
        (warden_dir / "baseline.json").write_text(json.dumps(baseline))

        ctx = make_context(project_root=tmp_path)
        f1 = make_finding("F1")
        fr = make_frame_result("sec", [f1])
        ctx.frame_results = {"sec": {"result": fr}}

        proc = _make_processor(project_root=tmp_path)
        proc.apply_baseline(ctx)

        assert len(fr.findings) == 1

    def test_failed_frame_becomes_passed(self, tmp_path):
        """All findings suppressed → frame status flips to 'passed'."""
        baseline = {
            "frame_results": [
                {
                    "findings": [
                        {"rule_id": "R1", "file_path": "app.py"},
                    ]
                }
            ]
        }
        warden_dir = tmp_path / ".warden"
        warden_dir.mkdir()
        (warden_dir / "baseline.json").write_text(json.dumps(baseline))

        ctx = make_context(project_root=tmp_path)
        f1 = make_finding("R1")
        f1.rule_id = "R1"
        f1.file_path = "app.py"
        fr = make_frame_result("sec", [f1], status="failed")
        ctx.frame_results = {"sec": {"result": fr}}

        proc = _make_processor(project_root=tmp_path)
        proc.apply_baseline(ctx)

        assert len(fr.findings) == 0
        assert fr.status == "passed"

    def test_partial_match(self, tmp_path):
        """Only matching findings are removed; others survive."""
        baseline = {
            "frame_results": [
                {
                    "findings": [
                        {"rule_id": "R1", "file_path": "app.py"},
                        {"rule_id": "R2", "file_path": "app.py"},
                    ]
                }
            ]
        }
        warden_dir = tmp_path / ".warden"
        warden_dir.mkdir()
        (warden_dir / "baseline.json").write_text(json.dumps(baseline))

        ctx = make_context(project_root=tmp_path)
        f1 = make_finding("F1")
        f1.rule_id = "R1"
        f1.file_path = "app.py"
        f2 = make_finding("F2")
        f2.rule_id = "R2"
        f2.file_path = "app.py"
        f3 = make_finding("F3")
        f3.rule_id = "R3"
        f3.file_path = "app.py"
        fr = make_frame_result("sec", [f1, f2, f3], status="failed")
        ctx.frame_results = {"sec": {"result": fr}}

        proc = _make_processor(project_root=tmp_path)
        proc.apply_baseline(ctx)

        assert len(fr.findings) == 1
        assert fr.findings[0].id == "F3"

    def test_corrupted_json_handled(self, tmp_path):
        """Invalid JSON in baseline.json — exception caught, context unchanged."""
        warden_dir = tmp_path / ".warden"
        warden_dir.mkdir()
        (warden_dir / "baseline.json").write_text("NOT VALID JSON {{{")

        ctx = make_context(project_root=tmp_path)
        f1 = make_finding("F1")
        fr = make_frame_result("sec", [f1])
        ctx.frame_results = {"sec": {"result": fr}}

        proc = _make_processor(project_root=tmp_path)
        proc.apply_baseline(ctx)

        assert len(fr.findings) == 1

    def test_relative_path_normalization(self, tmp_path):
        """Absolute vs relative paths match correctly via _normalize_path."""
        baseline = {
            "frame_results": [
                {
                    "findings": [
                        {"rule_id": "R1", "file_path": str(tmp_path / "src" / "app.py")},
                    ]
                }
            ]
        }
        warden_dir = tmp_path / ".warden"
        warden_dir.mkdir()
        (tmp_path / "src").mkdir()
        (warden_dir / "baseline.json").write_text(json.dumps(baseline))

        ctx = make_context(project_root=tmp_path)
        f1 = make_finding("F1")
        f1.rule_id = "R1"
        f1.file_path = "src/app.py"
        fr = make_frame_result("sec", [f1])
        ctx.frame_results = {"sec": {"result": fr}}

        proc = _make_processor(project_root=tmp_path)
        proc.apply_baseline(ctx)

        assert len(fr.findings) == 0


# ---------------------------------------------------------------------------
# ensure_state_consistency
# ---------------------------------------------------------------------------


class TestEnsureStateConsistency:
    """Pipeline context/state reconciliation after execution."""

    def test_failed_frames_correct_pipeline_status(self):
        """COMPLETED + failed frame → status corrected to FAILED."""
        ctx = make_context()
        ctx.frame_results = {
            "sec": {"result": make_frame_result("sec", [make_finding("F1")])},
        }

        pipeline = make_pipeline(status=PipelineStatus.COMPLETED)
        proc = _make_processor()
        proc.ensure_state_consistency(ctx, pipeline)

        assert pipeline.status == PipelineStatus.FAILED

    def test_completed_at_set_if_missing(self):
        """completed_at=None → gets set to a datetime."""
        ctx = make_context()
        ctx.frame_results = {}

        pipeline = make_pipeline()
        pipeline.completed_at = None

        proc = _make_processor()
        proc.ensure_state_consistency(ctx, pipeline)

        assert pipeline.completed_at is not None
        assert isinstance(pipeline.completed_at, datetime)

    def test_frame_counts_updated(self):
        """Mix of passed/failed frames → counts match."""
        ctx = make_context()
        ctx.frame_results = {
            "pass1": {"result": make_frame_result("pass1", [])},
            "pass2": {"result": make_frame_result("pass2", [])},
            "fail1": {"result": make_frame_result("fail1", [make_finding("F1")])},
        }

        pipeline = make_pipeline()
        proc = _make_processor()
        proc.ensure_state_consistency(ctx, pipeline)

        assert pipeline.frames_passed == 2
        assert pipeline.frames_failed == 1


# ---------------------------------------------------------------------------
# _normalize_path
# ---------------------------------------------------------------------------


class TestNormalizePath:
    """Path normalization relative to project root."""

    def test_absolute_path_resolves(self, tmp_path):
        """Absolute path under project_root → relative string."""
        (tmp_path / "src").mkdir()
        proc = _make_processor(project_root=tmp_path)
        result = proc._normalize_path(str(tmp_path / "src" / "app.py"))
        assert result == "src/app.py"

    def test_relative_path_resolved(self, tmp_path):
        """Relative path normalized via project_root."""
        (tmp_path / "lib").mkdir()
        proc = _make_processor(project_root=tmp_path)
        result = proc._normalize_path("lib/util.py")
        assert result == "lib/util.py"
