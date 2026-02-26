"""
Tests for warden.pipeline.application.orchestrator.pipeline_phase_runner

Covers:
1. execute_all_phases — phase orchestration with enable/disable flags
2. _apply_manual_frame_override — manual frame selection
3. _finalize_pipeline_status — blocker/non-blocker logic + LLM usage
4. _check_phase_preconditions — pre-condition checks for phase transitions
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from warden.pipeline.application.orchestrator.pipeline_phase_runner import (
    PipelinePhaseRunner,
)
from warden.pipeline.domain.enums import AnalysisLevel, PipelineStatus
from warden.pipeline.domain.models import PipelineConfig

from .conftest import (
    make_code_file,
    make_context,
    make_finding,
    make_frame_result,
    make_pipeline,
)


def _make_runner(config=None, **kwargs):
    """Create a PipelinePhaseRunner with mock collaborators."""
    phase_executor = kwargs.pop("phase_executor", AsyncMock())
    frame_executor = kwargs.pop("frame_executor", AsyncMock())
    frame_executor.frames = kwargs.pop("frames_list", [])
    post_processor = kwargs.pop("post_processor", MagicMock())
    post_processor.verify_findings_async = AsyncMock()
    post_processor.apply_baseline = MagicMock()

    return PipelinePhaseRunner(
        config=config or PipelineConfig(),
        phase_executor=phase_executor,
        frame_executor=frame_executor,
        post_processor=post_processor,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# execute_all_phases
# ---------------------------------------------------------------------------


class TestExecuteAllPhases:
    """Phase orchestration with enable/disable flags."""

    @pytest.mark.asyncio
    async def test_all_phases_called(self):
        """All phases enabled → each executor method called once."""
        config = PipelineConfig(
            enable_pre_analysis=True,
            enable_analysis=True,
            enable_validation=True,
            enable_fortification=True,
            enable_cleaning=True,
            enable_issue_validation=True,
            use_llm=True,
            analysis_level=AnalysisLevel.STANDARD,
        )
        pe = AsyncMock()
        fe = AsyncMock()
        fe.frames = ["security"]
        pp = MagicMock()
        pp.verify_findings_async = AsyncMock()
        pp.apply_baseline = MagicMock()

        runner = PipelinePhaseRunner(
            config=config,
            phase_executor=pe,
            frame_executor=fe,
            post_processor=pp,
        )

        ctx = make_context()
        ctx.selected_frames = ["security"]
        pipeline = make_pipeline(status=PipelineStatus.RUNNING)
        files = [make_code_file()]

        await runner.execute_all_phases(ctx, files, pipeline)

        pe.execute_pre_analysis_async.assert_awaited_once()
        pe.execute_triage_async.assert_awaited_once()
        pe.execute_analysis_async.assert_awaited_once()
        pe.execute_classification_async.assert_awaited_once()
        fe.execute_validation_with_strategy_async.assert_awaited_once()
        pe.execute_fortification_async.assert_awaited_once()
        pe.execute_cleaning_async.assert_awaited_once()
        pp.verify_findings_async.assert_awaited_once()
        pp.apply_baseline.assert_called_once()

    @pytest.mark.asyncio
    async def test_pre_analysis_skipped_when_disabled(self):
        """enable_pre_analysis=False → not called."""
        config = PipelineConfig(
            enable_pre_analysis=False,
            enable_validation=False,
            enable_fortification=False,
            enable_cleaning=False,
        )
        pe = AsyncMock()
        runner = _make_runner(config=config, phase_executor=pe)

        ctx = make_context()
        await runner.execute_all_phases(ctx, [make_code_file()], make_pipeline())

        pe.execute_pre_analysis_async.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_triage_skipped_for_basic(self):
        """analysis_level=BASIC → triage not called."""
        config = PipelineConfig(
            analysis_level=AnalysisLevel.BASIC,
            enable_validation=False,
            enable_fortification=False,
            enable_cleaning=False,
        )
        pe = AsyncMock()
        runner = _make_runner(config=config, phase_executor=pe)

        ctx = make_context()
        await runner.execute_all_phases(ctx, [make_code_file()], make_pipeline())

        pe.execute_triage_async.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_validation_skipped_when_disabled(self):
        """enable_validation=False → frame executor not called."""
        config = PipelineConfig(
            enable_validation=False,
            enable_fortification=False,
            enable_cleaning=False,
        )
        fe = AsyncMock()
        fe.frames = []
        runner = _make_runner(config=config, frame_executor=fe)

        ctx = make_context()
        await runner.execute_all_phases(ctx, [make_code_file()], make_pipeline())

        fe.execute_validation_with_strategy_async.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_fortification_skipped_when_disabled(self):
        """enable_fortification=False → not called."""
        config = PipelineConfig(
            enable_fortification=False,
            enable_validation=False,
            enable_cleaning=False,
        )
        pe = AsyncMock()
        runner = _make_runner(config=config, phase_executor=pe)

        ctx = make_context()
        await runner.execute_all_phases(ctx, [make_code_file()], make_pipeline())

        pe.execute_fortification_async.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cleaning_skipped_when_disabled(self):
        """enable_cleaning=False → not called."""
        config = PipelineConfig(
            enable_cleaning=False,
            enable_validation=False,
            enable_fortification=False,
        )
        pe = AsyncMock()
        runner = _make_runner(config=config, phase_executor=pe)

        ctx = make_context()
        await runner.execute_all_phases(ctx, [make_code_file()], make_pipeline())

        pe.execute_cleaning_async.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_verification_called_when_enabled(self):
        """enable_issue_validation=True → post_processor.verify_findings_async called."""
        config = PipelineConfig(
            enable_issue_validation=True,
            enable_validation=False,
            enable_fortification=False,
            enable_cleaning=False,
        )
        pp = MagicMock()
        pp.verify_findings_async = AsyncMock()
        pp.apply_baseline = MagicMock()
        runner = _make_runner(config=config, post_processor=pp)

        ctx = make_context()
        await runner.execute_all_phases(ctx, [make_code_file()], make_pipeline())

        pp.verify_findings_async.assert_awaited_once()


# ---------------------------------------------------------------------------
# _apply_manual_frame_override
# ---------------------------------------------------------------------------


class TestManualFrameOverride:
    """Manual frame selection via CLI override."""

    @pytest.mark.asyncio
    async def test_override_sets_context_fields(self):
        """frames_to_execute sets selected_frames + reasoning."""
        config = PipelineConfig(
            enable_validation=False,
            enable_fortification=False,
            enable_cleaning=False,
        )
        runner = _make_runner(config=config)

        ctx = make_context()
        frames = ["security", "resilience"]
        await runner.execute_all_phases(ctx, [make_code_file()], make_pipeline(), frames_to_execute=frames)

        assert ctx.selected_frames == ["security", "resilience"]
        assert "manually" in ctx.classification_reasoning.lower()

    @pytest.mark.asyncio
    async def test_override_skips_classification(self):
        """Manual override → classification executor not called."""
        config = PipelineConfig(
            enable_validation=False,
            enable_fortification=False,
            enable_cleaning=False,
        )
        pe = AsyncMock()
        runner = _make_runner(config=config, phase_executor=pe)

        ctx = make_context()
        await runner.execute_all_phases(
            ctx, [make_code_file()], make_pipeline(), frames_to_execute=["security"]
        )

        pe.execute_classification_async.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_override_runs_classification(self):
        """frames_to_execute=None → classification called."""
        config = PipelineConfig(
            enable_validation=False,
            enable_fortification=False,
            enable_cleaning=False,
        )
        pe = AsyncMock()
        runner = _make_runner(config=config, phase_executor=pe)

        ctx = make_context()
        await runner.execute_all_phases(ctx, [make_code_file()], make_pipeline())

        pe.execute_classification_async.assert_awaited_once()


# ---------------------------------------------------------------------------
# _finalize_pipeline_status
# ---------------------------------------------------------------------------


class TestFinalizePipelineStatus:
    """Pipeline status determination after execution."""

    def test_blocker_failures_set_failed(self):
        """is_blocker=True + failed → FAILED."""
        ctx = make_context()
        ctx.frame_results = {
            "sec": {"result": make_frame_result("sec", [make_finding("F1")], is_blocker=True)},
        }

        pipeline = make_pipeline(status=PipelineStatus.RUNNING)
        runner = _make_runner()
        runner._finalize_pipeline_status(ctx, pipeline)

        assert pipeline.status == PipelineStatus.FAILED

    def test_non_blocker_set_completed_with_failures(self):
        """is_blocker=False + failed → COMPLETED_WITH_FAILURES."""
        ctx = make_context()
        ctx.frame_results = {
            "sec": {"result": make_frame_result("sec", [make_finding("F1")], is_blocker=False)},
        }

        pipeline = make_pipeline(status=PipelineStatus.RUNNING)
        runner = _make_runner()
        runner._finalize_pipeline_status(ctx, pipeline)

        assert pipeline.status == PipelineStatus.COMPLETED_WITH_FAILURES

    def test_no_failures_set_completed(self):
        """All passed → COMPLETED."""
        ctx = make_context()
        ctx.frame_results = {
            "sec": {"result": make_frame_result("sec", [])},
        }

        pipeline = make_pipeline(status=PipelineStatus.RUNNING)
        runner = _make_runner()
        runner._finalize_pipeline_status(ctx, pipeline)

        assert pipeline.status == PipelineStatus.COMPLETED

    def test_llm_usage_captured(self):
        """llm_service.get_usage() → context tokens populated."""
        ctx = make_context()
        ctx.frame_results = {}

        llm = MagicMock()
        llm.get_usage.return_value = {
            "total_tokens": 1000,
            "prompt_tokens": 600,
            "completion_tokens": 400,
            "request_count": 5,
        }

        pipeline = make_pipeline(status=PipelineStatus.RUNNING)
        runner = _make_runner(llm_service=llm)
        runner._finalize_pipeline_status(ctx, pipeline)

        assert ctx.total_tokens == 1000
        assert ctx.prompt_tokens == 600
        assert ctx.completion_tokens == 400
        assert ctx.request_count == 5


# ---------------------------------------------------------------------------
# _check_phase_preconditions (PHASE-GAP-4)
# ---------------------------------------------------------------------------


class TestPhasePreconditionChecks:
    """Pre-condition gate checks before each phase transition."""

    def test_validation_precondition_passes_with_selected_frames(self):
        """selected_frames populated → Validation pre-check returns True."""
        runner = _make_runner()
        ctx = make_context()
        ctx.selected_frames = ["security", "resilience"]

        assert runner._check_phase_preconditions("Validation", ctx) is True
        assert len(ctx.warnings) == 0

    def test_validation_precondition_warns_when_selected_frames_is_none(self):
        """selected_frames is None → Validation pre-check returns False + warning."""
        runner = _make_runner()
        ctx = make_context()
        ctx.selected_frames = None

        result = runner._check_phase_preconditions("Validation", ctx)

        assert result is False
        assert len(ctx.warnings) == 1
        assert "selected_frames" in ctx.warnings[0]
        assert "Classification" in ctx.warnings[0]

    def test_validation_precondition_passes_with_empty_list(self):
        """selected_frames is [] (Classification ran, selected nothing) → True.

        An empty list means the producing phase ran but produced no frames,
        which is a valid (if unusual) result.  Only None signals a skipped phase.
        """
        runner = _make_runner()
        ctx = make_context()
        ctx.selected_frames = []

        assert runner._check_phase_preconditions("Validation", ctx) is True
        assert len(ctx.warnings) == 0

    def test_fortification_precondition_passes_with_findings(self):
        """findings and frame_results populated → Fortification pre-check returns True."""
        runner = _make_runner()
        ctx = make_context()
        ctx.findings = [{"id": "F1", "severity": "high"}]
        ctx.frame_results = {"sec": {"result": "ok"}}

        assert runner._check_phase_preconditions("Fortification", ctx) is True
        assert len(ctx.warnings) == 0

    def test_fortification_precondition_warns_when_findings_is_none(self):
        """findings is None → Fortification pre-check returns False + warning."""
        runner = _make_runner()
        ctx = make_context()
        ctx.findings = None
        ctx.frame_results = {}

        result = runner._check_phase_preconditions("Fortification", ctx)

        assert result is False
        assert len(ctx.warnings) == 1
        assert "findings" in ctx.warnings[0]
        assert "Validation" in ctx.warnings[0]

    def test_fortification_precondition_warns_when_frame_results_is_none(self):
        """frame_results is None → Fortification pre-check returns False + warning."""
        runner = _make_runner()
        ctx = make_context()
        ctx.findings = []
        ctx.frame_results = None

        result = runner._check_phase_preconditions("Fortification", ctx)

        assert result is False
        assert len(ctx.warnings) == 1
        assert "frame_results" in ctx.warnings[0]

    def test_fortification_precondition_warns_on_both_none(self):
        """Both findings and frame_results None → two warnings."""
        runner = _make_runner()
        ctx = make_context()
        ctx.findings = None
        ctx.frame_results = None

        result = runner._check_phase_preconditions("Fortification", ctx)

        assert result is False
        assert len(ctx.warnings) == 2

    def test_fortification_precondition_passes_with_empty_findings(self):
        """findings is [] (Validation ran, found nothing) → True."""
        runner = _make_runner()
        ctx = make_context()
        ctx.findings = []
        ctx.frame_results = {}

        assert runner._check_phase_preconditions("Fortification", ctx) is True
        assert len(ctx.warnings) == 0

    def test_verification_precondition_passes_with_findings(self):
        """findings populated → Verification pre-check returns True."""
        runner = _make_runner()
        ctx = make_context()
        ctx.findings = [{"id": "F1"}]

        assert runner._check_phase_preconditions("Verification", ctx) is True
        assert len(ctx.warnings) == 0

    def test_verification_precondition_warns_when_findings_is_none(self):
        """findings is None → Verification pre-check returns False + warning."""
        runner = _make_runner()
        ctx = make_context()
        ctx.findings = None

        result = runner._check_phase_preconditions("Verification", ctx)

        assert result is False
        assert len(ctx.warnings) == 1
        assert "findings" in ctx.warnings[0]

    def test_cleaning_precondition_passes_with_findings(self):
        """findings populated → Cleaning pre-check returns True."""
        runner = _make_runner()
        ctx = make_context()
        ctx.findings = []

        assert runner._check_phase_preconditions("Cleaning", ctx) is True
        assert len(ctx.warnings) == 0

    def test_cleaning_precondition_warns_when_findings_is_none(self):
        """findings is None → Cleaning pre-check returns False + warning."""
        runner = _make_runner()
        ctx = make_context()
        ctx.findings = None

        result = runner._check_phase_preconditions("Cleaning", ctx)

        assert result is False
        assert len(ctx.warnings) == 1
        assert "findings" in ctx.warnings[0]

    def test_unknown_phase_returns_true(self):
        """Unknown phase name → no checks, returns True."""
        runner = _make_runner()
        ctx = make_context()

        assert runner._check_phase_preconditions("UnknownPhase", ctx) is True
        assert len(ctx.warnings) == 0

    def test_precondition_does_not_raise(self):
        """Pre-condition failures must never raise — only warn."""
        runner = _make_runner()
        ctx = make_context()
        ctx.selected_frames = None
        ctx.findings = None
        ctx.frame_results = None

        # Should not raise for any phase
        for phase in ["Validation", "Verification", "Fortification", "Cleaning"]:
            runner._check_phase_preconditions(phase, ctx)

        # Warnings accumulated but no exceptions raised
        assert len(ctx.warnings) > 0

    @pytest.mark.asyncio
    async def test_pipeline_continues_despite_failed_precondition(self):
        """Validation still executes even when selected_frames is None.

        The pre-condition check logs a warning but does NOT block execution.
        """
        config = PipelineConfig(
            enable_validation=True,
            enable_fortification=False,
            enable_cleaning=False,
        )
        fe = AsyncMock()
        fe.frames = ["security"]
        runner = _make_runner(config=config, frame_executor=fe)

        ctx = make_context()
        # Simulate Classification that failed to populate selected_frames
        ctx.selected_frames = None

        await runner.execute_all_phases(ctx, [make_code_file()], make_pipeline())

        # Validation should still be called despite the warning
        fe.execute_validation_with_strategy_async.assert_awaited_once()
        # A warning should have been recorded
        assert any("selected_frames" in w for w in ctx.warnings)
