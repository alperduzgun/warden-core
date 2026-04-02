"""
Unit tests for warden.cli.commands.feedback.

Tests cover:
- Finding resolution from report dicts
- Pattern building from finding lists
- Learned-pattern persistence (merge / increment)
- Loading learned patterns
- CLI mark command (happy path, missing IDs, no-report)
- CLI list command (no patterns, with patterns)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml
from typer.testing import CliRunner

from warden.cli.commands.feedback import (
    _build_patterns_from_findings,
    _collect_all_findings,
    _load_report,
    _resolve_finding_ids,
    feedback_app,
)
from warden.classification.application.llm_classification_phase import (
    LLMClassificationPhase,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_FINDING_A = {
    "id": "W001",
    "rule_id": "W001",
    "file_path": "src/auth.py",
    "message": "Hardcoded secret detected",
    "severity": "critical",
}

SAMPLE_FINDING_B = {
    "id": "W002",
    "rule_id": "W002",
    "file_path": "src/db.py",
    "message": "SQL injection risk",
    "severity": "high",
}

SAMPLE_REPORT = {
    "pipelineId": "test-pipeline-001",
    "metadata": {"scan_id": "abc123"},
    "findings": [SAMPLE_FINDING_A],
    "frameResults": [
        {
            "frameId": "security",
            "findings": [SAMPLE_FINDING_B],
        }
    ],
}


@pytest.fixture()
def report_file(tmp_path: Path) -> Path:
    """Write a sample report into a tmp .warden/reports directory."""
    reports_dir = tmp_path / ".warden" / "reports"
    reports_dir.mkdir(parents=True)
    report_path = reports_dir / "warden-report.json"
    report_path.write_text(json.dumps(SAMPLE_REPORT))
    return tmp_path


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


# ---------------------------------------------------------------------------
# _collect_all_findings
# ---------------------------------------------------------------------------


class TestCollectAllFindings:
    def test_collects_top_level_and_frame_findings(self) -> None:
        findings = _collect_all_findings(SAMPLE_REPORT)
        ids = {f["id"] for f in findings}
        assert "W001" in ids
        assert "W002" in ids

    def test_deduplicates_same_id_and_path(self) -> None:
        report = {
            "findings": [SAMPLE_FINDING_A, SAMPLE_FINDING_A],
            "frameResults": [],
        }
        findings = _collect_all_findings(report)
        assert len([f for f in findings if f["id"] == "W001"]) == 1

    def test_empty_report(self) -> None:
        assert _collect_all_findings({}) == []


# ---------------------------------------------------------------------------
# _resolve_finding_ids
# ---------------------------------------------------------------------------


class TestResolveFindingIds:
    def test_resolves_exact_id(self) -> None:
        all_findings = [SAMPLE_FINDING_A, SAMPLE_FINDING_B]
        matched, unmatched = _resolve_finding_ids(["W001"], all_findings)
        assert len(matched) == 1
        assert matched[0]["id"] == "W001"
        assert unmatched == []

    def test_unmatched_id_returned(self) -> None:
        all_findings = [SAMPLE_FINDING_A]
        matched, unmatched = _resolve_finding_ids(["W999"], all_findings)
        assert matched == []
        assert "W999" in unmatched

    def test_empty_requested_ids(self) -> None:
        matched, unmatched = _resolve_finding_ids([], [SAMPLE_FINDING_A])
        assert matched == []
        assert unmatched == []


# ---------------------------------------------------------------------------
# _load_report
# ---------------------------------------------------------------------------


class TestLoadReport:
    def test_loads_latest_report_without_scan_id(self, report_file: Path) -> None:
        data = _load_report(report_file, None)
        assert data["pipelineId"] == "test-pipeline-001"

    def test_loads_report_by_scan_id(self, report_file: Path) -> None:
        data = _load_report(report_file, "abc123")
        assert data["metadata"]["scan_id"] == "abc123"

    def test_raises_when_no_report_exists(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="No warden-report"):
            _load_report(tmp_path, None)

    def test_raises_for_unknown_scan_id(self, report_file: Path) -> None:
        with pytest.raises(FileNotFoundError, match="scan_id 'xyz'"):
            _load_report(report_file, "xyz")


# ---------------------------------------------------------------------------
# _build_patterns_from_findings
# ---------------------------------------------------------------------------


class TestBuildPatternsFromFindings:
    def test_fp_findings_produce_false_positive_patterns(self) -> None:
        result = _build_patterns_from_findings([SAMPLE_FINDING_A], [])
        patterns = result["patterns"]
        assert len(patterns) == 1
        assert patterns[0]["type"] == "false_positive"
        assert patterns[0]["rule_id"] == "W001"

    def test_tp_findings_produce_true_positive_patterns(self) -> None:
        result = _build_patterns_from_findings([], [SAMPLE_FINDING_B])
        patterns = result["patterns"]
        assert len(patterns) == 1
        assert patterns[0]["type"] == "true_positive"
        assert patterns[0]["rule_id"] == "W002"

    def test_mixed_findings(self) -> None:
        result = _build_patterns_from_findings([SAMPLE_FINDING_A], [SAMPLE_FINDING_B])
        patterns = result["patterns"]
        assert len(patterns) == 2
        types = {p["type"] for p in patterns}
        assert types == {"false_positive", "true_positive"}

    def test_version_is_set(self) -> None:
        result = _build_patterns_from_findings([], [])
        assert result["version"] == 1


# ---------------------------------------------------------------------------
# LLMClassificationPhase._persist_learned_patterns
# ---------------------------------------------------------------------------


class TestPersistLearnedPatterns:
    def test_creates_file_on_first_write(self, tmp_path: Path) -> None:
        patterns = {
            "version": 1,
            "patterns": [
                {
                    "rule_id": "W001",
                    "file_pattern": "auth.py",
                    "message_pattern": "Hardcoded",
                    "type": "false_positive",
                    "occurrence_count": 1,
                    "confidence": 0.5,
                    "first_seen": "2026-04-01T00:00:00+00:00",
                    "last_seen": "2026-04-01T00:00:00+00:00",
                }
            ],
        }
        LLMClassificationPhase._persist_learned_patterns(patterns, tmp_path)

        patterns_file = tmp_path / ".warden" / "learned_patterns.yaml"
        assert patterns_file.exists()

        with open(patterns_file) as f:
            loaded = yaml.safe_load(f)

        assert loaded["version"] == 1
        assert len(loaded["patterns"]) == 1

    def test_increments_occurrence_count_on_duplicate(self, tmp_path: Path) -> None:
        pattern = {
            "rule_id": "W001",
            "file_pattern": "auth.py",
            "message_pattern": "Hardcoded",
            "type": "false_positive",
            "occurrence_count": 1,
            "confidence": 0.5,
            "first_seen": "2026-04-01T00:00:00+00:00",
            "last_seen": "2026-04-01T00:00:00+00:00",
        }
        batch = {"version": 1, "patterns": [pattern]}

        # Write twice
        LLMClassificationPhase._persist_learned_patterns(batch, tmp_path)
        LLMClassificationPhase._persist_learned_patterns(batch, tmp_path)

        patterns_file = tmp_path / ".warden" / "learned_patterns.yaml"
        with open(patterns_file) as f:
            loaded = yaml.safe_load(f)

        assert len(loaded["patterns"]) == 1
        assert loaded["patterns"][0]["occurrence_count"] == 2

    def test_confidence_increases_with_occurrences(self, tmp_path: Path) -> None:
        pattern = {
            "rule_id": "W001",
            "file_pattern": "auth.py",
            "message_pattern": "Hardcoded",
            "type": "false_positive",
            "occurrence_count": 1,
            "confidence": 0.5,
            "first_seen": "2026-04-01T00:00:00+00:00",
            "last_seen": "2026-04-01T00:00:00+00:00",
        }
        batch = {"version": 1, "patterns": [pattern]}

        # Write four times → occurrence_count = 4 → confidence = min(1.0, 4/2) = 1.0
        for _ in range(4):
            LLMClassificationPhase._persist_learned_patterns(batch, tmp_path)

        patterns_file = tmp_path / ".warden" / "learned_patterns.yaml"
        with open(patterns_file) as f:
            loaded = yaml.safe_load(f)

        assert loaded["patterns"][0]["confidence"] == 1.0

    def test_appends_new_patterns(self, tmp_path: Path) -> None:
        p1 = {
            "rule_id": "W001",
            "file_pattern": "auth.py",
            "message_pattern": "Hardcoded",
            "type": "false_positive",
            "occurrence_count": 1,
            "confidence": 0.5,
            "first_seen": "2026-04-01T00:00:00+00:00",
            "last_seen": "2026-04-01T00:00:00+00:00",
        }
        p2 = {
            "rule_id": "W002",
            "file_pattern": "db.py",
            "message_pattern": "SQL",
            "type": "false_positive",
            "occurrence_count": 1,
            "confidence": 0.5,
            "first_seen": "2026-04-01T00:00:00+00:00",
            "last_seen": "2026-04-01T00:00:00+00:00",
        }
        LLMClassificationPhase._persist_learned_patterns({"version": 1, "patterns": [p1]}, tmp_path)
        LLMClassificationPhase._persist_learned_patterns({"version": 1, "patterns": [p2]}, tmp_path)

        patterns_file = tmp_path / ".warden" / "learned_patterns.yaml"
        with open(patterns_file) as f:
            loaded = yaml.safe_load(f)

        assert len(loaded["patterns"]) == 2


# ---------------------------------------------------------------------------
# LLMClassificationPhase._load_learned_patterns
# ---------------------------------------------------------------------------


class TestLoadLearnedPatterns:
    def test_returns_empty_list_when_no_file(self, tmp_path: Path) -> None:
        result = LLMClassificationPhase._load_learned_patterns(tmp_path)
        assert result == []

    def test_loads_patterns_from_file(self, tmp_path: Path) -> None:
        patterns_dir = tmp_path / ".warden"
        patterns_dir.mkdir()
        patterns_file = patterns_dir / "learned_patterns.yaml"
        data = {
            "version": 1,
            "patterns": [
                {
                    "rule_id": "W001",
                    "file_pattern": "auth.py",
                    "message_pattern": "Hardcoded",
                    "type": "false_positive",
                    "occurrence_count": 3,
                    "confidence": 0.9,
                    "first_seen": "2026-04-01T00:00:00+00:00",
                    "last_seen": "2026-04-02T00:00:00+00:00",
                }
            ],
        }
        patterns_file.write_text(yaml.safe_dump(data))

        result = LLMClassificationPhase._load_learned_patterns(tmp_path)
        assert len(result) == 1
        assert result[0]["rule_id"] == "W001"

    def test_returns_empty_on_corrupt_file(self, tmp_path: Path) -> None:
        patterns_dir = tmp_path / ".warden"
        patterns_dir.mkdir()
        (patterns_dir / "learned_patterns.yaml").write_text(": invalid: yaml: [\n")

        result = LLMClassificationPhase._load_learned_patterns(tmp_path)
        assert result == []


# ---------------------------------------------------------------------------
# FindingsPostProcessor.suppress_learned_false_positives
# ---------------------------------------------------------------------------


class TestSuppressLearnedFalsePositives:
    def _make_finding(self, rule_id: str, file_path: str, message: str) -> MagicMock:
        f = MagicMock()
        f.id = rule_id
        f.file_path = file_path
        f.message = message
        return f

    def _make_context(self, findings: list) -> MagicMock:
        result_obj = MagicMock()
        result_obj.findings = list(findings)
        result_obj.issues_found = len(findings)
        result_obj.status = "failed"
        result_obj.metadata = {}

        frame_results = {"security": {"result": result_obj}}

        ctx = MagicMock()
        ctx.frame_results = frame_results
        ctx.findings = list(findings)
        return ctx

    def test_suppresses_matching_high_confidence_pattern(self, tmp_path: Path) -> None:
        from warden.pipeline.application.orchestrator.findings_post_processor import (
            FindingsPostProcessor,
        )
        from warden.pipeline.domain.models import PipelineConfig

        # Write a high-confidence pattern
        pattern = {
            "rule_id": "W001",
            "file_pattern": "auth.py",
            "message_pattern": "Hardcoded",
            "type": "false_positive",
            "occurrence_count": 2,
            "confidence": 1.0,
            "first_seen": "2026-04-01T00:00:00+00:00",
            "last_seen": "2026-04-01T00:00:00+00:00",
        }
        patterns_dir = tmp_path / ".warden"
        patterns_dir.mkdir()
        (patterns_dir / "learned_patterns.yaml").write_text(
            yaml.safe_dump({"version": 1, "patterns": [pattern]})
        )

        cfg = MagicMock(spec=PipelineConfig)
        processor = FindingsPostProcessor(config=cfg, project_root=tmp_path)

        finding = self._make_finding("W001", "src/auth.py", "Hardcoded secret")
        ctx = self._make_context([finding])

        processor.suppress_learned_false_positives(ctx)

        result_obj = ctx.frame_results["security"]["result"]
        assert len(result_obj.findings) == 0

    def test_does_not_suppress_low_confidence_pattern(self, tmp_path: Path) -> None:
        from warden.pipeline.application.orchestrator.findings_post_processor import (
            FindingsPostProcessor,
        )
        from warden.pipeline.domain.models import PipelineConfig

        pattern = {
            "rule_id": "W001",
            "file_pattern": "auth.py",
            "message_pattern": "Hardcoded",
            "type": "false_positive",
            "occurrence_count": 1,
            "confidence": 0.5,  # Below 0.8 threshold
            "first_seen": "2026-04-01T00:00:00+00:00",
            "last_seen": "2026-04-01T00:00:00+00:00",
        }
        patterns_dir = tmp_path / ".warden"
        patterns_dir.mkdir()
        (patterns_dir / "learned_patterns.yaml").write_text(
            yaml.safe_dump({"version": 1, "patterns": [pattern]})
        )

        cfg = MagicMock(spec=PipelineConfig)
        processor = FindingsPostProcessor(config=cfg, project_root=tmp_path)

        finding = self._make_finding("W001", "src/auth.py", "Hardcoded secret")
        ctx = self._make_context([finding])

        processor.suppress_learned_false_positives(ctx)

        result_obj = ctx.frame_results["security"]["result"]
        assert len(result_obj.findings) == 1

    def test_skips_when_no_patterns_file(self, tmp_path: Path) -> None:
        from warden.pipeline.application.orchestrator.findings_post_processor import (
            FindingsPostProcessor,
        )
        from warden.pipeline.domain.models import PipelineConfig

        cfg = MagicMock(spec=PipelineConfig)
        processor = FindingsPostProcessor(config=cfg, project_root=tmp_path)

        finding = self._make_finding("W001", "src/auth.py", "Hardcoded secret")
        ctx = self._make_context([finding])

        processor.suppress_learned_false_positives(ctx)

        result_obj = ctx.frame_results["security"]["result"]
        assert len(result_obj.findings) == 1


# ---------------------------------------------------------------------------
# CLI integration tests (typer CliRunner)
# ---------------------------------------------------------------------------


class TestFeedbackCLI:
    def test_list_no_patterns(self, runner: CliRunner, tmp_path: Path) -> None:
        result = runner.invoke(
            feedback_app, ["list", "--project", str(tmp_path)]
        )
        assert result.exit_code == 0
        assert "No learned patterns" in result.output

    def test_list_with_patterns(self, runner: CliRunner, tmp_path: Path) -> None:
        patterns_dir = tmp_path / ".warden"
        patterns_dir.mkdir()
        data = {
            "version": 1,
            "patterns": [
                {
                    "rule_id": "W001",
                    "file_pattern": "auth.py",
                    "message_pattern": "Hardcoded",
                    "type": "false_positive",
                    "occurrence_count": 3,
                    "confidence": 0.9,
                    "first_seen": "2026-04-01T00:00:00+00:00",
                    "last_seen": "2026-04-02T00:00:00+00:00",
                }
            ],
        }
        (patterns_dir / "learned_patterns.yaml").write_text(yaml.safe_dump(data))

        result = runner.invoke(
            feedback_app, ["list", "--project", str(tmp_path)]
        )
        assert result.exit_code == 0
        assert "W001" in result.output
        assert "false_positive" in result.output

    def test_mark_fails_without_ids(self, runner: CliRunner, tmp_path: Path) -> None:
        result = runner.invoke(
            feedback_app, ["mark", "--project", str(tmp_path)]
        )
        assert result.exit_code != 0
        assert "false-positives" in result.output or "Error" in result.output

    def test_mark_fails_when_no_report(self, runner: CliRunner, tmp_path: Path) -> None:
        result = runner.invoke(
            feedback_app,
            ["mark", "--false-positives", "W001", "--project", str(tmp_path)],
        )
        assert result.exit_code != 0
        assert "No warden-report" in result.output or "Error" in result.output

    def test_mark_succeeds_with_valid_report(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        reports_dir = tmp_path / ".warden" / "reports"
        reports_dir.mkdir(parents=True)
        report_path = reports_dir / "warden-report.json"
        report_path.write_text(json.dumps(SAMPLE_REPORT))

        with patch(
            "warden.cli.commands.feedback._run_feedback_async",
            new_callable=lambda: lambda *a, **kw: AsyncMock(return_value=None)(),
        ):
            # Patch asyncio.run to run the coroutine synchronously in tests
            async def _noop(**kwargs: Any) -> None:
                return None

            with patch("warden.cli.commands.feedback.asyncio.run") as mock_run:
                mock_run.return_value = None
                result = runner.invoke(
                    feedback_app,
                    [
                        "mark",
                        "--false-positives",
                        "W001",
                        "--project",
                        str(tmp_path),
                    ],
                )

        assert result.exit_code == 0
        assert "Processing feedback" in result.output
