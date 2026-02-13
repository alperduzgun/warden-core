"""
Tests for warden.pipeline.application.orchestrator.pipeline_phase_runner

Covers:
1. execute_all_phases — phase orchestration with enable/disable flags
2. _apply_manual_frame_override — manual frame selection
3. _finalize_pipeline_status — blocker/non-blocker logic + LLM usage
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
