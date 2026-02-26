"""
Tests for SuppressionFilter audit trail functionality.

Verifies:
1. Suppressed findings are recorded in PipelineContext.suppressed_findings
2. Each suppression record contains required audit fields (id, file, title, severity, matched_rule, timestamp)
3. INFO-level logging for each suppression decision
4. Backward compatibility: filter works without context parameter
5. Summary logging when findings are suppressed
"""

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from warden.pipeline.application.orchestrator.suppression_filter import SuppressionFilter
from warden.pipeline.domain.pipeline_context import PipelineContext


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


def _make_finding(id: str, file_path: str = "app.py", severity: str = "high", message: str = "Test finding"):
    """Create a mock finding object for testing."""
    return SimpleNamespace(
        id=id,
        file_path=file_path,
        severity=severity,
        message=message,
        location=f"{file_path}:1",
    )


class TestSuppressionFilterAuditTrail:
    """Test that suppression decisions produce a full audit trail."""

    def test_suppressed_finding_recorded_in_context(self):
        """Test that a suppressed finding is recorded in context.suppressed_findings."""
        ctx = _make_context()
        findings = [
            _make_finding("SQL-001", file_path="legacy/db.py", severity="critical", message="SQL injection"),
        ]
        suppressions = [
            {"rule": "SQL-001", "files": ["legacy/*.py"]},
        ]

        result = SuppressionFilter.apply_config_suppressions(findings, suppressions, context=ctx)

        assert len(result) == 0
        assert len(ctx.suppressed_findings) == 1

        record = ctx.suppressed_findings[0]
        assert record["id"] == "SQL-001"
        assert record["file"] == "legacy/db.py"
        assert record["title"] == "SQL injection"
        assert record["severity"] == "critical"
        assert record["matched_rule"] == "SQL-001"
        assert record["matched_files"] == ["legacy/*.py"]
        assert "timestamp" in record

    def test_multiple_suppressions_all_recorded(self):
        """Test that multiple suppressed findings each get their own audit record."""
        ctx = _make_context()
        findings = [
            _make_finding("SQL-001", file_path="legacy/db.py"),
            _make_finding("XSS-001", file_path="legacy/views.py"),
            _make_finding("CSRF-001", file_path="src/app.py"),
        ]
        suppressions = [
            {"rule": "*", "files": ["legacy/*.py"]},
        ]

        result = SuppressionFilter.apply_config_suppressions(findings, suppressions, context=ctx)

        assert len(result) == 1  # Only CSRF-001 survives
        assert result[0].id == "CSRF-001"
        assert len(ctx.suppressed_findings) == 2

        suppressed_ids = {r["id"] for r in ctx.suppressed_findings}
        assert suppressed_ids == {"SQL-001", "XSS-001"}

    def test_no_suppression_no_audit_records(self):
        """Test that when nothing is suppressed, no audit records are created."""
        ctx = _make_context()
        findings = [
            _make_finding("SQL-001", file_path="src/app.py"),
        ]
        suppressions = [
            {"rule": "SQL-001", "files": ["legacy/*.py"]},
        ]

        result = SuppressionFilter.apply_config_suppressions(findings, suppressions, context=ctx)

        assert len(result) == 1
        assert len(ctx.suppressed_findings) == 0

    def test_audit_record_contains_timestamp(self):
        """Test that audit records contain an ISO timestamp."""
        ctx = _make_context()
        findings = [
            _make_finding("SQL-001", file_path="legacy/db.py"),
        ]
        suppressions = [
            {"rule": "SQL-001", "files": ["legacy/*.py"]},
        ]

        SuppressionFilter.apply_config_suppressions(findings, suppressions, context=ctx)

        record = ctx.suppressed_findings[0]
        # Timestamp should be a valid ISO format string
        timestamp = record["timestamp"]
        assert isinstance(timestamp, str)
        # Should parse without error
        datetime.fromisoformat(timestamp)


