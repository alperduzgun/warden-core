"""
Tests for warden.pipeline.domain.phase_checklist

Covers:
1. PhaseStatus enum values
2. PhaseChecklistItem lifecycle (pending -> running -> done/failed/skipped)
3. PhaseChecklistItem timing (elapsed, elapsed_str)
4. PhaseChecklist factory and lookup
5. PhaseChecklist bulk state helpers
6. PhaseChecklist properties (active_phase, completed_count)
"""

import time

import pytest

from warden.pipeline.domain.phase_checklist import (
    PIPELINE_PHASES,
    PhaseChecklist,
    PhaseChecklistItem,
    PhaseStatus,
)


# ---------------------------------------------------------------------------
# PhaseStatus enum
# ---------------------------------------------------------------------------


class TestPhaseStatus:
    """Verify enum values match expected strings."""

    def test_all_statuses_present(self):
        assert PhaseStatus.PENDING == "pending"
        assert PhaseStatus.RUNNING == "running"
        assert PhaseStatus.DONE == "done"
        assert PhaseStatus.FAILED == "failed"
        assert PhaseStatus.SKIPPED == "skipped"

    def test_is_str_enum(self):
        assert isinstance(PhaseStatus.PENDING, str)


# ---------------------------------------------------------------------------
# PhaseChecklistItem
# ---------------------------------------------------------------------------


class TestPhaseChecklistItem:
    """Item lifecycle and timing."""

    def test_default_state_is_pending(self):
        item = PhaseChecklistItem(name="Test")
        assert item.status == PhaseStatus.PENDING
        assert item.start_time is None
        assert item.end_time is None

    def test_elapsed_none_before_start(self):
        item = PhaseChecklistItem(name="Test")
        assert item.elapsed is None
        assert item.elapsed_str == ""

    def test_mark_running(self):
        item = PhaseChecklistItem(name="Test")
        item.mark_running()
        assert item.status == PhaseStatus.RUNNING
        assert item.start_time is not None
        assert item.end_time is None

    def test_elapsed_while_running(self):
        item = PhaseChecklistItem(name="Test")
        item.start_time = time.monotonic() - 5.0  # started 5 seconds ago
        item.status = PhaseStatus.RUNNING
        elapsed = item.elapsed
        assert elapsed is not None
        assert elapsed >= 4.9  # allow small drift

    def test_mark_done(self):
        item = PhaseChecklistItem(name="Test")
        item.mark_running()
        item.mark_done()
        assert item.status == PhaseStatus.DONE
        assert item.end_time is not None

    def test_elapsed_after_done(self):
        item = PhaseChecklistItem(name="Test")
        item.start_time = 100.0
        item.end_time = 112.5
        item.status = PhaseStatus.DONE
        assert item.elapsed == 12.5

    def test_mark_failed(self):
        item = PhaseChecklistItem(name="Test")
        item.mark_running()
        item.mark_failed()
        assert item.status == PhaseStatus.FAILED
        assert item.end_time is not None

    def test_mark_skipped(self):
        item = PhaseChecklistItem(name="Test")
        item.mark_skipped()
        assert item.status == PhaseStatus.SKIPPED
        assert item.start_time is None
        assert item.end_time is None

    def test_elapsed_str_seconds(self):
        item = PhaseChecklistItem(name="Test")
        item.start_time = 100.0
        item.end_time = 112.0
        item.status = PhaseStatus.DONE
        assert item.elapsed_str == "12s"

    def test_elapsed_str_minutes(self):
        item = PhaseChecklistItem(name="Test")
        item.start_time = 100.0
        item.end_time = 163.0
        item.status = PhaseStatus.DONE
        assert item.elapsed_str == "1m 3s"


# ---------------------------------------------------------------------------
# PIPELINE_PHASES constant
# ---------------------------------------------------------------------------


class TestPipelinePhases:
    """Verify the canonical phase list."""

    def test_contains_core_phases(self):
        assert "Pre-Analysis" in PIPELINE_PHASES
        assert "Triage" in PIPELINE_PHASES
        assert "Analysis" in PIPELINE_PHASES
        assert "Classification" in PIPELINE_PHASES
        assert "Validation" in PIPELINE_PHASES
        assert "Fortification" in PIPELINE_PHASES
        assert "Cleaning" in PIPELINE_PHASES

    def test_ordering_pre_analysis_first(self):
        assert PIPELINE_PHASES[0] == "Pre-Analysis"

    def test_ordering_cleaning_last(self):
        assert PIPELINE_PHASES[-1] == "Cleaning"


