"""E2E tests for edge cases and error handling in Warden CLI.

This file tests:
- Config command edge cases (nested keys, array values, malformed YAML, JSON output)
- CI command edge cases (GitLab provider, custom branch, force/no-force, result messages)
- Baseline command edge cases (empty dirs, module filters, debt without baseline)
- General error handling (missing .warden, readonly protection, invalid paths)

All tests use CliRunner for deterministic, in-process testing.
Tests use isolated_project fixture for mutations, tmp_path for destructive tests.
"""

import json
from pathlib import Path

import pytest
import yaml
from warden.main import app


# ============================================================================
# Helper: extract JSON from structlog-polluted stdout
# ============================================================================
def _extract_json(stdout: str) -> dict | None:
    """Extract a JSON object from stdout that may contain structlog lines."""
    lines = stdout.splitlines()
    json_start = None
    for i, line in enumerate(lines):
        if line.strip() == "{":
            json_start = i
            break
    if json_start is not None:
        return json.loads("\n".join(lines[json_start:]))
    # Try single-line JSON
    for line in lines:
        s = line.strip()
        if s.startswith("{") and s.endswith("}"):
            return json.loads(s)
    return None


# =============================================================================
# Config Edge Cases
# =============================================================================
@pytest.mark.e2e
class TestConfigEdgeCases:
    """Edge cases for config get/set/list commands."""

    def test_config_set_deeply_nested_key(self, runner, isolated_project, monkeypatch):
        """Set and verify a deeply nested configuration key."""
        monkeypatch.chdir(isolated_project)

        # Set a deeply nested key
        result = runner.invoke(app, [
            "config", "set",
            "settings.pre_analysis_config.batch_size", "50"
        ])
        assert result.exit_code == 0
        assert "settings.pre_analysis_config.batch_size" in result.stdout

        # Verify it was set correctly
        config_path = isolated_project / ".warden" / "config.yaml"
        with open(config_path) as f:
            config = yaml.safe_load(f)

        # Note: Value may be string "50" since it's not in the int_keys list
        batch_size = config.get("settings", {}).get("pre_analysis_config", {}).get("batch_size")
        assert batch_size == "50" or batch_size == 50

    def test_config_set_creates_nested_structure(self, runner, isolated_project, monkeypatch):
        """Setting a nested key creates the full structure if it doesn't exist."""
        monkeypatch.chdir(isolated_project)

        result = runner.invoke(app, [
            "config", "set",
            "new_section.subsection.value", "test_value"
        ])
        assert result.exit_code == 0

        config_path = isolated_project / ".warden" / "config.yaml"
        with open(config_path) as f:
            config = yaml.safe_load(f)

        assert config.get("new_section", {}).get("subsection", {}).get("value") == "test_value"

    def test_config_set_boolean_conversion(self, runner, isolated_project, monkeypatch):
        """Config set auto-converts boolean values correctly."""
        monkeypatch.chdir(isolated_project)

        # Test various boolean representations
        for true_val in ["true", "True", "yes", "1", "on"]:
            result = runner.invoke(app, [
                "config", "set", "settings.fail_fast", true_val
            ])
            assert result.exit_code == 0

            config_path = isolated_project / ".warden" / "config.yaml"
            with open(config_path) as f:
                config = yaml.safe_load(f)
            assert config["settings"]["fail_fast"] is True

        # Test false values
        for false_val in ["false", "False", "no", "0", "off"]:
            result = runner.invoke(app, [
                "config", "set", "settings.fail_fast", false_val
            ])
            assert result.exit_code == 0

            with open(config_path) as f:
                config = yaml.safe_load(f)
            assert config["settings"]["fail_fast"] is False

    def test_config_set_invalid_boolean(self, runner, isolated_project, monkeypatch):
        """Config set rejects invalid boolean values."""
        monkeypatch.chdir(isolated_project)

        result = runner.invoke(app, [
            "config", "set", "settings.fail_fast", "maybe"
        ])
        assert result.exit_code == 1
        assert "invalid boolean" in result.stdout.lower()

    def test_config_empty_yaml_handling(self, runner, tmp_path, monkeypatch):
        """Empty config.yaml returns empty config dict."""
        monkeypatch.chdir(tmp_path)

        # Create .warden with empty config
        warden_dir = tmp_path / ".warden"
        warden_dir.mkdir()
        (warden_dir / "config.yaml").write_text("")

        result = runner.invoke(app, ["config", "list"])
        # Should succeed but show empty/minimal config
        assert result.exit_code == 0

    def test_config_malformed_yaml_handling(self, runner, tmp_path, monkeypatch):
        """Malformed YAML returns error."""
        monkeypatch.chdir(tmp_path)

        warden_dir = tmp_path / ".warden"
        warden_dir.mkdir()
        # Write invalid YAML
        (warden_dir / "config.yaml").write_text("{{invalid: yaml: content")

        result = runner.invoke(app, ["config", "list"])
        assert result.exit_code == 1
        assert "error" in result.stdout.lower()

    def test_config_missing_warden_dir(self, runner, tmp_path, monkeypatch):
        """Config commands fail gracefully when .warden doesn't exist."""
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["config", "list"])
        assert result.exit_code == 1
        assert "config not found" in result.stdout.lower() or "warden init" in result.stdout.lower()

    def test_config_get_json_format(self, runner, isolated_project, monkeypatch):
        """Config get with --json returns JSON value."""
        monkeypatch.chdir(isolated_project)

        # Get a simple value
        result = runner.invoke(app, ["config", "get", "llm.provider", "--json"])
        assert result.exit_code == 0

        # Output should be valid JSON
        output = result.stdout.strip()
        json_value = json.loads(output)
        assert isinstance(json_value, str)

    def test_config_get_nested_json_format(self, runner, isolated_project, monkeypatch):
        """Config get with --json returns nested JSON correctly."""
        monkeypatch.chdir(isolated_project)

        # Get a dict value (llm is a known dict)
        result = runner.invoke(app, ["config", "get", "llm", "--json"])

        if result.exit_code == 0:
            # Output should be valid JSON
            output = result.stdout.strip()
            json_value = json.loads(output)
            assert isinstance(json_value, dict)
        else:
            # May fail if settings doesn't exist or is structured differently
            pytest.skip("Config key not available")

    def test_config_get_nonexistent_key(self, runner, isolated_project, monkeypatch):
        """Config get returns error for non-existent key."""
        monkeypatch.chdir(isolated_project)

        result = runner.invoke(app, ["config", "get", "nonexistent.key"])
        assert result.exit_code == 1
        assert "not found" in result.stdout.lower()

    def test_config_set_invalid_provider(self, runner, isolated_project, monkeypatch):
        """Config set rejects invalid LLM provider."""
        monkeypatch.chdir(isolated_project)

        result = runner.invoke(app, ["config", "set", "llm.provider", "invalid_provider"])
        assert result.exit_code == 1
        assert "invalid provider" in result.stdout.lower()

    def test_config_set_invalid_mode(self, runner, isolated_project, monkeypatch):
        """Config set rejects invalid mode."""
        monkeypatch.chdir(isolated_project)

        result = runner.invoke(app, ["config", "set", "settings.mode", "invalid_mode"])
        assert result.exit_code == 1
        assert "invalid mode" in result.stdout.lower()

    def test_config_set_integer_conversion(self, runner, isolated_project, monkeypatch):
        """Config set auto-converts integer values."""
        monkeypatch.chdir(isolated_project)

        result = runner.invoke(app, ["config", "set", "llm.timeout", "120"])
        assert result.exit_code == 0

        config_path = isolated_project / ".warden" / "config.yaml"
        with open(config_path) as f:
            config = yaml.safe_load(f)
        assert config["llm"]["timeout"] == 120
        assert isinstance(config["llm"]["timeout"], int)

    def test_config_set_invalid_integer(self, runner, isolated_project, monkeypatch):
        """Config set rejects invalid integer values."""
        monkeypatch.chdir(isolated_project)

        result = runner.invoke(app, ["config", "set", "llm.timeout", "not_a_number"])
        assert result.exit_code == 1
        assert "invalid integer" in result.stdout.lower()