class TestSuppressionFilterLogging:
    """Test that suppression decisions are logged at INFO level."""

    def test_info_log_for_each_suppressed_finding(self):
        """Test that each suppressed finding generates an INFO log."""
        ctx = _make_context()
        findings = [
            _make_finding("SQL-001", file_path="legacy/db.py", severity="high"),
            _make_finding("XSS-001", file_path="legacy/views.py", severity="medium"),
        ]
        suppressions = [
            {"rule": "*", "files": ["legacy/*.py"]},
        ]

        with patch(
            "warden.pipeline.application.orchestrator.suppression_filter.logger"
        ) as mock_logger:
            SuppressionFilter.apply_config_suppressions(findings, suppressions, context=ctx)

            # Should have 2 individual suppression logs + 1 summary log
            info_calls = mock_logger.info.call_args_list
            assert len(info_calls) >= 2

            # Check first individual log
            first_call_args = info_calls[0]
            assert first_call_args[0][0] == "finding_suppressed_by_config"
            assert first_call_args[1]["finding_id"] == "SQL-001"
            assert first_call_args[1]["severity"] == "high"

            # Check second individual log
            second_call_args = info_calls[1]
            assert second_call_args[0][0] == "finding_suppressed_by_config"
            assert second_call_args[1]["finding_id"] == "XSS-001"

    def test_summary_log_with_counts(self):
        """Test that a summary log is emitted with suppression counts."""
        ctx = _make_context()
        findings = [
            _make_finding("SQL-001", file_path="legacy/db.py"),
            _make_finding("XSS-001", file_path="src/app.py"),
        ]
        suppressions = [
            {"rule": "SQL-001", "files": ["legacy/*.py"]},
        ]

        with patch(
            "warden.pipeline.application.orchestrator.suppression_filter.logger"
        ) as mock_logger:
            SuppressionFilter.apply_config_suppressions(findings, suppressions, context=ctx)

            # Find the summary log call
            summary_calls = [
                c for c in mock_logger.info.call_args_list
                if c[0][0] == "suppression_filter_summary"
            ]
            assert len(summary_calls) == 1
            assert summary_calls[0][1]["total_findings"] == 2
            assert summary_calls[0][1]["suppressed"] == 1
            assert summary_calls[0][1]["remaining"] == 1

    def test_no_summary_log_when_nothing_suppressed(self):
        """Test that no summary log is emitted when nothing is suppressed."""
        ctx = _make_context()
        findings = [
            _make_finding("SQL-001", file_path="src/app.py"),
        ]
        suppressions = [
            {"rule": "SQL-001", "files": ["legacy/*.py"]},
        ]

        with patch(
            "warden.pipeline.application.orchestrator.suppression_filter.logger"
        ) as mock_logger:
            SuppressionFilter.apply_config_suppressions(findings, suppressions, context=ctx)

            summary_calls = [
                c for c in mock_logger.info.call_args_list
                if c[0][0] == "suppression_filter_summary"
            ]
            assert len(summary_calls) == 0


class TestSuppressionFilterBackwardCompatibility:
    """Test that the filter works correctly without a context parameter."""

    def test_works_without_context(self):
        """Test that suppression still filters correctly when context is None."""
        findings = [
            _make_finding("SQL-001", file_path="legacy/db.py"),
            _make_finding("XSS-001", file_path="src/app.py"),
        ]
        suppressions = [
            {"rule": "SQL-001", "files": ["legacy/*.py"]},
        ]

        result = SuppressionFilter.apply_config_suppressions(findings, suppressions)

        assert len(result) == 1
        assert result[0].id == "XSS-001"

    def test_works_with_empty_findings(self):
        """Test that empty findings list is returned unchanged."""
        result = SuppressionFilter.apply_config_suppressions([], [{"rule": "*", "files": ["*.py"]}])
        assert result == []

    def test_works_with_empty_suppressions(self):
        """Test that all findings pass through with empty suppressions."""
        findings = [_make_finding("SQL-001")]
        result = SuppressionFilter.apply_config_suppressions(findings, [])
        assert len(result) == 1

    def test_wildcard_rule_suppresses_all_matching_files(self):
        """Test that rule='*' matches any finding ID for matching files."""
        ctx = _make_context()
        findings = [
            _make_finding("SQL-001", file_path="test/test_app.py"),
            _make_finding("XSS-002", file_path="test/test_views.py"),
            _make_finding("CSRF-003", file_path="src/app.py"),
        ]
        suppressions = [
            {"rule": "*", "files": ["test/*.py"]},
        ]

        result = SuppressionFilter.apply_config_suppressions(findings, suppressions, context=ctx)

        assert len(result) == 1
        assert result[0].id == "CSRF-003"
        assert len(ctx.suppressed_findings) == 2