# ---------------------------------------------------------------------------
# PhaseChecklist
# ---------------------------------------------------------------------------


class TestPhaseChecklist:
    """Factory, lookup, and bulk operations."""

    def test_from_defaults_creates_all_phases(self):
        cl = PhaseChecklist.from_defaults()
        assert len(cl.items) == len(PIPELINE_PHASES)
        for item, expected_name in zip(cl.items, PIPELINE_PHASES):
            assert item.name == expected_name
            assert item.status == PhaseStatus.PENDING

    def test_get_by_name(self):
        cl = PhaseChecklist.from_defaults()
        item = cl.get("Analysis")
        assert item is not None
        assert item.name == "Analysis"

    def test_get_case_insensitive(self):
        cl = PhaseChecklist.from_defaults()
        item = cl.get("analysis")
        assert item is not None
        assert item.name == "Analysis"

    def test_get_returns_none_for_unknown(self):
        cl = PhaseChecklist.from_defaults()
        assert cl.get("NonExistentPhase") is None

    def test_mark_phase_running(self):
        cl = PhaseChecklist.from_defaults()
        cl.mark_phase_running("Analysis")
        item = cl.get("Analysis")
        assert item.status == PhaseStatus.RUNNING

    def test_mark_phase_running_only_from_pending(self):
        cl = PhaseChecklist.from_defaults()
        cl.mark_phase_running("Analysis")
        cl.mark_phase_done("Analysis")
        # Trying to mark as running again should not change status
        cl.mark_phase_running("Analysis")
        assert cl.get("Analysis").status == PhaseStatus.DONE

    def test_mark_phase_done(self):
        cl = PhaseChecklist.from_defaults()
        cl.mark_phase_running("Triage")
        cl.mark_phase_done("Triage")
        assert cl.get("Triage").status == PhaseStatus.DONE

    def test_mark_phase_done_only_from_running(self):
        cl = PhaseChecklist.from_defaults()
        # Trying to mark as done without running first should be a no-op
        cl.mark_phase_done("Triage")
        assert cl.get("Triage").status == PhaseStatus.PENDING

    def test_mark_phase_failed(self):
        cl = PhaseChecklist.from_defaults()
        cl.mark_phase_running("Validation")
        cl.mark_phase_failed("Validation")
        assert cl.get("Validation").status == PhaseStatus.FAILED

    def test_mark_phase_skipped(self):
        cl = PhaseChecklist.from_defaults()
        cl.mark_phase_skipped("Fortification")
        assert cl.get("Fortification").status == PhaseStatus.SKIPPED

    def test_mark_phase_skipped_only_from_pending(self):
        cl = PhaseChecklist.from_defaults()
        cl.mark_phase_running("Fortification")
        cl.mark_phase_skipped("Fortification")
        # Should not change from RUNNING to SKIPPED
        assert cl.get("Fortification").status == PhaseStatus.RUNNING

    def test_active_phase(self):
        cl = PhaseChecklist.from_defaults()
        assert cl.active_phase is None
        cl.mark_phase_running("Pre-Analysis")
        assert cl.active_phase.name == "Pre-Analysis"
        cl.mark_phase_done("Pre-Analysis")
        assert cl.active_phase is None

    def test_completed_count(self):
        cl = PhaseChecklist.from_defaults()
        assert cl.completed_count == 0
        cl.mark_phase_running("Pre-Analysis")
        assert cl.completed_count == 0  # running is not completed
        cl.mark_phase_done("Pre-Analysis")
        assert cl.completed_count == 1
        cl.mark_phase_skipped("Triage")
        assert cl.completed_count == 2

    def test_total_count(self):
        cl = PhaseChecklist.from_defaults()
        assert cl.total_count == len(PIPELINE_PHASES)

    def test_mark_unknown_phase_is_noop(self):
        cl = PhaseChecklist.from_defaults()
        # Should not raise
        cl.mark_phase_running("NonExistent")
        cl.mark_phase_done("NonExistent")
        cl.mark_phase_failed("NonExistent")
        cl.mark_phase_skipped("NonExistent")
        # All items should still be PENDING
        assert all(item.status == PhaseStatus.PENDING for item in cl.items)
