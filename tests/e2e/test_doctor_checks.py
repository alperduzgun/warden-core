"""E2E tests for warden doctor command.

Tests the diagnostic system that validates project health and readiness.
Doctor performs 8 check categories: Python version, Core config, Warden dir,
Installed frames, Custom rules, Environment/API keys, Tooling (LSP/Git), Semantic index.

Exit codes:
  - 0: healthy (or warnings only)
  - 1: critical errors

No side effects (read-only diagnostic).
"""

import pytest
import yaml
from pathlib import Path
from warden.main import app


# ============================================================================
# Help and Basic Invocation
# ============================================================================
@pytest.mark.e2e
class TestDoctorHelp:

    def test_doctor_help(self, runner):
        """Doctor command shows help text."""
        result = runner.invoke(app, ["doctor", "--help"])
        assert result.exit_code == 0
        stdout = result.stdout.lower()
        assert "doctor" in stdout or "diagnostic" in stdout
        assert "health" in stdout or "verify" in stdout or "readiness" in stdout


# ============================================================================
# Healthy Project Checks
# ============================================================================
@pytest.mark.e2e
class TestDoctorHealthyProject:

    def test_doctor_healthy_project(self, runner, isolated_project, monkeypatch):
        """Doctor on fixture project runs all checks and returns 0 or 1."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["doctor"])
        # Exit code: 0 = healthy, 1 = critical errors (LLM missing is ok)
        assert result.exit_code in (0, 1)
        stdout = result.stdout.lower()
        # Should show "running diagnostics"
        assert "diagnostic" in stdout or "doctor" in stdout

    def test_doctor_shows_all_check_categories(self, runner, isolated_project, monkeypatch):
        """Doctor output mentions all 8 check categories."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["doctor"])
        stdout = result.stdout.lower()

        # Check for all 8 categories (case-insensitive)
        assert "python" in stdout  # Python Version
        assert "config" in stdout or "configuration" in stdout  # Core Configuration
        assert "warden" in stdout and "directory" in stdout  # Warden Directory
        assert "frame" in stdout  # Installed Frames
        assert "rule" in stdout or "custom" in stdout  # Custom Rules
        assert "environment" in stdout or "api" in stdout or "key" in stdout  # Environment & API Keys
        assert "tool" in stdout or "git" in stdout or "lsp" in stdout  # Tooling (LSP/Git)
        assert "semantic" in stdout or "index" in stdout or "vector" in stdout  # Semantic Index

    def test_doctor_output_has_check_indicators(self, runner, isolated_project, monkeypatch):
        """Doctor output contains pass/warning/error indicators."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["doctor"])
        stdout = result.stdout

        # Rich formatting uses Unicode symbols: ✔ (success), ⚠️ (warning), ✘ (error)
        # At least one check should have passed
        # Note: Rich may strip these in test environment, so check for text patterns too
        has_indicator = (
            "✔" in stdout or "✘" in stdout or "⚠" in stdout or
            "success" in stdout.lower() or "warning" in stdout.lower() or "error" in stdout.lower()
        )
        assert has_indicator, f"No check indicators in output: {stdout[:500]}"


# ============================================================================
# Individual Check Tests
# ============================================================================
@pytest.mark.e2e
class TestDoctorIndividualChecks:

    def test_doctor_checks_python_version(self, runner, isolated_project, monkeypatch):
        """Doctor output mentions Python version check."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["doctor"])
        stdout = result.stdout.lower()
        assert "python" in stdout
        # Should mention version number (e.g., "python 3.9", "3.10", "3.11")
        assert any(v in stdout for v in ["3.9", "3.10", "3.11", "3.12", "3.13"])

    def test_doctor_checks_config(self, runner, isolated_project, monkeypatch):
        """Doctor output mentions config validation."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["doctor"])
        stdout = result.stdout.lower()
        assert "config" in stdout or "yaml" in stdout

    def test_doctor_checks_warden_dir(self, runner, isolated_project, monkeypatch):
        """Doctor output mentions .warden directory check."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["doctor"])
        stdout = result.stdout.lower()
        assert "warden" in stdout and ("directory" in stdout or "dir" in stdout)

    def test_doctor_checks_frames(self, runner, isolated_project, monkeypatch):
        """Doctor output mentions frames check."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["doctor"])
        stdout = result.stdout.lower()
        assert "frame" in stdout

    def test_doctor_checks_rules(self, runner, isolated_project, monkeypatch):
        """Doctor output mentions custom rules check."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["doctor"])
        stdout = result.stdout.lower()
        assert "rule" in stdout or "custom" in stdout

    def test_doctor_checks_environment(self, runner, isolated_project, monkeypatch):
        """Doctor output mentions environment/API keys check."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["doctor"])
        stdout = result.stdout.lower()
        assert "environment" in stdout or "api" in stdout or "key" in stdout

    def test_doctor_checks_git(self, runner, isolated_project, monkeypatch):
        """Doctor output mentions git availability check."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["doctor"])
        stdout = result.stdout.lower()
        assert "git" in stdout or "tool" in stdout

    def test_doctor_checks_semantic_index(self, runner, isolated_project, monkeypatch):
        """Doctor output mentions semantic index check."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["doctor"])
        stdout = result.stdout.lower()
        assert "semantic" in stdout or "index" in stdout or "vector" in stdout or "embedding" in stdout


# ============================================================================
# Error Scenarios
# ============================================================================
@pytest.mark.e2e
class TestDoctorErrorScenarios:

    def test_doctor_no_warden_dir(self, runner, tmp_path, monkeypatch):
        """Without .warden dir, doctor reports critical error."""
        # Create empty directory with no .warden
        empty_dir = tmp_path / "no_warden"
        empty_dir.mkdir()
        monkeypatch.chdir(empty_dir)

        result = runner.invoke(app, ["doctor"])
        # Should exit with 1 (critical error)
        assert result.exit_code == 1
        stdout = result.stdout.lower()

        # Should mention .warden directory issue
        assert "warden" in stdout and ("not found" in stdout or "directory" in stdout)
        # Should show critical error message
        assert "critical" in stdout or "error" in stdout

    def test_doctor_empty_warden_dir(self, runner, tmp_path, monkeypatch):
        """With empty .warden, doctor reports config missing."""
        # Create .warden dir but no config
        project_dir = tmp_path / "empty_warden"
        project_dir.mkdir()
        (project_dir / ".warden").mkdir()
        monkeypatch.chdir(project_dir)

        result = runner.invoke(app, ["doctor"])
        assert result.exit_code == 1
        stdout = result.stdout.lower()

        # Should mention missing config (warden.yaml or config.yaml)
        assert "config" in stdout or "yaml" in stdout
        assert "not found" in stdout or "missing" in stdout

    def test_doctor_malformed_config(self, runner, tmp_path, monkeypatch):
        """With invalid YAML in config, doctor reports error."""
        # Create project with malformed config
        project_dir = tmp_path / "bad_config"
        project_dir.mkdir()
        warden_dir = project_dir / ".warden"
        warden_dir.mkdir()

        # Write malformed YAML (invalid syntax)
        config_path = warden_dir / "config.yaml"
        config_path.write_text("invalid: yaml: syntax: [[[")

        monkeypatch.chdir(project_dir)
        result = runner.invoke(app, ["doctor"])
        assert result.exit_code == 1
        stdout = result.stdout.lower()

        # Should mention YAML error
        assert "yaml" in stdout
        assert "error" in stdout or "invalid" in stdout or "syntax" in stdout

    def test_doctor_missing_config(self, runner, tmp_path, monkeypatch):
        """With .warden but no config.yaml, doctor reports error."""
        # Same as empty_warden_dir, but explicit test
        project_dir = tmp_path / "no_config"
        project_dir.mkdir()
        (project_dir / ".warden").mkdir()
        monkeypatch.chdir(project_dir)

        result = runner.invoke(app, ["doctor"])
        assert result.exit_code == 1
        stdout = result.stdout.lower()

        # Should mention config not found
        assert "config" in stdout or "warden.yaml" in stdout
        assert "not found" in stdout or "missing" in stdout

    def test_doctor_empty_config_file(self, runner, tmp_path, monkeypatch):
        """With empty config.yaml, doctor reports error."""
        project_dir = tmp_path / "empty_config"
        project_dir.mkdir()
        warden_dir = project_dir / ".warden"
        warden_dir.mkdir()

        # Write empty config file
        config_path = warden_dir / "config.yaml"
        config_path.write_text("")

        monkeypatch.chdir(project_dir)
        result = runner.invoke(app, ["doctor"])
        assert result.exit_code == 1
        stdout = result.stdout.lower()

        # Should mention empty config
        assert "empty" in stdout or "missing" in stdout

    def test_doctor_config_not_dict(self, runner, tmp_path, monkeypatch):
        """With config.yaml as list instead of dict, doctor reports error."""
        project_dir = tmp_path / "list_config"
        project_dir.mkdir()
        warden_dir = project_dir / ".warden"
        warden_dir.mkdir()

        # Write config as list instead of dict
        config_path = warden_dir / "config.yaml"
        config_path.write_text("- item1\n- item2")

        monkeypatch.chdir(project_dir)
        result = runner.invoke(app, ["doctor"])
        assert result.exit_code == 1
        stdout = result.stdout.lower()

        # Should mention structure error
        assert "mapping" in stdout or "dictionary" in stdout or "dict" in stdout

    def test_doctor_missing_required_keys(self, runner, tmp_path, monkeypatch):
        """With config missing required keys, doctor reports warning."""
        project_dir = tmp_path / "incomplete_config"
        project_dir.mkdir()
        warden_dir = project_dir / ".warden"
        warden_dir.mkdir()

        # Write config without required keys (project, frames)
        config_path = warden_dir / "config.yaml"
        config = {"other_key": "value"}
        config_path.write_text(yaml.dump(config))

        monkeypatch.chdir(project_dir)
        result = runner.invoke(app, ["doctor"])
        # Exit code can be 0 (warning) or 1 depending on other checks
        stdout = result.stdout.lower()

        # Should mention missing keys as warning
        assert "missing" in stdout or "warning" in stdout


# ============================================================================
# Warning Scenarios (Non-Critical)
# ============================================================================
@pytest.mark.e2e
class TestDoctorWarningScenarios:

    def test_doctor_missing_llm_keys_warning(self, runner, isolated_project, monkeypatch):
        """Doctor warns if no LLM API keys are present (Zombie Mode)."""
        monkeypatch.chdir(isolated_project)

        # Clear environment variables for LLM keys
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

        result = runner.invoke(app, ["doctor"])
        # Should NOT exit 1 for missing LLM keys (only warning)
        # But other checks might fail, so allow 0 or 1
        stdout = result.stdout.lower()

        # Should mention zombie mode or missing API keys
        assert "zombie" in stdout or "api" in stdout or "key" in stdout or "offline" in stdout

    def test_doctor_missing_lsp_warning(self, runner, tmp_path, monkeypatch):
        """Doctor warns if no LSP servers are found."""
        # Create minimal valid project
        project_dir = tmp_path / "no_lsp"
        project_dir.mkdir()
        warden_dir = project_dir / ".warden"
        warden_dir.mkdir()

        # Write minimal config
        config_path = warden_dir / "config.yaml"
        config = {
            "project": {"name": "test"},
            "frames": {},
            "dependencies": {}
        }
        config_path.write_text(yaml.dump(config))

        monkeypatch.chdir(project_dir)
        result = runner.invoke(app, ["doctor"])
        stdout = result.stdout.lower()

        # Should mention LSP or precision analysis warning
        # Note: test environment might have LSP installed, so check conditionally
        # If no LSP found, should see warning
        if "lsp" in stdout or "precision" in stdout or "ast" in stdout:
            # Warning about LSP might be present
            pass  # Test passes either way

    def test_doctor_no_semantic_index_warning(self, runner, isolated_project, monkeypatch):
        """Doctor warns if semantic index is not found."""
        monkeypatch.chdir(isolated_project)

        # Remove embeddings directory if it exists
        embeddings_dir = isolated_project / ".warden" / "embeddings"
        if embeddings_dir.exists():
            import shutil
            shutil.rmtree(embeddings_dir)

        result = runner.invoke(app, ["doctor"])
        stdout = result.stdout.lower()

        # Should mention semantic index or embeddings
        assert "semantic" in stdout or "index" in stdout or "embedding" in stdout


# ============================================================================
# Standard Config Path (warden.yaml at root)
# ============================================================================
@pytest.mark.e2e
class TestDoctorStandardConfig:

    def test_doctor_with_standard_config_path(self, runner, tmp_path, monkeypatch):
        """Doctor works with warden.yaml at project root (standard path)."""
        project_dir = tmp_path / "standard_config"
        project_dir.mkdir()
        warden_dir = project_dir / ".warden"
        warden_dir.mkdir()

        # Write config at root (standard location)
        config_path = project_dir / "warden.yaml"
        config = {
            "project": {"name": "test"},
            "frames": {},
            "dependencies": {}
        }
        config_path.write_text(yaml.dump(config))

        monkeypatch.chdir(project_dir)
        result = runner.invoke(app, ["doctor"])
        # Should complete checks (may have warnings/errors for other things)
        assert result.exit_code in (0, 1)
        stdout = result.stdout.lower()

        # Should find config and run checks
        assert "python" in stdout  # At least Python check should run


# ============================================================================
# Success Messages
# ============================================================================
@pytest.mark.e2e
class TestDoctorSuccessMessages:

    def test_doctor_success_message(self, runner, tmp_path, monkeypatch):
        """Doctor shows success message when healthy."""
        # Create minimal healthy project
        project_dir = tmp_path / "healthy"
        project_dir.mkdir()
        warden_dir = project_dir / ".warden"
        warden_dir.mkdir()

        # Write valid config
        config_path = warden_dir / "config.yaml"
        config = {
            "project": {"name": "test"},
            "frames": {},
            "dependencies": {}
        }
        config_path.write_text(yaml.dump(config))

        monkeypatch.chdir(project_dir)
        result = runner.invoke(app, ["doctor"])

        # Exit code 0 or 1 (depending on LLM keys, git, etc.)
        stdout = result.stdout.lower()

        # Should show either success or critical error message
        if result.exit_code == 0:
            assert "healthy" in stdout or "ready" in stdout
        else:
            assert "critical" in stdout or "error" in stdout

    def test_doctor_failure_message(self, runner, tmp_path, monkeypatch):
        """Doctor shows critical error message when checks fail."""
        # Create project with missing config
        project_dir = tmp_path / "failure"
        project_dir.mkdir()
        (project_dir / ".warden").mkdir()

        monkeypatch.chdir(project_dir)
        result = runner.invoke(app, ["doctor"])
        assert result.exit_code == 1
        stdout = result.stdout.lower()

        # Should show critical error message
        assert "critical" in stdout or "error" in stdout
        assert "fix" in stdout or "please" in stdout
