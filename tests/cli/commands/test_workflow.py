"""
Unit tests for warden.cli.commands.workflow.

Tests cover:
- Preset registry: known presets, unknown preset lookup
- list_presets() ordering and completeness
- workflow list command output
- workflow run command: unknown preset exits 1
- workflow run command: dry-run mode does not call scan
- workflow run command: happy path delegates to scan_command with correct kwargs
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from warden.cli.commands.workflow import (
    PRESETS,
    get_preset,
    list_presets,
    workflow_app,
)

runner = CliRunner()


# ---------------------------------------------------------------------------
# get_preset()
# ---------------------------------------------------------------------------


class TestGetPreset:
    def test_returns_preset_for_known_name(self):
        preset = get_preset("ci")
        assert preset is not None
        assert preset.name == "ci"

    def test_returns_none_for_unknown_name(self):
        assert get_preset("does-not-exist") is None

    @pytest.mark.parametrize("name", ["ci", "security-audit", "pre-commit", "nightly"])
    def test_all_documented_presets_exist(self, name: str):
        preset = get_preset(name)
        assert preset is not None, f"Preset '{name}' not found in registry"

    def test_ci_preset_kwargs(self):
        preset = get_preset("ci")
        assert preset.scan_kwargs.get("level") == "basic"
        assert preset.scan_kwargs.get("no_preflight") is True
        assert preset.scan_kwargs.get("ci") is True

    def test_security_audit_preset_kwargs(self):
        preset = get_preset("security-audit")
        assert preset.scan_kwargs.get("level") == "deep"
        assert preset.scan_kwargs.get("format") == "sarif"

    def test_pre_commit_preset_kwargs(self):
        preset = get_preset("pre-commit")
        assert preset.scan_kwargs.get("level") == "standard"
        assert preset.scan_kwargs.get("diff") is True
        assert preset.scan_kwargs.get("base") == "HEAD"

    def test_nightly_preset_kwargs(self):
        preset = get_preset("nightly")
        assert preset.scan_kwargs.get("level") == "standard"
        assert preset.scan_kwargs.get("format") == "sarif"
        assert ".warden/reports/" in str(preset.scan_kwargs.get("output", ""))


# ---------------------------------------------------------------------------
# list_presets()
# ---------------------------------------------------------------------------


class TestListPresets:
    def test_returns_all_presets(self):
        presets = list_presets()
        assert len(presets) == len(PRESETS)

    def test_returns_sorted_by_name(self):
        presets = list_presets()
        names = [p.name for p in presets]
        assert names == sorted(names)

    def test_each_preset_has_description(self):
        for preset in list_presets():
            assert preset.description, f"Preset '{preset.name}' has no description"

    def test_each_preset_has_scan_kwargs(self):
        for preset in list_presets():
            assert preset.scan_kwargs, f"Preset '{preset.name}' has empty scan_kwargs"


# ---------------------------------------------------------------------------
# workflow list command
# ---------------------------------------------------------------------------


class TestWorkflowListCommand:
    def test_list_shows_preset_names(self):
        result = runner.invoke(workflow_app, ["list"])
        assert result.exit_code == 0
        for name in PRESETS:
            assert name in result.output

    def test_list_shows_run_hint(self):
        result = runner.invoke(workflow_app, ["list"])
        assert result.exit_code == 0
        assert "warden workflow run" in result.output


# ---------------------------------------------------------------------------
# workflow run command — unknown preset
# ---------------------------------------------------------------------------


class TestWorkflowRunUnknownPreset:
    def test_exits_with_code_1_for_unknown_preset(self):
        result = runner.invoke(workflow_app, ["run", "unknown-preset"])
        assert result.exit_code == 1

    def test_prints_available_presets_on_unknown(self):
        result = runner.invoke(workflow_app, ["run", "unknown-preset"])
        # Should mention available presets
        for name in PRESETS:
            assert name in result.output


# ---------------------------------------------------------------------------
# workflow run command — dry-run
# ---------------------------------------------------------------------------


class TestWorkflowRunDryRun:
    def test_dry_run_does_not_call_scan(self):
        # scan_command is imported lazily inside workflow_run(), so patch at source
        with patch("warden.cli.commands.scan.scan_command") as mock_scan:
            result = runner.invoke(workflow_app, ["run", "ci", "--dry-run"])
        assert result.exit_code == 0
        mock_scan.assert_not_called()

    def test_dry_run_prints_dry_run_message(self):
        result = runner.invoke(workflow_app, ["run", "ci", "--dry-run"])
        assert result.exit_code == 0
        assert "Dry-run" in result.output or "dry-run" in result.output.lower()

    def test_dry_run_shows_preset_description(self):
        result = runner.invoke(workflow_app, ["run", "nightly", "--dry-run"])
        assert result.exit_code == 0
        assert "nightly" in result.output


# ---------------------------------------------------------------------------
# workflow run command — happy path
# ---------------------------------------------------------------------------


class TestWorkflowRunHappyPath:
    # scan_command is imported lazily inside workflow_run() via:
    #   from warden.cli.commands.scan import scan_command
    # Patching at 'warden.cli.commands.scan.scan_command' replaces the
    # attribute on the scan module so the lazy import inside workflow_run()
    # picks up the mock.
    _PATCH_TARGET = "warden.cli.commands.scan.scan_command"

    def test_run_ci_calls_scan_command_with_correct_level(self):
        captured_kwargs: dict = {}

        def fake_scan(**kwargs):
            captured_kwargs.update(kwargs)

        with patch(self._PATCH_TARGET, side_effect=fake_scan):
            result = runner.invoke(workflow_app, ["run", "ci"])

        assert result.exit_code == 0
        assert captured_kwargs.get("level") == "basic"
        assert captured_kwargs.get("no_preflight") is True
        assert captured_kwargs.get("ci") is True

    def test_run_security_audit_uses_sarif_format(self):
        captured_kwargs: dict = {}

        def fake_scan(**kwargs):
            captured_kwargs.update(kwargs)

        with patch(self._PATCH_TARGET, side_effect=fake_scan):
            result = runner.invoke(workflow_app, ["run", "security-audit"])

        assert result.exit_code == 0
        assert captured_kwargs.get("level") == "deep"
        assert captured_kwargs.get("format") == "sarif"

    def test_run_pre_commit_enables_diff(self):
        captured_kwargs: dict = {}

        def fake_scan(**kwargs):
            captured_kwargs.update(kwargs)

        with patch(self._PATCH_TARGET, side_effect=fake_scan):
            result = runner.invoke(workflow_app, ["run", "pre-commit"])

        assert result.exit_code == 0
        assert captured_kwargs.get("diff") is True
        assert captured_kwargs.get("base") == "HEAD"

    def test_verbose_flag_forwarded_to_scan(self):
        captured_kwargs: dict = {}

        def fake_scan(**kwargs):
            captured_kwargs.update(kwargs)

        with patch(self._PATCH_TARGET, side_effect=fake_scan):
            result = runner.invoke(workflow_app, ["run", "ci", "--verbose"])

        assert result.exit_code == 0
        assert captured_kwargs.get("verbose") is True
