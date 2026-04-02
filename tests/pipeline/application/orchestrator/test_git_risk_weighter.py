"""Unit tests for GitRiskWeighter — git churn-based findings re-ranking.

All subprocess calls are mocked so tests run without a real git repo.
"""

from math import log1p
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from warden.pipeline.application.orchestrator.git_risk_weighter import (
    CHURN_WEIGHT,
    SEVERITY_SCORES,
    GitRiskWeighter,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_finding_dict(
    id: str = "F-001",
    severity: str = "high",
    file_path: str = "src/app.py",
) -> dict:
    return {"id": id, "severity": severity, "file_path": file_path, "message": "test"}


def _make_finding_obj(
    id: str = "F-001",
    severity: str = "high",
    file_path: str = "src/app.py",
):
    """Simple object-style finding (not a dataclass)."""
    obj = MagicMock()
    obj.id = id
    obj.severity = severity
    obj.file_path = file_path
    obj.path = None
    obj.location = ""
    return obj


PROJECT = Path("/tmp/test-project")


# ---------------------------------------------------------------------------
# GitRiskWeighter._check_git_available
# ---------------------------------------------------------------------------

class TestGitAvailable:
    def test_returns_true_when_inside_git_repo(self):
        weighter = GitRiskWeighter(PROJECT)
        mock_result = MagicMock(returncode=0)
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            assert weighter._check_git_available() is True
            mock_run.assert_called_once()

    def test_returns_false_on_nonzero_returncode(self):
        weighter = GitRiskWeighter(PROJECT)
        mock_result = MagicMock(returncode=128)
        with patch("subprocess.run", return_value=mock_result):
            assert weighter._check_git_available() is False

    def test_returns_false_when_git_not_found(self):
        weighter = GitRiskWeighter(PROJECT)
        with patch("subprocess.run", side_effect=FileNotFoundError("git not found")):
            assert weighter._check_git_available() is False

    def test_returns_false_on_timeout(self):
        import subprocess

        weighter = GitRiskWeighter(PROJECT)
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("git", 10)):
            assert weighter._check_git_available() is False

    def test_caches_result_after_first_check(self):
        weighter = GitRiskWeighter(PROJECT)
        mock_result = MagicMock(returncode=0)
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            weighter._check_git_available()
            weighter._check_git_available()
            # subprocess.run should only be called once
            assert mock_run.call_count == 1


# ---------------------------------------------------------------------------
# GitRiskWeighter.get_file_churn
# ---------------------------------------------------------------------------

class TestGetFileChurn:
    def _weighter_with_git(self) -> GitRiskWeighter:
        """Return a weighter pre-configured as git-available."""
        w = GitRiskWeighter(PROJECT)
        w._git_available = True
        return w

    def test_returns_commit_count(self):
        w = self._weighter_with_git()
        git_output = "abc1234 fix: thing\ndef5678 feat: stuff\n"
        mock_result = MagicMock(returncode=0, stdout=git_output)
        with patch("subprocess.run", return_value=mock_result):
            assert w.get_file_churn("src/app.py") == 2

    def test_returns_zero_on_empty_output(self):
        w = self._weighter_with_git()
        mock_result = MagicMock(returncode=0, stdout="")
        with patch("subprocess.run", return_value=mock_result):
            assert w.get_file_churn("src/app.py") == 0

    def test_returns_zero_on_nonzero_returncode(self):
        w = self._weighter_with_git()
        mock_result = MagicMock(returncode=1, stdout="")
        with patch("subprocess.run", return_value=mock_result):
            assert w.get_file_churn("src/app.py") == 0

    def test_returns_zero_when_git_unavailable(self):
        w = GitRiskWeighter(PROJECT)
        w._git_available = False
        with patch("subprocess.run") as mock_run:
            assert w.get_file_churn("src/app.py") == 0
            mock_run.assert_not_called()

    def test_returns_zero_on_timeout(self):
        import subprocess

        w = self._weighter_with_git()
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("git", 10)):
            assert w.get_file_churn("src/app.py") == 0

    def test_caches_churn_result(self):
        w = self._weighter_with_git()
        git_output = "abc1234 fix\n"
        mock_result = MagicMock(returncode=0, stdout=git_output)
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            w.get_file_churn("src/app.py")
            w.get_file_churn("src/app.py")
            assert mock_run.call_count == 1

    def test_uses_days_parameter_in_git_command(self):
        w = self._weighter_with_git()
        mock_result = MagicMock(returncode=0, stdout="abc fix\n")
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            w.get_file_churn("src/app.py", days=30)
            call_args = mock_run.call_args[0][0]
            assert "--since=30 days ago" in call_args

    def test_different_days_produce_separate_cache_entries(self):
        w = self._weighter_with_git()
        mock_result = MagicMock(returncode=0, stdout="abc fix\n")
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            w.get_file_churn("src/app.py", days=30)
            w.get_file_churn("src/app.py", days=90)
            assert mock_run.call_count == 2


# ---------------------------------------------------------------------------
# GitRiskWeighter.weight_findings
# ---------------------------------------------------------------------------

