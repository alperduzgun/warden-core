"""
Unit tests for diff-mode line-level finding filtering.

Tests that FindingsPostProcessor.filter_by_diff_lines():
- Removes findings on unchanged lines when changed_lines is populated
- Keeps findings on changed lines
- Passes all findings through when changed_lines is empty (full-scan mode)
- Handles findings whose file is not in changed_lines (pass-through)
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from warden.pipeline.application.orchestrator.findings_post_processor import FindingsPostProcessor
from warden.pipeline.domain.models import PipelineConfig
from warden.pipeline.domain.pipeline_context import PipelineContext
from warden.validation.domain.frame import Finding


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_context(changed_lines: dict | None = None, **kwargs) -> PipelineContext:
    defaults = {
        "pipeline_id": "test-diff-filter",
        "started_at": datetime.now(),
        "file_path": Path("test.py"),
        "source_code": "",
    }
    defaults.update(kwargs)
    ctx = PipelineContext(**defaults)
    if changed_lines is not None:
        ctx.changed_lines = changed_lines
    return ctx


def _make_finding(fid: str, location: str, line: int = 0) -> Finding:
    return Finding(
        id=fid,
        severity="high",
        message=f"finding {fid}",
        location=location,
        line=line,
    )


def _make_frame_result(findings: list[Finding]) -> dict:
    result_obj = MagicMock()
    result_obj.findings = list(findings)
    result_obj.issues_found = len(findings)
    result_obj.status = "failed" if findings else "passed"
    result_obj.metadata = {}
    result_obj.pre_rule_violations = []
    result_obj.post_rule_violations = []
    result_obj.is_blocker = False
    return {"result": result_obj}


def _make_processor(project_root: Path | None = None) -> FindingsPostProcessor:
    return FindingsPostProcessor(
        config=PipelineConfig(),
        project_root=project_root or Path("/project"),
    )


# ---------------------------------------------------------------------------
# Tests: full-scan mode (empty changed_lines)
# ---------------------------------------------------------------------------


class TestFullScanMode:
    def test_empty_changed_lines_passes_all_findings(self, tmp_path: Path):
        """When changed_lines is empty, no filtering should occur."""
        processor = _make_processor(tmp_path)
        ctx = _make_context(changed_lines={})

        f1 = _make_finding("F1", f"{tmp_path}/app.py:10", line=10)
        f2 = _make_finding("F2", f"{tmp_path}/app.py:20", line=20)
        ctx.frame_results = {"sec": _make_frame_result([f1, f2])}

        processor.filter_by_diff_lines(ctx)

        result = ctx.frame_results["sec"]["result"]
        assert len(result.findings) == 2

    def test_no_changed_lines_field_passes_all(self, tmp_path: Path):
        """When changed_lines is not set (defaults to {}), no filtering occurs."""
        processor = _make_processor(tmp_path)
        ctx = _make_context()  # default: changed_lines = {}

        f1 = _make_finding("F1", f"{tmp_path}/app.py:5", line=5)
        ctx.frame_results = {"sec": _make_frame_result([f1])}

        processor.filter_by_diff_lines(ctx)

        result = ctx.frame_results["sec"]["result"]
        assert len(result.findings) == 1


# ---------------------------------------------------------------------------
# Tests: diff-mode filtering
# ---------------------------------------------------------------------------


class TestDiffModeFiltering:
    def test_finding_on_changed_line_is_kept(self, tmp_path: Path):
        """Findings on changed lines must be preserved."""
        processor = _make_processor(tmp_path)

        app_py = tmp_path / "app.py"
        app_py.write_text("x = 1\n")

        ctx = _make_context(changed_lines={"app.py": {10, 15, 20}})
        f_keep = _make_finding("KEEP", "app.py:10", line=10)
        ctx.frame_results = {"sec": _make_frame_result([f_keep])}

        processor.filter_by_diff_lines(ctx)

        result = ctx.frame_results["sec"]["result"]
        assert len(result.findings) == 1
        assert result.findings[0].id == "KEEP"

    def test_finding_on_unchanged_line_is_removed(self, tmp_path: Path):
        """Findings on lines NOT in the changed set must be removed."""
        processor = _make_processor(tmp_path)

        ctx = _make_context(changed_lines={"app.py": {10, 20}})
        f_drop = _make_finding("DROP", "app.py:99", line=99)
        ctx.frame_results = {"sec": _make_frame_result([f_drop])}

        processor.filter_by_diff_lines(ctx)

        result = ctx.frame_results["sec"]["result"]
        assert len(result.findings) == 0

    def test_mixed_findings_are_split_correctly(self, tmp_path: Path):
        """Changed-line findings kept; unchanged-line findings removed."""
        processor = _make_processor(tmp_path)

        ctx = _make_context(changed_lines={"app.py": {5, 10}})
        f_keep = _make_finding("KEEP", "app.py:5", line=5)
        f_drop = _make_finding("DROP", "app.py:42", line=42)
        ctx.frame_results = {"sec": _make_frame_result([f_keep, f_drop])}

        processor.filter_by_diff_lines(ctx)

        result = ctx.frame_results["sec"]["result"]
        assert len(result.findings) == 1
        assert result.findings[0].id == "KEEP"

    def test_finding_in_file_not_in_diff_map_passes_through(self, tmp_path: Path):
        """Findings in files NOT listed in changed_lines pass through unchanged."""
        processor = _make_processor(tmp_path)

        # Only app.py is in changed_lines; utils.py is NOT
        ctx = _make_context(changed_lines={"app.py": {5}})
        f_utils = _make_finding("UTILS", "utils.py:100", line=100)
        ctx.frame_results = {"sec": _make_frame_result([f_utils])}

        processor.filter_by_diff_lines(ctx)

        result = ctx.frame_results["sec"]["result"]
        assert len(result.findings) == 1
        assert result.findings[0].id == "UTILS"

    def test_context_findings_synced_after_filter(self, tmp_path: Path):
        """context.findings must reflect filtered results after filtering."""
        processor = _make_processor(tmp_path)

        ctx = _make_context(changed_lines={"app.py": {10}})
        f_keep = _make_finding("KEEP", "app.py:10", line=10)
        f_drop = _make_finding("DROP", "app.py:50", line=50)
        ctx.frame_results = {"sec": _make_frame_result([f_keep, f_drop])}

        processor.filter_by_diff_lines(ctx)

        assert len(ctx.findings) == 1
        assert ctx.findings[0].id == "KEEP"

    def test_location_string_parsed_when_line_field_is_zero(self, tmp_path: Path):
        """Line number is extracted from location string when finding.line == 0."""
        processor = _make_processor(tmp_path)

        ctx = _make_context(changed_lines={"app.py": {15}})
        # line=0 forces fallback to location parsing
        f_keep = _make_finding("KEEP", "app.py:15", line=0)
        f_drop = _make_finding("DROP", "app.py:99", line=0)
        ctx.frame_results = {"sec": _make_frame_result([f_keep, f_drop])}

        processor.filter_by_diff_lines(ctx)

        result = ctx.frame_results["sec"]["result"]
        assert len(result.findings) == 1
        assert result.findings[0].id == "KEEP"

    def test_multiple_frames_all_filtered(self, tmp_path: Path):
        """Filtering applies across all frames in context.frame_results."""
        processor = _make_processor(tmp_path)

        ctx = _make_context(changed_lines={"app.py": {1}})
        f1_keep = _make_finding("F1_KEEP", "app.py:1", line=1)
        f1_drop = _make_finding("F1_DROP", "app.py:99", line=99)
        f2_keep = _make_finding("F2_KEEP", "app.py:1", line=1)
        f2_drop = _make_finding("F2_DROP", "app.py:77", line=77)

        ctx.frame_results = {
            "frame_a": _make_frame_result([f1_keep, f1_drop]),
            "frame_b": _make_frame_result([f2_keep, f2_drop]),
        }

        processor.filter_by_diff_lines(ctx)

        res_a = ctx.frame_results["frame_a"]["result"]
        res_b = ctx.frame_results["frame_b"]["result"]

        assert len(res_a.findings) == 1
        assert res_a.findings[0].id == "F1_KEEP"
        assert len(res_b.findings) == 1
        assert res_b.findings[0].id == "F2_KEEP"

    def test_empty_frame_not_mutated(self, tmp_path: Path):
        """Frames with no findings are not affected."""
        processor = _make_processor(tmp_path)

        ctx = _make_context(changed_lines={"app.py": {1}})
        ctx.frame_results = {"sec": _make_frame_result([])}

        processor.filter_by_diff_lines(ctx)

        result = ctx.frame_results["sec"]["result"]
        assert result.findings == []

    def test_finding_with_no_location_info_passes_through(self, tmp_path: Path):
        """Findings with no file or location info pass through (safe default)."""
        processor = _make_processor(tmp_path)

        ctx = _make_context(changed_lines={"app.py": {1}})
        # No location, no file_path attribute, line=0
        f = _make_finding("NOLOC", "", line=0)
        ctx.frame_results = {"sec": _make_frame_result([f])}

        processor.filter_by_diff_lines(ctx)

        result = ctx.frame_results["sec"]["result"]
        assert len(result.findings) == 1
