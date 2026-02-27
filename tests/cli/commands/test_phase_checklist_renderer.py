"""
Tests for warden.cli.commands._phase_checklist_renderer

Covers:
1. render_checklist_rows — generates correct Rich Text objects per status
2. normalise_phase_name — maps executor/runner identifiers to canonical names
"""

import pytest

from warden.cli.commands._phase_checklist_renderer import (
    normalise_phase_name,
    render_checklist_rows,
)
from warden.pipeline.domain.phase_checklist import (
    PhaseChecklist,
    PhaseChecklistItem,
    PhaseStatus,
)


# ---------------------------------------------------------------------------
# render_checklist_rows
# ---------------------------------------------------------------------------


class TestRenderChecklistRows:
    """Rendering correctness for each phase status."""

    def test_returns_list_of_text_objects(self):
        cl = PhaseChecklist.from_defaults()
        rows = render_checklist_rows(cl)
        assert isinstance(rows, list)
        assert len(rows) == len(cl.items)

    def test_pending_item_has_no_timing(self):
        cl = PhaseChecklist(items=[PhaseChecklistItem(name="Test")])
        rows = render_checklist_rows(cl)
        assert len(rows) == 1
        text = rows[0].plain
        assert "Test" in text
        # Should not contain timing information
        assert "s" not in text.split("Test")[1] or text.split("Test")[1].strip() == ""

    def test_done_item_shows_timing(self):
        item = PhaseChecklistItem(name="Analysis")
        item.start_time = 100.0
        item.end_time = 112.0
        item.status = PhaseStatus.DONE
        cl = PhaseChecklist(items=[item])
        rows = render_checklist_rows(cl)
        text = rows[0].plain
        assert "Analysis" in text
        assert "12s" in text

    def test_running_item_shows_dots_or_elapsed(self):
        item = PhaseChecklistItem(name="Validation")
        item.status = PhaseStatus.RUNNING
        item.start_time = None  # No start time yet
        cl = PhaseChecklist(items=[item])
        rows = render_checklist_rows(cl)
        text = rows[0].plain
        assert "Validation" in text
        assert "..." in text

    def test_failed_item_rendered(self):
        item = PhaseChecklistItem(name="Classification")
        item.start_time = 100.0
        item.end_time = 108.0
        item.status = PhaseStatus.FAILED
        cl = PhaseChecklist(items=[item])
        rows = render_checklist_rows(cl)
        text = rows[0].plain
        assert "Classification" in text
        assert "8s" in text

    def test_skipped_item_rendered(self):
        item = PhaseChecklistItem(name="Cleaning")
        item.status = PhaseStatus.SKIPPED
        cl = PhaseChecklist(items=[item])
        rows = render_checklist_rows(cl)
        text = rows[0].plain
        assert "Cleaning" in text

    def test_full_lifecycle_rendering(self):
        """Simulate a real pipeline progression and verify row count."""
        cl = PhaseChecklist.from_defaults()
        cl.mark_phase_running("Pre-Analysis")
        cl.mark_phase_done("Pre-Analysis")
        cl.mark_phase_running("Triage")

        rows = render_checklist_rows(cl)
        assert len(rows) == cl.total_count

        # Check that Pre-Analysis shows "OK" glyph
        pre_analysis_text = rows[0].plain
        assert "OK" in pre_analysis_text

        # Check that Triage shows ">>" glyph
        triage_text = rows[1].plain
        assert ">>" in triage_text


# ---------------------------------------------------------------------------
# normalise_phase_name
# ---------------------------------------------------------------------------


class TestNormalisePhaseNameFn:
    """Phase name normalization mapping."""

    @pytest.mark.parametrize(
        "raw, expected",
        [
            # Executor identifiers (UPPER_CASE)
            ("PRE_ANALYSIS", "Pre-Analysis"),
            ("TRIAGE", "Triage"),
            ("ANALYSIS", "Analysis"),
            ("CLASSIFICATION", "Classification"),
            ("VALIDATION", "Validation"),
            ("VERIFICATION", "Verification"),
            ("FORTIFICATION", "Fortification"),
            ("CLEANING", "Cleaning"),
            # Runner labels (Title Case)
            ("Pre-Analysis", "Pre-Analysis"),
            ("Triage", "Triage"),
            ("Analysis", "Analysis"),
            ("Classification", "Classification"),
            ("Validation", "Validation"),
            ("Verification", "Verification"),
            ("Fortification", "Fortification"),
            ("Cleaning", "Cleaning"),
        ],
    )
    def test_maps_known_identifiers(self, raw, expected):
        assert normalise_phase_name(raw) == expected

    def test_lsp_diagnostics_returns_empty(self):
        assert normalise_phase_name("LSP_DIAGNOSTICS") == ""
        assert normalise_phase_name("Lsp Diagnostics") == ""

    def test_unknown_phase_returns_titled(self):
        result = normalise_phase_name("CUSTOM_PHASE")
        # Should be some title-case form, not crash
        assert isinstance(result, str)
        assert len(result) > 0