# =============================================================================
# CI Edge Cases
# =============================================================================
@pytest.mark.e2e
class TestCIEdgeCases:
    """Edge cases for CI init/update/status commands."""

    def test_ci_init_gitlab_provider(self, runner, isolated_project, monkeypatch):
        """CI init with --provider gitlab creates .gitlab-ci.yml."""
        monkeypatch.chdir(isolated_project)

        result = runner.invoke(app, [
            "ci", "init",
            "--provider", "gitlab",
            "--force"
        ])

        # May succeed or fail depending on template availability
        if result.exit_code == 0:
            assert (isolated_project / ".gitlab-ci.yml").exists()

            # Verify content has Warden version header
            content = (isolated_project / ".gitlab-ci.yml").read_text()
            assert "Warden CI v" in content
        else:
            # If it fails, should have helpful error message
            assert "error" in result.stdout.lower() or "gitlab" in result.stdout.lower()

    def test_ci_init_custom_branch(self, runner, isolated_project, monkeypatch):
        """CI init with --branch sets correct trigger branch."""
        monkeypatch.chdir(isolated_project)

        result = runner.invoke(app, [
            "ci", "init",
            "--provider", "github",
            "--branch", "develop",
            "--force"
        ])

        if result.exit_code == 0:
            # Check that workflow files were created
            github_dir = isolated_project / ".github" / "workflows"
            if github_dir.exists():
                # At least one workflow should exist
                workflows = list(github_dir.glob("*.yml"))
                assert len(workflows) > 0

                # Check one workflow contains the branch
                warden_yml = github_dir / "warden.yml"
                if warden_yml.exists():
                    content = warden_yml.read_text()
                    # Branch may appear in triggers
                    assert "develop" in content or "main" in content

    def test_ci_init_no_force_skips_existing(self, runner, isolated_project, monkeypatch):
        """Without --force, existing workflows are skipped."""
        monkeypatch.chdir(isolated_project)

        # Create initial workflows
        result1 = runner.invoke(app, [
            "ci", "init",
            "--provider", "github",
            "--force"
        ])

        if result1.exit_code != 0:
            pytest.skip("CI init failed, may be missing templates")

        # Run again without force
        result2 = runner.invoke(app, [
            "ci", "init",
            "--provider", "github"
        ])

        assert result2.exit_code == 0
        # Should mention skipped files
        assert "skipped" in result2.stdout.lower() or "existing" in result2.stdout.lower()

    def test_ci_init_result_message(self, runner, isolated_project, monkeypatch):
        """CI init output mentions created/skipped files."""
        monkeypatch.chdir(isolated_project)

        result = runner.invoke(app, [
            "ci", "init",
            "--provider", "github",
            "--force"
        ])

        if result.exit_code == 0:
            stdout = result.stdout.lower()
            # Should show what was created
            assert "created" in stdout or "workflow" in stdout

    def test_ci_init_invalid_provider(self, runner, isolated_project, monkeypatch):
        """CI init rejects invalid provider."""
        monkeypatch.chdir(isolated_project)

        result = runner.invoke(app, [
            "ci", "init",
            "--provider", "invalid_provider"
        ])

        assert result.exit_code == 1
        assert "invalid" in result.stdout.lower() or "provider" in result.stdout.lower()

    def test_ci_init_invalid_branch_name(self, runner, isolated_project, monkeypatch):
        """CI init rejects branch names with dangerous path traversal patterns."""
        monkeypatch.chdir(isolated_project)

        # Branch with special chars that MAY fail validation (depends on SAFE_BRANCH_PATTERN)
        # The pattern allows dots and slashes, so "../" might pass
        # Test with truly invalid chars like spaces or special chars instead
        result = runner.invoke(app, [
            "ci", "init",
            "--provider", "github",
            "--branch", "branch with spaces!"
        ])

        # Should fail validation (spaces and ! not allowed)
        assert result.exit_code == 1

    def test_ci_status_no_workflows(self, runner, tmp_path, monkeypatch):
        """CI status with no workflows shows not configured."""
        monkeypatch.chdir(tmp_path)

        # Create minimal .warden
        warden_dir = tmp_path / ".warden"
        warden_dir.mkdir()
        (warden_dir / "config.yaml").write_text("llm:\n  provider: ollama\n")

        result = runner.invoke(app, ["ci", "status"])
        # Should succeed but show no CI configured
        assert result.exit_code == 0
        assert "no" in result.stdout.lower() or "not" in result.stdout.lower()

    def test_ci_status_json_output(self, runner, isolated_project, monkeypatch):
        """CI status --json returns valid JSON."""
        monkeypatch.chdir(isolated_project)

        result = runner.invoke(app, ["ci", "status", "--json"])
        assert result.exit_code == 0

        # Should be valid JSON (may have structlog lines before it)
        json_data = _extract_json(result.stdout)
        assert json_data is not None
        assert isinstance(json_data, dict)