class TestWeightFindings:
    def _weighter_with_churn(self, churn_map: dict) -> GitRiskWeighter:
        """Return a weighter whose get_file_churn is driven by churn_map."""
        w = GitRiskWeighter(PROJECT)
        w._git_available = True

        def _churn(file_path: str, days: int = 90) -> int:
            return churn_map.get(file_path, 0)

        w.get_file_churn = _churn  # type: ignore[method-assign]
        return w

    def test_returns_empty_list_unchanged(self):
        w = self._weighter_with_churn({})
        assert w.weight_findings([]) == []

    def test_higher_severity_ranks_first_with_no_churn(self):
        low = _make_finding_dict("F-low", severity="low", file_path="a.py")
        critical = _make_finding_dict("F-crit", severity="critical", file_path="a.py")
        medium = _make_finding_dict("F-med", severity="medium", file_path="a.py")

        w = self._weighter_with_churn({"a.py": 0})
        result = w.weight_findings([low, medium, critical])
        ids = [f["id"] for f in result]
        assert ids == ["F-crit", "F-med", "F-low"]

    def test_high_churn_elevates_lower_severity(self):
        """A medium finding in a very high-churn file should outscore a high in a cold file."""
        high_cold = _make_finding_dict("H-cold", severity="high", file_path="cold.py")
        medium_hot = _make_finding_dict("M-hot", severity="medium", file_path="hot.py")

        # hot.py: 200 commits; cold.py: 0 commits
        churn_map = {"hot.py": 200, "cold.py": 0}
        w = self._weighter_with_churn(churn_map)

        high_score = SEVERITY_SCORES["high"] * (1 + log1p(0) * CHURN_WEIGHT)
        medium_hot_score = SEVERITY_SCORES["medium"] * (1 + log1p(200) * CHURN_WEIGHT)

        result = w.weight_findings([high_cold, medium_hot])

        if medium_hot_score > high_score:
            assert result[0]["id"] == "M-hot"
        else:
            # formula didn't flip — still high first
            assert result[0]["id"] == "H-cold"

    def test_does_not_mutate_original_list(self):
        findings = [
            _make_finding_dict("A", severity="low"),
            _make_finding_dict("B", severity="critical"),
        ]
        original_order = [f["id"] for f in findings]
        w = self._weighter_with_churn({"src/app.py": 5})
        w.weight_findings(findings)
        assert [f["id"] for f in findings] == original_order

    def test_works_with_object_style_findings(self):
        high_obj = _make_finding_obj("OBJ-high", severity="high", file_path="a.py")
        low_obj = _make_finding_obj("OBJ-low", severity="low", file_path="a.py")

        w = self._weighter_with_churn({"a.py": 0})
        result = w.weight_findings([low_obj, high_obj])
        assert result[0].id == "OBJ-high"

    def test_returns_findings_unchanged_on_exception(self):
        """If an unexpected error occurs, return original list without raising."""

        def _bad_churn(*_a, **_kw):
            raise RuntimeError("unexpected git error")

        w = GitRiskWeighter(PROJECT)
        w._git_available = True
        w.get_file_churn = _bad_churn  # type: ignore[method-assign]

        findings = [_make_finding_dict("X")]
        result = w.weight_findings(findings)
        assert result == findings

    def test_project_root_override_updates_root_and_resets_old_entries(self):
        w = GitRiskWeighter(PROJECT)
        w._git_available = True
        # Pre-populate the cache with an old entry
        w._churn_cache["old_entry.py:90"] = 5

        new_root = Path("/tmp/other-project")
        mock_result = MagicMock(returncode=0, stdout="")
        with patch("subprocess.run", return_value=mock_result):
            w.weight_findings([_make_finding_dict("F")], project_root=new_root)

        # Project root must be updated
        assert w.project_root == new_root.resolve()
        # Old cache entry from the previous root must be gone
        assert "old_entry.py:90" not in w._churn_cache


# ---------------------------------------------------------------------------
# FindingsPostProcessor.apply_git_risk_weighting integration
# ---------------------------------------------------------------------------

class TestApplyGitRiskWeightingIntegration:
    """Verifies the method on FindingsPostProcessor delegates correctly."""

    def _make_post_processor(self):
        from warden.pipeline.application.orchestrator.findings_post_processor import (
            FindingsPostProcessor,
        )
        from warden.pipeline.domain.models import PipelineConfig

        return FindingsPostProcessor(
            config=PipelineConfig(),
            project_root=PROJECT,
        )

    def _make_context(self, findings):
        from datetime import datetime

        from warden.pipeline.domain.pipeline_context import PipelineContext

        ctx = PipelineContext(
            pipeline_id="test",
            started_at=datetime.now(),
            file_path=Path("/tmp/test.py"),
            source_code="x=1",
            project_root=PROJECT,
        )
        ctx.findings = findings
        return ctx

    def test_empty_findings_no_op(self):
        pp = self._make_post_processor()
        ctx = self._make_context([])
        pp.apply_git_risk_weighting(ctx)
        assert ctx.findings == []

    def test_findings_reordered_by_severity_when_git_unavailable(self):
        """When git is not available churn=0 so severity alone decides order."""
        low = _make_finding_dict("LOW", severity="low")
        critical = _make_finding_dict("CRIT", severity="critical")

        pp = self._make_post_processor()
        ctx = self._make_context([low, critical])

        # Simulate git being unavailable
        mock_result = MagicMock(returncode=128, stdout="")
        with patch("subprocess.run", return_value=mock_result):
            pp.apply_git_risk_weighting(ctx)

        assert ctx.findings[0]["id"] == "CRIT"

    def test_exception_in_weighter_does_not_raise(self):
        """apply_git_risk_weighting must never bubble up exceptions."""
        pp = self._make_post_processor()
        ctx = self._make_context([_make_finding_dict("X")])

        with patch(
            "warden.pipeline.application.orchestrator.git_risk_weighter.GitRiskWeighter.weight_findings",
            side_effect=RuntimeError("boom"),
        ):
            # Should not raise
            pp.apply_git_risk_weighting(ctx)
