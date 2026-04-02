"""
Unit tests for Issue #619 — confirmation gates for destructive CLI operations.

Covers:
- confirmation.is_ci_environment() detection for CI env vars
- confirmation.confirm_destructive_operation() with --yes flag
- confirmation.confirm_destructive_operation() CI auto-confirm
- confirmation.confirm_destructive_operation() interactive Y/N input
- confirmation.confirm_destructive_operation() non-interactive stdin (fail safe)
- warden baseline reset: --yes skips prompt and deletes baseline
- warden baseline reset: cancels when user declines
- warden baseline reset: auto-confirms in CI environment
- warden baseline clear: delegates to reset
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch, MagicMock
import io

import pytest
from typer.testing import CliRunner

from warden.cli.commands.baseline import baseline_app
from warden.cli.commands.helpers.confirmation import (
    confirm_destructive_operation,
    is_ci_environment,
)


# ---------------------------------------------------------------------------
# is_ci_environment()
# ---------------------------------------------------------------------------


class TestIsCIEnvironment:
    def test_returns_false_when_no_ci_vars(self) -> None:
        ci_vars = ["CI", "GITHUB_ACTIONS", "GITLAB_CI", "CIRCLECI", "TRAVIS", "BITBUCKET_BUILD_NUMBER"]
        clean_env = {k: v for k, v in os.environ.items() if k not in ci_vars}
        with patch.dict(os.environ, clean_env, clear=True):
            assert is_ci_environment() is False

    def test_detects_ci_true(self) -> None:
        with patch.dict(os.environ, {"CI": "true"}, clear=False):
            assert is_ci_environment() is True

    def test_detects_github_actions(self) -> None:
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}, clear=False):
            assert is_ci_environment() is True

    def test_detects_gitlab_ci(self) -> None:
        with patch.dict(os.environ, {"GITLAB_CI": "true"}, clear=False):
            assert is_ci_environment() is True

    def test_detects_circleci(self) -> None:
        with patch.dict(os.environ, {"CIRCLECI": "true"}, clear=False):
            assert is_ci_environment() is True

    def test_detects_travis(self) -> None:
        with patch.dict(os.environ, {"TRAVIS": "true"}, clear=False):
            assert is_ci_environment() is True

    def test_detects_bitbucket_build_number(self) -> None:
        with patch.dict(os.environ, {"BITBUCKET_BUILD_NUMBER": "42"}, clear=False):
            assert is_ci_environment() is True

    def test_ci_false_string_not_detected(self) -> None:
        """CI=false must NOT be treated as a CI environment."""
        ci_vars = ["CI", "GITHUB_ACTIONS", "GITLAB_CI", "CIRCLECI", "TRAVIS", "BITBUCKET_BUILD_NUMBER"]
        clean_env = {k: v for k, v in os.environ.items() if k not in ci_vars}
        clean_env["CI"] = "false"
        with patch.dict(os.environ, clean_env, clear=True):
            assert is_ci_environment() is False

    def test_ci_numeric_1_detected(self) -> None:
        with patch.dict(os.environ, {"CI": "1"}, clear=False):
            assert is_ci_environment() is True


# ---------------------------------------------------------------------------
# confirm_destructive_operation()
# ---------------------------------------------------------------------------


class TestConfirmDestructiveOperation:
    def test_yes_flag_bypasses_prompt(self, capsys) -> None:
        result = confirm_destructive_operation("delete everything", yes=True)
        assert result is True
        captured = capsys.readouterr()
        assert "--yes flag set" in captured.out

    def test_ci_environment_auto_confirms(self, capsys) -> None:
        with patch.dict(os.environ, {"CI": "true"}, clear=False):
            result = confirm_destructive_operation("delete everything", yes=False)
        assert result is True
        captured = capsys.readouterr()
        assert "CI environment" in captured.out

    def test_interactive_y_confirms(self) -> None:
        with patch("sys.stdin", io.StringIO("y\n")), \
             patch("sys.stdin.isatty", return_value=True):
            result = confirm_destructive_operation("delete everything", yes=False)
        assert result is True

    def test_interactive_yes_confirms(self) -> None:
        with patch("sys.stdin", io.StringIO("yes\n")), \
             patch("sys.stdin.isatty", return_value=True), \
             patch("builtins.input", return_value="yes"):
            result = confirm_destructive_operation("delete everything", yes=False)
        assert result is True

    def test_interactive_n_declines(self) -> None:
        with patch("sys.stdin.isatty", return_value=True), \
             patch("builtins.input", return_value="n"):
            result = confirm_destructive_operation("delete everything", yes=False)
        assert result is False

    def test_interactive_empty_input_defaults_to_no(self) -> None:
        with patch("sys.stdin.isatty", return_value=True), \
             patch("builtins.input", return_value=""):
            result = confirm_destructive_operation("delete everything", yes=False)
        assert result is False

    def test_non_interactive_stdin_returns_false(self, capsys) -> None:
        with patch("sys.stdin.isatty", return_value=False), \
             patch.dict(os.environ, {}, clear=False):
            # Ensure we're not in a CI environment
            ci_vars = ["CI", "GITHUB_ACTIONS", "GITLAB_CI", "CIRCLECI", "TRAVIS"]
            clean_env = {k: v for k, v in os.environ.items() if k not in ci_vars}
            with patch.dict(os.environ, clean_env, clear=True):
                result = confirm_destructive_operation("delete everything", yes=False)
        assert result is False
        captured = capsys.readouterr()
        assert "Non-interactive" in captured.out


# ---------------------------------------------------------------------------
# warden baseline reset — CLI integration tests
# ---------------------------------------------------------------------------


class TestBaselineResetCommand:
    @pytest.fixture()
    def runner(self) -> CliRunner:
        return CliRunner()

    @pytest.fixture()
    def baseline_dir(self, tmp_path: Path) -> Path:
        """Create a fake module-based baseline directory structure."""
        bl_dir = tmp_path / ".warden" / "baseline"
        bl_dir.mkdir(parents=True)
        (bl_dir / "_meta.json").write_text('{"modules": [], "total_findings": 0, "total_debt": 0}')
        (bl_dir / "auth.json").write_text('{"module_name": "auth", "findings": []}')
        return tmp_path

    @pytest.fixture()
    def legacy_baseline(self, tmp_path: Path) -> Path:
        """Create a legacy baseline.json file."""
        warden_dir = tmp_path / ".warden"
        warden_dir.mkdir(parents=True, exist_ok=True)
        (warden_dir / "baseline.json").write_text('{"fingerprints": []}')
        return tmp_path

    def test_reset_with_yes_flag_deletes_module_baseline(
        self, runner: CliRunner, baseline_dir: Path
    ) -> None:
        with patch("pathlib.Path.cwd", return_value=baseline_dir):
            result = runner.invoke(baseline_app, ["reset", "--yes"])
        assert result.exit_code == 0
        assert not (baseline_dir / ".warden" / "baseline").exists()

    def test_reset_with_y_flag_deletes_legacy_baseline(
        self, runner: CliRunner, legacy_baseline: Path
    ) -> None:
        with patch("pathlib.Path.cwd", return_value=legacy_baseline):
            result = runner.invoke(baseline_app, ["reset", "-y"])
        assert result.exit_code == 0
        assert not (legacy_baseline / ".warden" / "baseline.json").exists()

    def test_reset_without_yes_in_ci_auto_confirms(
        self, runner: CliRunner, baseline_dir: Path
    ) -> None:
        env = {"CI": "true"}
        with patch("pathlib.Path.cwd", return_value=baseline_dir), \
             patch.dict(os.environ, env, clear=False):
            result = runner.invoke(baseline_app, ["reset"])
        assert result.exit_code == 0
        assert not (baseline_dir / ".warden" / "baseline").exists()

    def test_reset_without_yes_not_in_ci_cancels_on_n(
        self, runner: CliRunner, baseline_dir: Path
    ) -> None:
        ci_vars = ["CI", "GITHUB_ACTIONS", "GITLAB_CI", "CIRCLECI", "TRAVIS", "BITBUCKET_BUILD_NUMBER"]
        clean_env = {k: v for k, v in os.environ.items() if k not in ci_vars}

        with patch("pathlib.Path.cwd", return_value=baseline_dir), \
             patch.dict(os.environ, clean_env, clear=True), \
             patch("sys.stdin.isatty", return_value=True), \
             patch("builtins.input", return_value="n"):
            result = runner.invoke(baseline_app, ["reset"])

        assert result.exit_code == 0
        assert "cancelled" in result.output.lower()
        # Baseline must still exist — not deleted
        assert (baseline_dir / ".warden" / "baseline").exists()

    def test_reset_with_no_baseline_reports_nothing_to_delete(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        # Create .warden dir but no baseline
        (tmp_path / ".warden").mkdir(parents=True)

        with patch("pathlib.Path.cwd", return_value=tmp_path):
            result = runner.invoke(baseline_app, ["reset", "--yes"])

        assert result.exit_code == 0
        assert "nothing to delete" in result.output.lower() or "No baseline found" in result.output

    def test_reset_deletes_both_module_and_legacy(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        warden_dir = tmp_path / ".warden"
        warden_dir.mkdir(parents=True)
        # Module baseline
        bl_dir = warden_dir / "baseline"
        bl_dir.mkdir()
        (bl_dir / "_meta.json").write_text("{}")
        # Legacy baseline
        (warden_dir / "baseline.json").write_text("{}")

        with patch("pathlib.Path.cwd", return_value=tmp_path):
            result = runner.invoke(baseline_app, ["reset", "--yes"])

        assert result.exit_code == 0
        assert not bl_dir.exists()
        assert not (warden_dir / "baseline.json").exists()

    def test_github_actions_auto_confirms(
        self, runner: CliRunner, baseline_dir: Path
    ) -> None:
        env = {"GITHUB_ACTIONS": "true"}
        with patch("pathlib.Path.cwd", return_value=baseline_dir), \
             patch.dict(os.environ, env, clear=False):
            result = runner.invoke(baseline_app, ["reset"])
        assert result.exit_code == 0
        assert not (baseline_dir / ".warden" / "baseline").exists()


# ---------------------------------------------------------------------------
# warden baseline clear — delegates to reset
# ---------------------------------------------------------------------------


class TestBaselineClearCommand:
    @pytest.fixture()
    def runner(self) -> CliRunner:
        return CliRunner()

    def test_clear_with_yes_flag_deletes_baseline(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        warden_dir = tmp_path / ".warden"
        warden_dir.mkdir(parents=True)
        (warden_dir / "baseline.json").write_text("{}")

        with patch("pathlib.Path.cwd", return_value=tmp_path):
            result = runner.invoke(baseline_app, ["clear", "--yes"])

        assert result.exit_code == 0
        assert not (warden_dir / "baseline.json").exists()

    def test_clear_ci_auto_confirms(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        warden_dir = tmp_path / ".warden"
        warden_dir.mkdir(parents=True)
        (warden_dir / "baseline.json").write_text("{}")

        env = {"CI": "true"}
        with patch("pathlib.Path.cwd", return_value=tmp_path), \
             patch.dict(os.environ, env, clear=False):
            result = runner.invoke(baseline_app, ["clear"])

        assert result.exit_code == 0
        assert not (warden_dir / "baseline.json").exists()