class TestPipelineContextSuppressedFindings:
    """Test PipelineContext suppressed_findings field and methods."""

    def test_suppressed_findings_empty_by_default(self):
        """Test that suppressed_findings starts as an empty list."""
        ctx = _make_context()
        assert ctx.suppressed_findings == []

    def test_add_suppressed_finding_method(self):
        """Test that add_suppressed_finding records are stored correctly."""
        ctx = _make_context()
        record = {
            "id": "SQL-001",
            "file": "app.py",
            "title": "SQL injection",
            "severity": "high",
            "matched_rule": "SQL-001",
            "matched_files": ["*.py"],
            "timestamp": "2026-02-26T12:00:00+00:00",
        }
        ctx.add_suppressed_finding(record)

        assert len(ctx.suppressed_findings) == 1
        assert ctx.suppressed_findings[0] == record

    def test_suppressed_findings_in_summary(self):
        """Test that get_summary includes suppression count."""
        ctx = _make_context()
        ctx.suppressed_findings = [
            {"id": "SQL-001", "file": "app.py", "title": "SQL injection", "severity": "high",
             "matched_rule": "SQL-001", "matched_files": ["*.py"], "timestamp": "2026-02-26T12:00:00+00:00"},
            {"id": "XSS-001", "file": "views.py", "title": "XSS vulnerability", "severity": "medium",
             "matched_rule": "XSS-001", "matched_files": ["*.py"], "timestamp": "2026-02-26T12:00:00+00:00"},
        ]

        summary = ctx.get_summary()
        assert "Suppressed Findings: 2" in summary

    def test_suppressed_findings_not_in_summary_when_empty(self):
        """Test that get_summary does not mention suppressed findings when empty."""
        ctx = _make_context()
        summary = ctx.get_summary()
        assert "Suppressed" not in summary

    def test_suppressed_findings_in_to_json(self):
        """Test that to_json includes suppressed_findings data."""
        ctx = _make_context()
        ctx.suppressed_findings = [
            {"id": "SQL-001", "file": "app.py", "title": "SQL injection", "severity": "high",
             "matched_rule": "SQL-001", "matched_files": ["*.py"], "timestamp": "2026-02-26T12:00:00+00:00"},
        ]

        json_data = ctx.to_json()
        assert json_data["suppressed_findings_count"] == 1
        assert len(json_data["suppressed_findings"]) == 1
        assert json_data["suppressed_findings"][0]["id"] == "SQL-001"

    def test_suppressed_findings_in_context_for_phase(self):
        """Test that get_context_for_phase includes suppressed_findings for FORTIFICATION phase."""
        ctx = _make_context()
        ctx.suppressed_findings = [
            {"id": "SQL-001", "file": "app.py", "title": "SQL injection", "severity": "high",
             "matched_rule": "SQL-001", "matched_files": ["*.py"], "timestamp": "2026-02-26T12:00:00+00:00"},
        ]

        phase_ctx = ctx.get_context_for_phase("FORTIFICATION")
        assert "suppressed_findings" in phase_ctx
        assert len(phase_ctx["suppressed_findings"]) == 1

    def test_suppressed_findings_memory_bounded(self):
        """Test that suppressed_findings respects memory bounds."""
        ctx = _make_context()
        # Fill beyond MAX_LIST_SIZE
        for i in range(ctx.MAX_LIST_SIZE + 10):
            ctx.add_suppressed_finding({"id": f"FIND-{i}"})

        assert len(ctx.suppressed_findings) == ctx.MAX_LIST_SIZE

    def test_suppressed_findings_in_llm_context(self):
        """Test that suppressed findings count appears in LLM context prompt."""
        ctx = _make_context()
        ctx.suppressed_findings = [
            {"id": "SQL-001", "file": "app.py", "title": "SQL injection", "severity": "high",
             "matched_rule": "SQL-001", "matched_files": ["*.py"], "timestamp": "2026-02-26T12:00:00+00:00"},
        ]

        prompt = ctx.get_llm_context_prompt("VALIDATION")
        assert "SUPPRESSED: 1 findings" in prompt