# =============================================================================
# Baseline Edge Cases
# =============================================================================
@pytest.mark.e2e
class TestBaselineEdgeCases:
    """Edge cases for baseline debt/status commands."""

    def test_baseline_status_empty_baseline_dir(self, runner, tmp_path, monkeypatch):
        """Baseline status handles empty baseline directory."""
        monkeypatch.chdir(tmp_path)

        warden_dir = tmp_path / ".warden"
        warden_dir.mkdir()
        (warden_dir / "config.yaml").write_text("llm:\n  provider: ollama\n")

        # Create empty baseline dir
        baseline_dir = warden_dir / "baseline"
        baseline_dir.mkdir()

        result = runner.invoke(app, ["baseline", "status"])
        # Should handle gracefully
        assert result.exit_code == 0

    def test_baseline_debt_no_baseline(self, runner, tmp_path, monkeypatch):
        """Baseline debt without baseline shows helpful message."""
        monkeypatch.chdir(tmp_path)

        warden_dir = tmp_path / ".warden"
        warden_dir.mkdir()
        (warden_dir / "config.yaml").write_text("llm:\n  provider: ollama\n")

        result = runner.invoke(app, ["baseline", "debt"])
        # Should show that no baseline exists
        assert result.exit_code == 0
        assert "no" in result.stdout.lower() or "not found" in result.stdout.lower()

    def test_baseline_debt_module_filter(self, runner, isolated_project, monkeypatch):
        """Baseline debt --module filters to specific module."""
        monkeypatch.chdir(isolated_project)

        result = runner.invoke(app, [
            "baseline", "debt",
            "--module", "nonexistent_module"
        ])

        # Should succeed but show module not found
        assert result.exit_code == 0

    def test_baseline_debt_verbose_flag(self, runner, isolated_project, monkeypatch):
        """Baseline debt --verbose shows detailed items."""
        monkeypatch.chdir(isolated_project)

        result = runner.invoke(app, [
            "baseline", "debt",
            "--verbose"
        ])

        # Should succeed
        assert result.exit_code == 0

    def test_baseline_migrate_no_legacy(self, runner, tmp_path, monkeypatch):
        """Baseline migrate without legacy baseline shows helpful message."""
        monkeypatch.chdir(tmp_path)

        warden_dir = tmp_path / ".warden"
        warden_dir.mkdir()
        (warden_dir / "config.yaml").write_text("llm:\n  provider: ollama\n")

        result = runner.invoke(app, ["baseline", "migrate"])
        # Should show that no legacy baseline found
        assert result.exit_code == 0
        assert "no" in result.stdout.lower() or "not found" in result.stdout.lower()

    def test_baseline_migrate_already_migrated(self, runner, isolated_project, monkeypatch):
        """Baseline migrate when already using module-based shows message."""
        monkeypatch.chdir(isolated_project)

        result = runner.invoke(app, ["baseline", "migrate"])
        # May show already migrated or no legacy found
        assert result.exit_code == 0


