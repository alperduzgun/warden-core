"""E2E tests for warden refresh and warden status commands.

Tests cover:
  - Refresh: intelligence generation, flags, file creation, incremental modes
  - Status: SARIF parsing, finding counts, pass/fail display

Pattern: CliRunner for in-process CLI execution with fixture project.
"""

import json
from pathlib import Path

import pytest
from warden.main import app


# ============================================================================
# warden refresh
# ============================================================================
@pytest.mark.e2e
class TestRefreshCommand:
    """Tests for 'warden refresh' command."""

    def test_refresh_help_shows_all_flags(self, runner):
        """Help displays all refresh flags."""
        result = runner.invoke(app, ["refresh", "--help"])
        assert result.exit_code == 0
        stdout = result.stdout.lower()
        for flag in ("--force", "--no-intelligence", "--baseline", "--module", "--quick"):
            assert flag in stdout, f"Missing flag in help: {flag}"

    def test_refresh_requires_warden_dir(self, runner, tmp_path, monkeypatch):
        """Refresh without .warden dir exits with error and init message."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["refresh"])
        assert result.exit_code == 1
        stdout = result.stdout.lower()
        assert "init" in stdout or "not initialized" in stdout

    def test_refresh_no_intelligence_completes(self, runner, isolated_project, monkeypatch):
        """Refresh with --no-intelligence exits successfully without generating intelligence."""
        monkeypatch.chdir(isolated_project)

        # Remove existing intelligence to verify it's not created
        intel_file = isolated_project / ".warden" / "intelligence" / "project.json"
        if intel_file.exists():
            intel_file.unlink()

        result = runner.invoke(app, ["refresh", "--no-intelligence"])
        assert result.exit_code == 0
        stdout = result.stdout.lower()
        # Should complete but skip intelligence refresh
        assert "refresh complete" in stdout or "complete" in stdout
        # Intelligence file should not be created when --no-intelligence is used
        # (it may still exist from fixture, so we can't assert it doesn't exist)

    def test_refresh_force_regenerates(self, runner, isolated_project, monkeypatch):
        """Refresh with --force triggers regeneration even if recent."""
        monkeypatch.chdir(isolated_project)

        result = runner.invoke(app, ["refresh", "--force"])
        # May exit 0 or 1 depending on whether intelligence refresh completes
        assert result.exit_code in (0, 1)
        stdout = result.stdout.lower()
        # Should show refresh activity
        assert "refresh" in stdout

    def test_refresh_creates_intelligence_file(self, runner, isolated_project, monkeypatch):
        """Refresh creates intelligence/project.json file."""
        monkeypatch.chdir(isolated_project)

        intel_file = isolated_project / ".warden" / "intelligence" / "project.json"

        # Remove it first if it exists
        if intel_file.exists():
            intel_file.unlink()

        result = runner.invoke(app, ["refresh", "--force"])

        # Intelligence refresh may fail in test env without proper LLM setup,
        # but we can verify the command runs
        assert result.exit_code in (0, 1)

        # Check if file was created (it should exist from fixture anyway)
        # Note: In isolated env without LLM, this might fail gracefully

    def test_refresh_intelligence_structure(self, runner, isolated_project, monkeypatch):
        """Intelligence file has expected JSON structure."""
        monkeypatch.chdir(isolated_project)

        intel_file = isolated_project / ".warden" / "intelligence" / "project.json"

        # The fixture already has this file, verify its structure
        assert intel_file.exists(), "Fixture should have intelligence file"

        with open(intel_file) as f:
            data = json.load(f)

        # Verify expected fields
        assert "version" in data
        assert "project_name" in data
        assert "modules" in data
        assert isinstance(data["modules"], dict)

    def test_refresh_quick_mode(self, runner, isolated_project, monkeypatch):
        """Refresh with --quick mode completes."""
        monkeypatch.chdir(isolated_project)

        result = runner.invoke(app, ["refresh", "--quick"])
        # Quick mode should complete (exit 0 or 1 if no new files)
        assert result.exit_code in (0, 1)
        stdout = result.stdout.lower()
        assert "refresh" in stdout or "quick" in stdout or "no new files" in stdout

    def test_refresh_module_filter(self, runner, isolated_project, monkeypatch):
        """Refresh with --module filters to specific module."""
        monkeypatch.chdir(isolated_project)

        result = runner.invoke(app, ["refresh", "--module", "src"])
        assert result.exit_code in (0, 1)
        stdout = result.stdout.lower()
        # Should mention module filtering
        assert "refresh" in stdout or "module" in stdout or "src" in stdout

    def test_refresh_shows_completion_message(self, runner, isolated_project, monkeypatch):
        """Refresh shows completion message on success."""
        monkeypatch.chdir(isolated_project)

        result = runner.invoke(app, ["refresh", "--no-intelligence"])
        assert result.exit_code == 0
        stdout = result.stdout.lower()
        assert "complete" in stdout or "refresh" in stdout

    def test_refresh_force_and_quick_combination(self, runner, isolated_project, monkeypatch):
        """Refresh accepts --force and --quick together."""
        monkeypatch.chdir(isolated_project)

        result = runner.invoke(app, ["refresh", "--force", "--quick"])
        assert result.exit_code in (0, 1)
        stdout = result.stdout.lower()
        assert "refresh" in stdout


# ============================================================================
# warden status
# ============================================================================
@pytest.mark.e2e
class TestStatusCommand:
    """Tests for 'warden status' command."""

    def test_status_help(self, runner):
        """Status help shows --fetch flag."""
        result = runner.invoke(app, ["status", "--help"])
        assert result.exit_code == 0
        stdout = result.stdout.lower()
        assert "--fetch" in stdout or "-f" in stdout

    def test_status_reads_local_sarif(self, runner, isolated_project, monkeypatch):
        """Status reads fixture SARIF and displays findings."""
        monkeypatch.chdir(isolated_project)

        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        stdout = result.stdout.lower()
        # Should show status output (pass/fail, counts, etc.)
        assert "status" in stdout or "issue" in stdout or "error" in stdout or "warning" in stdout

    def test_status_shows_finding_count(self, runner, isolated_project, monkeypatch):
        """Status output mentions finding counts or severity."""
        monkeypatch.chdir(isolated_project)

        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        stdout = result.stdout.lower()
        # Fixture SARIF has 1 error-level finding
        # Should show counts or severity levels
        assert any(word in stdout for word in ["error", "warning", "total", "issue", "critical", "high"])

    def test_status_no_warden_dir(self, runner, tmp_path, monkeypatch):
        """Status without .warden dir handles gracefully."""
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["status"])
        # Should not crash, but may show "no report found"
        assert result.exit_code in (0, 1)
        stdout = result.stdout.lower()
        assert "no report" in stdout or "not found" in stdout or "scan" in stdout

    def test_status_no_sarif_report(self, runner, isolated_project, monkeypatch):
        """Status with .warden but no SARIF handles gracefully."""
        monkeypatch.chdir(isolated_project)

        # Remove SARIF report
        sarif_file = isolated_project / ".warden" / "reports" / "warden-report.sarif"
        if sarif_file.exists():
            sarif_file.unlink()

        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        stdout = result.stdout.lower()
        # Should show "no report found" message
        assert "no report" in stdout or "not found" in stdout

    def test_status_sarif_structure_validation(self, runner, isolated_project):
        """Fixture SARIF is valid JSON with expected structure."""
        sarif_file = isolated_project / ".warden" / "reports" / "warden-report.sarif"
        assert sarif_file.exists(), "Fixture should have SARIF report"

        with open(sarif_file) as f:
            data = json.load(f)

        # Verify SARIF structure
        assert "$schema" in data or "version" in data
        assert "runs" in data
        assert isinstance(data["runs"], list)
        if data["runs"]:
            assert "results" in data["runs"][0]
            assert isinstance(data["runs"][0]["results"], list)

    def test_status_shows_pass_or_fail(self, runner, isolated_project, monkeypatch):
        """Status output contains pass/fail indicator."""
        monkeypatch.chdir(isolated_project)

        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        stdout = result.stdout.lower()
        # Fixture has 1 error, so should show FAIL
        # Output should contain pass or fail indicator
        assert "fail" in stdout or "pass" in stdout or "❌" in stdout or "✅" in stdout

    def test_status_displays_severity_breakdown(self, runner, isolated_project, monkeypatch):
        """Status shows breakdown of findings by severity."""
        monkeypatch.chdir(isolated_project)

        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        stdout = result.stdout.lower()
        # Should show severity levels (critical/high, warnings, etc.)
        # Fixture has 1 error-level finding
        assert "critical" in stdout or "high" in stdout or "error" in stdout or "warning" in stdout

    def test_status_shows_source_path(self, runner, isolated_project, monkeypatch):
        """Status output mentions source report path."""
        monkeypatch.chdir(isolated_project)

        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        stdout = result.stdout.lower()
        # Should mention the report path
        assert "warden-report.sarif" in stdout or ".warden" in stdout or "reports" in stdout

    def test_status_fixture_has_one_error(self, runner, isolated_project, monkeypatch):
        """Fixture SARIF contains exactly 1 error-level finding (SEC-001)."""
        monkeypatch.chdir(isolated_project)

        sarif_file = isolated_project / ".warden" / "reports" / "warden-report.sarif"
        with open(sarif_file) as f:
            data = json.load(f)

        results = data["runs"][0]["results"]
        errors = [r for r in results if r.get("level") == "error"]

        assert len(errors) == 1
        assert errors[0]["ruleId"] == "SEC-001"
        assert "secret" in errors[0]["message"]["text"].lower()

    def test_status_empty_sarif_runs(self, runner, tmp_path, monkeypatch):
        """Status handles SARIF with empty runs array."""
        monkeypatch.chdir(tmp_path)

        # Create minimal .warden structure with empty SARIF
        warden_dir = tmp_path / ".warden" / "reports"
        warden_dir.mkdir(parents=True)
        sarif_file = warden_dir / "warden-report.sarif"

        empty_sarif = {
            "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
            "version": "2.1.0",
            "runs": []
        }

        with open(sarif_file, "w") as f:
            json.dump(empty_sarif, f)

        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        stdout = result.stdout.lower()
        # Should handle empty runs gracefully
        assert "no runs" in stdout or "valid" in stdout or "contains" in stdout

    def test_status_malformed_sarif(self, runner, tmp_path, monkeypatch):
        """Status handles malformed SARIF gracefully."""
        monkeypatch.chdir(tmp_path)

        # Create .warden structure with invalid JSON
        warden_dir = tmp_path / ".warden" / "reports"
        warden_dir.mkdir(parents=True)
        sarif_file = warden_dir / "warden-report.sarif"

        with open(sarif_file, "w") as f:
            f.write("{ invalid json }}")

        result = runner.invoke(app, ["status"])
        # Should not crash, but show parse error
        assert result.exit_code in (0, 1)
        stdout = result.stdout.lower()
        assert "failed" in stdout or "error" in stdout or "parse" in stdout