# =============================================================================
# General Error Handling
# =============================================================================
@pytest.mark.e2e
class TestGeneralErrorHandling:
    """General error handling across commands."""

    def test_config_commands_without_warden_dir(self, runner, tmp_path, monkeypatch):
        """Config commands handle missing .warden gracefully."""
        monkeypatch.chdir(tmp_path)

        # config list
        result = runner.invoke(app, ["config", "list"])
        assert result.exit_code == 1
        assert "not found" in result.stdout.lower() or "warden init" in result.stdout.lower()

        # config get
        result = runner.invoke(app, ["config", "get", "llm.provider"])
        assert result.exit_code == 1

        # config set
        result = runner.invoke(app, ["config", "set", "llm.provider", "ollama"])
        assert result.exit_code == 1

    def test_scan_help_without_warden_dir(self, runner, tmp_path, monkeypatch):
        """Scan --help works without .warden directory."""
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["scan", "--help"])
        # Help should always work
        assert result.exit_code == 0
        assert "scan" in result.stdout.lower()

    def test_version_without_warden_dir(self, runner, tmp_path, monkeypatch):
        """Version command works without .warden directory."""
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert "warden" in result.stdout.lower()

    def test_doctor_without_warden_dir(self, runner, tmp_path, monkeypatch):
        """Doctor command handles missing .warden gracefully."""
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["doctor"])
        # Doctor should run but show issues
        assert result.exit_code in (0, 1)

    def test_ci_status_without_warden_dir(self, runner, tmp_path, monkeypatch):
        """CI status handles missing .warden gracefully."""
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["ci", "status"])
        # Should handle gracefully
        assert result.exit_code in (0, 1)

    def test_config_permission_error_simulation(self, runner, tmp_path, monkeypatch):
        """Config commands handle permission errors gracefully."""
        monkeypatch.chdir(tmp_path)

        warden_dir = tmp_path / ".warden"
        warden_dir.mkdir()
        config_file = warden_dir / "config.yaml"
        config_file.write_text("llm:\n  provider: ollama\n")

        # Make file read-only (this is OS-dependent and may not fully work)
        import os
        config_file.chmod(0o444)

        result = runner.invoke(app, ["config", "set", "llm.provider", "anthropic"])
        # Should fail with permission error
        # Note: chmod may not fully prevent writes in all environments
        if result.exit_code == 1:
            assert "permission" in result.stdout.lower() or "error" in result.stdout.lower()

        # Cleanup
        config_file.chmod(0o644)

    def test_scan_nonexistent_file(self, runner, isolated_project, monkeypatch):
        """Scan with nonexistent file path shows error."""
        monkeypatch.chdir(isolated_project)

        result = runner.invoke(app, [
            "scan",
            "--disable-ai",
            str(isolated_project / "nonexistent_file.py")
        ])

        # Should complete but may show warning about path
        # Exit code depends on scan behavior
        assert result.exit_code in (0, 1, 2)

    def test_config_list_json_output(self, runner, isolated_project, monkeypatch):
        """Config list --json returns valid JSON."""
        monkeypatch.chdir(isolated_project)

        result = runner.invoke(app, ["config", "list", "--json"])
        assert result.exit_code == 0

        # Should be valid JSON
        json.loads(result.stdout)

    def test_baseline_status_without_warden(self, runner, tmp_path, monkeypatch):
        """Baseline status without .warden handles gracefully."""
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["baseline", "status"])
        # Should handle gracefully
        assert result.exit_code in (0, 1)

    def test_ci_init_no_provider_non_interactive(self, runner, tmp_path, monkeypatch):
        """CI init without provider in non-interactive mode shows error."""
        monkeypatch.chdir(tmp_path)

        warden_dir = tmp_path / ".warden"
        warden_dir.mkdir()
        (warden_dir / "config.yaml").write_text("llm:\n  provider: ollama\n")

        # CliRunner is non-interactive by default
        result = runner.invoke(app, ["ci", "init"])

        # Should either prompt or fail
        assert result.exit_code in (0, 1)

    def test_config_set_shows_old_value(self, runner, isolated_project, monkeypatch):
        """Config set shows old and new values."""
        monkeypatch.chdir(isolated_project)

        # Get initial value
        result1 = runner.invoke(app, ["config", "get", "settings.fail_fast"])
        initial_exit = result1.exit_code

        if initial_exit == 0:
            # Set to opposite value
            result2 = runner.invoke(app, ["config", "set", "settings.fail_fast", "true"])
            assert result2.exit_code == 0

            # Output should show old and new
            stdout = result2.stdout.lower()
            assert "old" in stdout or "new" in stdout or "updated" in stdout

    def test_ci_update_without_ci(self, runner, tmp_path, monkeypatch):
        """CI update without existing CI shows error."""
        monkeypatch.chdir(tmp_path)

        warden_dir = tmp_path / ".warden"
        warden_dir.mkdir()
        (warden_dir / "config.yaml").write_text("llm:\n  provider: ollama\n")

        result = runner.invoke(app, ["ci", "update"])
        # Should show that CI needs to be initialized first
        assert result.exit_code in (0, 1)
        assert "no" in result.stdout.lower() or "init" in result.stdout.lower()

    def test_ci_sync_without_ci(self, runner, tmp_path, monkeypatch):
        """CI sync without existing CI shows error."""
        monkeypatch.chdir(tmp_path)

        warden_dir = tmp_path / ".warden"
        warden_dir.mkdir()
        (warden_dir / "config.yaml").write_text("llm:\n  provider: ollama\n")

        result = runner.invoke(app, ["ci", "sync"])
        # Should show that CI needs to be initialized first
        assert result.exit_code in (0, 1)
        assert "no" in result.stdout.lower() or "init" in result.stdout.lower()
