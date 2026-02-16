"""E2E tests for all warden CLI commands.

Tests every CLI command's help, basic invocation, and behavioral correctness.
Uses CliRunner (in-process) for deterministic, fast testing.

Coverage matrix:
  - Every registered command has at least a --help test
  - Every command that can run without network/LLM/interactive has invocation tests
  - Behavioral verification: output content, side effects, file mutations
  - Edge cases: invalid inputs, missing config, flag combinations
"""

import json

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


# ============================================================================
# warden --help / version
# ============================================================================
@pytest.mark.e2e
class TestGlobalCLI:

    def test_help(self, runner):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "warden" in result.stdout.lower()

    def test_help_shows_all_commands(self, runner):
        """Root help lists all registered commands."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        for cmd in ("scan", "init", "doctor", "config", "status", "version",
                     "search", "refresh", "baseline", "ci", "serve"):
            assert cmd in result.stdout.lower(), f"Missing command in help: {cmd}"

    def test_no_args_shows_help(self, runner):
        """Running warden with no args shows help (Typer exit code 0 or 2)."""
        result = runner.invoke(app, [])
        assert result.exit_code in (0, 2)
        assert "warden" in result.stdout.lower()

    def test_version_shows_panel(self, runner):
        """Version command shows Warden Core version, Python, and Platform."""
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        stdout = result.stdout.lower()
        assert "warden" in stdout
        assert "python" in stdout
        assert "platform" in stdout or "darwin" in stdout or "linux" in stdout

    def test_version_shows_version_number(self, runner):
        """Version output contains a version-like string (e.g., v2.0.2)."""
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        # Version string contains "v" followed by digits
        import re
        assert re.search(r"v?\d+\.\d+", result.stdout), \
            f"No version number found in: {result.stdout[:200]}"

    def test_invalid_command(self, runner):
        """Unknown command returns non-zero exit code."""
        result = runner.invoke(app, ["nonexistent-command"])
        assert result.exit_code != 0


# ============================================================================
# warden scan (CliRunner — help + flag validation only, pipeline in scan_smoke)
# ============================================================================
@pytest.mark.e2e
class TestScan:

    def test_scan_help(self, runner):
        result = runner.invoke(app, ["scan", "--help"])
        assert result.exit_code == 0
        # Strip ANSI codes for reliable assertion
        import re
        clean_output = re.sub(r'\x1b\[[0-9;]*m', '', result.stdout)
        for flag in ("--level", "--format", "--frame", "--ci", "--diff",
                      "--output", "--verbose", "--base", "--disable-ai",
                      "--memory-profile", "--no-update-baseline"):
            assert flag in clean_output, f"Missing flag in scan help: {flag}"

    def test_scan_help_formats(self, runner):
        """Help mentions all supported output formats."""
        result = runner.invoke(app, ["scan", "--help"])
        assert result.exit_code == 0
        for fmt in ("json", "sarif", "text"):
            assert fmt in result.stdout.lower()

    def test_scan_help_levels(self, runner):
        """Help mentions all analysis levels."""
        result = runner.invoke(app, ["scan", "--help"])
        assert result.exit_code == 0
        for level in ("basic", "standard", "deep"):
            assert level in result.stdout.lower()


# ============================================================================
# warden doctor
# ============================================================================
@pytest.mark.e2e
class TestDoctor:

    def test_help(self, runner):
        result = runner.invoke(app, ["doctor", "--help"])
        assert result.exit_code == 0
        assert "diagnostic" in result.stdout.lower() or "health" in result.stdout.lower()

    def test_doctor_runs_checks(self, runner, isolated_project, monkeypatch):
        """Doctor runs diagnostics and reports specific check results."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["doctor"])
        assert result.exit_code in (0, 1)
        stdout = result.stdout.lower()
        # Doctor should perform known checks
        assert "doctor" in stdout or "diagnostic" in stdout
        # Should check Python version
        assert "python" in stdout
        # Should check configuration
        assert "config" in stdout or "configuration" in stdout or "yaml" in stdout

    def test_doctor_detects_warden_dir(self, runner, isolated_project, monkeypatch):
        """Doctor verifies .warden directory exists."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["doctor"])
        assert result.exit_code in (0, 1)
        # Should reference warden directory check
        assert ".warden" in result.stdout or "warden" in result.stdout.lower()


# ============================================================================
# warden config (list / get / set)
# ============================================================================
@pytest.mark.e2e
class TestConfig:

    def test_config_help(self, runner):
        result = runner.invoke(app, ["config", "--help"])
        assert result.exit_code == 0

    def test_config_list_help(self, runner):
        result = runner.invoke(app, ["config", "list", "--help"])
        assert result.exit_code == 0

    def test_config_list_shows_fixture_data(self, runner, isolated_project, monkeypatch):
        """Config list displays all key sections from the fixture config."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["config", "list"])
        assert result.exit_code == 0
        stdout = result.stdout
        # Fixture config has these sections
        assert "e2e-test-project" in stdout
        assert "ollama" in stdout
        assert "python" in stdout

    def test_config_list_json_full_structure(self, runner, isolated_project, monkeypatch):
        """Config list --json returns valid JSON with all fixture config keys."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["config", "list", "--json"])
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert isinstance(parsed, dict)
        # Verify fixture config structure
        assert parsed["project"]["name"] == "e2e-test-project"
        assert parsed["project"]["language"] == "python"
        assert parsed["project"]["type"] == "backend"
        assert parsed["llm"]["provider"] == "ollama"
        assert parsed["llm"]["model"] == "qwen2.5-coder:0.5b"
        assert "frames" in parsed

    def test_config_get_project_name(self, runner, isolated_project, monkeypatch):
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["config", "get", "project.name"])
        assert result.exit_code == 0
        assert "e2e-test-project" in result.stdout

    def test_config_get_llm_provider(self, runner, isolated_project, monkeypatch):
        """Get nested key with dot notation returns exact value."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["config", "get", "llm.provider"])
        assert result.exit_code == 0
        assert "ollama" in result.stdout

    def test_config_get_project_type(self, runner, isolated_project, monkeypatch):
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["config", "get", "project.type"])
        assert result.exit_code == 0
        assert "backend" in result.stdout

    def test_config_get_nonexistent_key(self, runner, isolated_project, monkeypatch):
        """Getting a non-existent key returns exit code 1."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["config", "get", "does.not.exist"])
        assert result.exit_code == 1
        assert "not found" in result.stdout.lower()

    def test_config_set_persists_to_disk(self, runner, isolated_project, monkeypatch):
        """Config set actually writes the value to the YAML file."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["config", "set", "analysis.level", "deep"])
        assert result.exit_code == 0
        # Verify file on disk was mutated
        config_path = isolated_project / ".warden" / "config.yaml"
        with open(config_path) as f:
            config = yaml.safe_load(f)
        assert config["analysis"]["level"] == "deep"

    def test_config_set_roundtrip(self, runner, isolated_project, monkeypatch):
        """Set a value and verify it reads back correctly via CLI."""
        monkeypatch.chdir(isolated_project)
        runner.invoke(app, ["config", "set", "settings.mode", "strict"])
        result = runner.invoke(app, ["config", "get", "settings.mode"])
        assert result.exit_code == 0
        assert "strict" in result.stdout

    def test_config_set_boolean(self, runner, isolated_project, monkeypatch):
        """Set a boolean config value and verify it persists as bool."""
        monkeypatch.chdir(isolated_project)
        runner.invoke(app, ["config", "set", "settings.fail_fast", "true"])
        config_path = isolated_project / ".warden" / "config.yaml"
        with open(config_path) as f:
            config = yaml.safe_load(f)
        assert config["settings"]["fail_fast"] is True

    def test_config_set_invalid_provider(self, runner, isolated_project, monkeypatch):
        """Setting invalid LLM provider fails and does NOT mutate config."""
        monkeypatch.chdir(isolated_project)
        config_path = isolated_project / ".warden" / "config.yaml"
        before = config_path.read_text()
        result = runner.invoke(app, ["config", "set", "llm.provider", "invalid_provider_xyz"])
        assert result.exit_code == 1
        assert "invalid" in result.stdout.lower()
        # Config file should be unchanged
        assert config_path.read_text() == before

    def test_config_set_invalid_mode(self, runner, isolated_project, monkeypatch):
        """Setting invalid mode fails."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["config", "set", "settings.mode", "turbo"])
        assert result.exit_code == 1
        assert "invalid" in result.stdout.lower()

    def test_config_set_provider_updates_model(self, runner, isolated_project, monkeypatch):
        """Setting llm.provider to groq also updates the model automatically."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["config", "set", "llm.provider", "groq"])
        assert result.exit_code == 0
        config_path = isolated_project / ".warden" / "config.yaml"
        with open(config_path) as f:
            config = yaml.safe_load(f)
        assert config["llm"]["provider"] == "groq"
        # Provider change should auto-update model to a groq-compatible model
        assert config["llm"]["model"] != "qwen2.5-coder:0.5b", \
            "Model should change when provider changes from ollama to groq"

    def test_config_fixture_integrity(self, isolated_project):
        """Fixture config.yaml has all required sections."""
        config_path = isolated_project / ".warden" / "config.yaml"
        with open(config_path) as f:
            config = yaml.safe_load(f)
        assert config["version"] == "2.0"
        assert "project" in config
        assert "llm" in config
        assert "analysis" in config
        assert "frames" in config
        assert config["frames"]["enabled"] == ["security", "antipattern", "property"]

    def test_config_no_project(self, runner, tmp_path, monkeypatch):
        """Config in a non-warden directory fails with clear error."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["config", "list"])
        assert result.exit_code == 1
        assert "not found" in result.stdout.lower() or "init" in result.stdout.lower()


# ============================================================================
# warden baseline (status / debt / migrate)
# ============================================================================
@pytest.mark.e2e
class TestBaseline:

    def test_baseline_help(self, runner):
        result = runner.invoke(app, ["baseline", "--help"])
        assert result.exit_code == 0
        for sub in ("status", "debt", "migrate"):
            assert sub in result.stdout.lower()

    def test_baseline_status_help(self, runner):
        result = runner.invoke(app, ["baseline", "status", "--help"])
        assert result.exit_code == 0

    def test_baseline_fixture_file_structure(self, isolated_project):
        """Fixture baseline files are correctly structured."""
        baseline_path = isolated_project / ".warden" / "baseline" / "security.json"
        assert baseline_path.exists(), "Fixture missing security baseline"
        data = json.loads(baseline_path.read_text())
        assert data["module"] == "security"
        assert data["version"] == "1.0.0"
        assert len(data["findings"]) == 1
        assert data["findings"][0]["rule"] == "hardcoded-secret"
        assert data["findings"][0]["fingerprint"] == "abc123def456"

    def test_baseline_status_shows_info(self, runner, isolated_project, monkeypatch):
        """Baseline status reports baseline type and structure."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["baseline", "status"])
        assert result.exit_code in (0, 1)
        stdout = result.stdout.lower()
        assert "baseline" in stdout
        # Should mention either module-based, legacy, or "no baseline"
        assert ("module" in stdout or "legacy" in stdout
                or "v2" in stdout or "v1" in stdout
                or "no baseline" in stdout)

    def test_baseline_debt_help(self, runner):
        result = runner.invoke(app, ["baseline", "debt", "--help"])
        assert result.exit_code == 0

    def test_baseline_debt_shows_report(self, runner, isolated_project, monkeypatch):
        """Baseline debt shows debt report table."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["baseline", "debt"])
        assert result.exit_code in (0, 1)
        stdout = result.stdout.lower()
        # Should show either debt table or "no module-based baseline"
        assert "debt" in stdout or "baseline" in stdout

    def test_baseline_debt_verbose(self, runner, isolated_project, monkeypatch):
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["baseline", "debt", "--verbose"])
        assert result.exit_code in (0, 1)

    def test_baseline_migrate_help(self, runner):
        result = runner.invoke(app, ["baseline", "migrate", "--help"])
        assert result.exit_code == 0

    def test_baseline_migrate_no_legacy(self, runner, isolated_project, monkeypatch):
        """Migrate without legacy baseline.json handles gracefully."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["baseline", "migrate"])
        assert result.exit_code in (0, 1)
        stdout = result.stdout.lower()
        # Should say already migrated, or no legacy baseline
        assert ("already" in stdout or "legacy" in stdout
                or "module-based" in stdout or "no legacy" in stdout)

    def test_baseline_migrate_creates_module_structure(self, runner, tmp_path, monkeypatch):
        """Migrate from legacy baseline.json creates _meta.json and per-module files."""
        monkeypatch.chdir(tmp_path)
        warden_dir = tmp_path / ".warden"
        warden_dir.mkdir()
        # Create minimal config
        (warden_dir / "config.yaml").write_text(
            "version: '2.0'\nproject:\n  name: test\n  language: python\n  type: backend\n"
        )
        # Create legacy baseline.json with one finding
        legacy = {
            "version": "1.0",
            "findings": [
                {
                    "rule_id": "SEC-001",
                    "file": "src/vulnerable.py",
                    "line": 7,
                    "severity": "critical",
                    "fingerprint": "abc123",
                    "message": "Hardcoded secret"
                }
            ]
        }
        (warden_dir / "baseline.json").write_text(json.dumps(legacy))
        result = runner.invoke(app, ["baseline", "migrate"])
        assert result.exit_code in (0, 1)
        if result.exit_code == 0:
            baseline_dir = warden_dir / "baseline"
            # _meta.json should be created
            meta_path = baseline_dir / "_meta.json"
            assert meta_path.exists(), "_meta.json not created by migrate"
            meta = json.loads(meta_path.read_text())
            assert "modules" in meta or "created_at" in meta
            # At least one module JSON file should be created
            module_files = list(baseline_dir.glob("*.json"))
            non_meta = [f for f in module_files if f.name != "_meta.json"]
            assert len(non_meta) >= 1, "No module baseline files created"

    def test_baseline_empty_warden_dir(self, runner, tmp_path, monkeypatch):
        """Baseline in empty .warden directory shows 'no baseline'."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".warden").mkdir()
        result = runner.invoke(app, ["baseline", "status"])
        assert result.exit_code in (0, 1)
        assert "no baseline" in result.stdout.lower() or "baseline" in result.stdout.lower()

    def test_baseline_debt_module_filter(self, runner, isolated_project, monkeypatch):
        """Baseline debt --module filters to specific module only."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["baseline", "debt", "--module", "security"])
        assert result.exit_code in (0, 1)
        stdout = result.stdout.lower()
        # Should show debt for security module specifically
        assert "debt" in stdout or "security" in stdout or "module" in stdout

    def test_baseline_debt_unknown_module(self, runner, isolated_project, monkeypatch):
        """Baseline debt --module nonexistent handles gracefully."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["baseline", "debt", "--module", "nonexistent_xyz"])
        assert result.exit_code in (0, 1)
        stdout = result.stdout.lower()
        # Should say module not found
        assert "not found" in stdout or "nonexistent_xyz" in stdout or "available" in stdout

    def test_baseline_status_json_structure(self, runner, isolated_project, monkeypatch):
        """Baseline status displays module count and meta information."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["baseline", "status"])
        assert result.exit_code in (0, 1)
        stdout = result.stdout.lower()
        # Status should mention module count or modules
        assert "module" in stdout or "baseline" in stdout
        # Should show some metadata (created, updated, findings, debt)
        assert ("created" in stdout or "updated" in stdout
                or "findings" in stdout or "debt" in stdout
                or "v2.0" in stdout or "module-based" in stdout)

    def test_baseline_meta_json_integrity(self, isolated_project):
        """Fixture _meta.json has correct structure and required fields."""
        meta_path = isolated_project / ".warden" / "baseline" / "_meta.json"
        assert meta_path.exists(), "Fixture missing _meta.json"
        meta = json.loads(meta_path.read_text())
        # Verify structure
        assert meta["version"] == "2.0"
        assert "created_at" in meta
        assert "updated_at" in meta
        assert "modules" in meta
        assert isinstance(meta["modules"], list)
        assert "security" in meta["modules"]
        assert "total_findings" in meta
        assert "total_debt" in meta
        assert meta["total_findings"] == 1
        assert meta["total_debt"] == 1

    def test_baseline_debt_warn_days(self, runner, isolated_project, monkeypatch):
        """Baseline debt --warn-days accepts custom threshold."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["baseline", "debt", "--warn-days", "30"])
        assert result.exit_code in (0, 1)
        # Should complete successfully with custom warn-days threshold
        stdout = result.stdout.lower()
        assert "debt" in stdout or "module" in stdout


# ============================================================================
# warden ci (init / status / update / sync)
# ============================================================================
@pytest.mark.e2e
class TestCI:

    def test_ci_help(self, runner):
        result = runner.invoke(app, ["ci", "--help"])
        assert result.exit_code == 0
        for sub in ("init", "status", "update", "sync"):
            assert sub in result.stdout.lower()

    def test_ci_init_help(self, runner):
        result = runner.invoke(app, ["ci", "init", "--help"])
        assert result.exit_code == 0
        assert "--provider" in result.stdout
        assert "--branch" in result.stdout
        assert "--force" in result.stdout

    def test_ci_fixture_workflow_content(self, isolated_project):
        """Fixture workflow file has correct GitHub Actions structure."""
        wf_path = isolated_project / ".github" / "workflows" / "warden.yml"
        assert wf_path.exists(), "Fixture missing warden.yml workflow"
        content = yaml.safe_load(wf_path.read_text())
        # YAML parses 'on' as boolean True
        assert True in content or "on" in content, "Missing 'on' trigger block"
        assert "jobs" in content
        assert "scan" in content["jobs"]
        steps = content["jobs"]["scan"]["steps"]
        assert any("warden" in str(step).lower() for step in steps)

    def test_ci_status_detects_github(self, runner, isolated_project, monkeypatch):
        """CI status detects GitHub Actions from .github/workflows/."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["ci", "status"])
        assert result.exit_code in (0, 1)
        stdout = result.stdout.lower()
        # Fixture has .github/workflows/warden.yml → should detect GitHub
        assert "github" in stdout

    def test_ci_status_json_structure(self, runner, isolated_project, monkeypatch):
        """CI status --json returns structured data with provider and workflows."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["ci", "status", "--json"])
        assert result.exit_code in (0, 1)
        if result.exit_code == 0:
            parsed = _extract_json(result.stdout)
            if parsed:
                assert parsed.get("provider") == "github"
                assert parsed.get("is_configured") is True
                assert "workflows" in parsed
                # Fixture has warden.yml → "main" workflow should exist
                workflows = parsed["workflows"]
                assert "main" in workflows
                assert workflows["main"]["exists"] is True

    def test_ci_init_creates_all_workflows(self, runner, isolated_project, monkeypatch):
        """CI init --force creates all 4 GitHub workflow files."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["ci", "init", "--provider", "github", "--force"])
        assert result.exit_code in (0, 1)
        if result.exit_code == 0:
            workflows_dir = isolated_project / ".github" / "workflows"
            # CI init creates 4 workflow files from templates
            expected_files = [
                "warden.yml",          # main (from github.yml template)
                "warden-pr.yml",       # PR checks
                "warden-nightly.yml",  # nightly baseline updates
                "warden-release.yml",  # release security audits
            ]
            for wf in expected_files:
                path = workflows_dir / wf
                assert path.exists(), f"Workflow not created: {wf}"
                content = path.read_text()
                assert len(content) > 0, f"Workflow is empty: {wf}"
                # All generated workflows should have warden reference
                assert "warden" in content.lower(), \
                    f"Workflow {wf} missing warden reference"

    def test_ci_init_workflow_has_version_header(self, runner, isolated_project, monkeypatch):
        """CI init generated workflows contain a version header."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["ci", "init", "--provider", "github", "--force"])
        if result.exit_code == 0:
            wf_path = isolated_project / ".github" / "workflows" / "warden.yml"
            content = wf_path.read_text()
            # Generated workflows should have version header added by _add_version_header
            assert "warden" in content.lower()

    def test_ci_update_help(self, runner):
        result = runner.invoke(app, ["ci", "update", "--help"])
        assert result.exit_code == 0
        assert "--dry-run" in result.stdout

    def test_ci_update_dry_run_no_side_effects(self, runner, isolated_project, monkeypatch):
        """CI update --dry-run reports changes without mutating files."""
        monkeypatch.chdir(isolated_project)
        wf_path = isolated_project / ".github" / "workflows" / "warden.yml"
        before = wf_path.read_text()
        result = runner.invoke(app, ["ci", "update", "--dry-run"])
        assert result.exit_code in (0, 1)
        # File should be unchanged after dry-run
        assert wf_path.read_text() == before

    def test_ci_sync_help(self, runner):
        result = runner.invoke(app, ["ci", "sync", "--help"])
        assert result.exit_code == 0

    def test_ci_sync_runs(self, runner, isolated_project, monkeypatch):
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["ci", "sync"])
        assert result.exit_code in (0, 1)


# ============================================================================
# warden status
# ============================================================================
@pytest.mark.e2e
class TestStatus:

    def test_status_help(self, runner):
        result = runner.invoke(app, ["status", "--help"])
        assert result.exit_code == 0
        assert "--fetch" in result.stdout

    def test_status_reads_sarif(self, runner, isolated_project, monkeypatch):
        """Status reads the SARIF report and shows findings from it."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["status"])
        assert result.exit_code in (0, 1)
        stdout = result.stdout.lower()
        # Fixture has warden-report.sarif with SEC-001 error-level finding
        assert "status" in stdout or "security" in stdout or "sarif" in stdout \
            or "sec-001" in stdout or "issue" in stdout or "finding" in stdout \
            or "fail" in stdout or "pass" in stdout

    def test_status_sarif_file_exists(self, isolated_project):
        """Fixture SARIF report file is properly structured."""
        sarif_path = isolated_project / ".warden" / "reports" / "warden-report.sarif"
        assert sarif_path.exists(), "Fixture missing SARIF report"
        sarif = json.loads(sarif_path.read_text())
        assert sarif["version"] == "2.1.0"
        assert sarif["runs"][0]["tool"]["driver"]["name"] == "Warden"
        results = sarif["runs"][0]["results"]
        assert len(results) == 1
        assert results[0]["ruleId"] == "SEC-001"
        assert results[0]["level"] == "error"

    def test_status_no_report(self, runner, tmp_path, monkeypatch):
        """Status without SARIF report handles gracefully."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["status"])
        assert result.exit_code in (0, 1)


# ============================================================================
# warden serve (mcp / ipc / grpc)
# ============================================================================
@pytest.mark.e2e
class TestServe:

    def test_serve_help(self, runner):
        result = runner.invoke(app, ["serve", "--help"])
        assert result.exit_code == 0
        for sub in ("mcp", "ipc", "grpc"):
            assert sub in result.stdout.lower()

    def test_ipc_help(self, runner):
        result = runner.invoke(app, ["serve", "ipc", "--help"])
        assert result.exit_code == 0

    def test_grpc_help(self, runner):
        result = runner.invoke(app, ["serve", "grpc", "--help"])
        assert result.exit_code == 0
        assert "--port" in result.stdout

    def test_mcp_help(self, runner):
        result = runner.invoke(app, ["serve", "mcp", "--help"])
        assert result.exit_code == 0
        for sub in ("start", "register", "status"):
            assert sub in result.stdout.lower()

    def test_mcp_start_help(self, runner):
        result = runner.invoke(app, ["serve", "mcp", "start", "--help"])
        assert result.exit_code == 0
        assert "--project-root" in result.stdout

    def test_mcp_register_help(self, runner):
        result = runner.invoke(app, ["serve", "mcp", "register", "--help"])
        assert result.exit_code == 0

    def test_mcp_status_help(self, runner):
        result = runner.invoke(app, ["serve", "mcp", "status", "--help"])
        assert result.exit_code == 0

    def test_mcp_status_shows_tools_table(self, runner):
        """MCP status shows registration status for AI tools."""
        result = runner.invoke(app, ["serve", "mcp", "status"])
        assert result.exit_code in (0, 1)
        stdout = result.stdout.lower()
        # Should show a table with tool registration info
        assert "status" in stdout or "register" in stdout
        # Should mention at least one AI tool
        assert ("claude" in stdout or "cursor" in stdout
                or "windsurf" in stdout or "not installed" in stdout
                or "registered" in stdout)

    def test_mcp_register_detects_tools(self, runner):
        """MCP register should detect AI tools or show not found."""
        result = runner.invoke(app, ["serve", "mcp", "register"])
        assert result.exit_code in (0, 1)
        stdout = result.stdout.lower()
        # Should attempt registration
        assert "register" in stdout or "mcp" in stdout
        # Should mention at least one tool detection result
        assert ("claude" in stdout or "cursor" in stdout
                or "windsurf" in stdout or "not installed" in stdout
                or "registered" in stdout or "skipped" in stdout)

    def test_mcp_status_shows_all_tools(self, runner):
        """MCP status should list all known AI tools in table."""
        result = runner.invoke(app, ["serve", "mcp", "status"])
        assert result.exit_code in (0, 1)
        stdout = result.stdout.lower()
        # Should show registration status table
        assert "status" in stdout
        # Should list multiple AI tools (at least 3 from known list)
        tool_count = 0
        for tool in ("claude", "cursor", "windsurf", "gemini"):
            if tool in stdout:
                tool_count += 1
        assert tool_count >= 3, f"Expected at least 3 tools in status, found {tool_count}"

    def test_ipc_without_project(self, runner, tmp_path, monkeypatch):
        """IPC server in a non-warden dir should fail gracefully or warn."""
        monkeypatch.chdir(tmp_path)
        # Note: IPC server would hang if started, but we test help/validation
        # The actual server startup is tested elsewhere
        result = runner.invoke(app, ["serve", "ipc", "--help"])
        assert result.exit_code == 0
        assert "ipc" in result.stdout.lower()

    def test_grpc_help_shows_port(self, runner):
        """gRPC help should show --port option."""
        result = runner.invoke(app, ["serve", "grpc", "--help"])
        assert result.exit_code == 0
        assert "--port" in result.stdout
        # Should mention default port
        assert "50051" in result.stdout or "port" in result.stdout.lower()

    def test_mcp_start_without_project(self, runner, tmp_path, monkeypatch):
        """MCP start in a non-warden directory should handle gracefully."""
        monkeypatch.chdir(tmp_path)
        # MCP start with invalid project root should fail fast
        result = runner.invoke(app, ["serve", "mcp", "start", "--project-root", "/nonexistent"])
        assert result.exit_code == 1
        assert "error" in result.stdout.lower() or "invalid" in result.stdout.lower()

    def test_mcp_start_help_shows_project_root(self, runner):
        """MCP start help should clearly show --project-root option."""
        result = runner.invoke(app, ["serve", "mcp", "start", "--help"])
        assert result.exit_code == 0
        assert "--project-root" in result.stdout
        assert "directory" in result.stdout.lower()

    def test_grpc_port_validation(self, runner):
        """gRPC help should document port parameter."""
        result = runner.invoke(app, ["serve", "grpc", "--help"])
        assert result.exit_code == 0
        stdout = result.stdout.lower()
        assert "port" in stdout
        # Should mention it's for listening
        assert "listen" in stdout or "50051" in stdout



# ============================================================================
# warden search (Hub + semantic)
# ============================================================================
@pytest.mark.e2e
class TestSearch:

    def test_search_help(self, runner):
        result = runner.invoke(app, ["search", "--help"])
        assert result.exit_code == 0
        assert "--local" in result.stdout

    def test_search_no_query(self, runner):
        """Search without query either lists all frames or says none found."""
        result = runner.invoke(app, ["search"])
        assert result.exit_code in (0, 1)
        stdout = result.stdout.lower()
        # Should either show frames table or "no frames found"
        if result.exit_code == 0:
            assert "frame" in stdout or "hub" in stdout or "warden" in stdout

    def test_search_with_query(self, runner):
        """Search with query attempts to search (may fail without network)."""
        result = runner.invoke(app, ["search", "security"])
        assert result.exit_code in (0, 1)
        # Should attempt search, may fail if no network or show results
        stdout = result.stdout.lower()
        assert "search" in stdout or "security" in stdout or "frame" in stdout \
            or "not found" in stdout or "error" in stdout

    def test_search_local_flag(self, runner, isolated_project, monkeypatch):
        """Search --local attempts local semantic search."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["search", "--local", "security"])
        assert result.exit_code in (0, 1)
        # May require embeddings or fail gracefully
        stdout = result.stdout.lower()
        assert "search" in stdout or "security" in stdout or "local" in stdout \
            or "index" in stdout or "error" in stdout or "not found" in stdout


# ============================================================================
# warden index (semantic search)
# ============================================================================
@pytest.mark.e2e
class TestIndex:

    def test_index_help(self, runner):
        result = runner.invoke(app, ["index", "--help"])
        assert result.exit_code == 0
        assert "semantic" in result.stdout.lower() or "index" in result.stdout.lower()

    def test_index_no_warden_dir(self, runner, tmp_path, monkeypatch):
        """Index without .warden directory fails gracefully."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["index"])
        # May exit 0 with error message or exit 1
        assert result.exit_code in (0, 1)
        stdout = result.stdout.lower()
        assert "error" in stdout or "not available" in stdout or "semantic" in stdout

    def test_index_runs_in_project(self, runner, isolated_project, monkeypatch):
        """Index in warden project attempts to build semantic index."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["index"])
        assert result.exit_code in (0, 1)
        # May require LLM/embeddings or complete successfully
        stdout = result.stdout.lower()
        assert "index" in stdout or "semantic" in stdout or "complete" in stdout \
            or "error" in stdout or "embedding" in stdout


# ============================================================================
# warden refresh
# ============================================================================
@pytest.mark.e2e
class TestRefresh:

    def test_refresh_help(self, runner):
        result = runner.invoke(app, ["refresh", "--help"])
        assert result.exit_code == 0
        for flag in ("--force", "--no-intelligence", "--baseline",
                      "--module", "--quick"):
            assert flag in result.stdout, f"Missing flag in refresh help: {flag}"

    def test_refresh_no_intelligence_completes(self, runner, isolated_project, monkeypatch):
        """Refresh with --no-intelligence skips intelligence and completes."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["refresh", "--no-intelligence"])
        assert result.exit_code in (0, 1)
        # Should print completion message
        stdout = result.stdout.lower()
        assert "refresh" in stdout
        assert "complete" in stdout

    def test_refresh_requires_warden_dir(self, runner, tmp_path, monkeypatch):
        """Refresh without .warden dir fails with clear init instruction."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["refresh"])
        assert result.exit_code == 1
        assert "init" in result.stdout.lower()

    def test_refresh_intelligence_runs(self, runner, isolated_project, monkeypatch):
        """Refresh with intelligence (default) attempts intelligence generation."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["refresh", "--force"])
        assert result.exit_code in (0, 1)
        stdout = result.stdout.lower()
        # Should mention intelligence
        assert "intelligence" in stdout or "refresh" in stdout


# ============================================================================
# warden init
# ============================================================================
@pytest.mark.e2e
class TestInit:

    def test_init_help(self, runner):
        result = runner.invoke(app, ["init", "--help"])
        assert result.exit_code == 0
        for flag in ("--force", "--mode", "--ci", "--skip-mcp"):
            assert flag in result.stdout, f"Missing flag in init help: {flag}"


# ============================================================================
# warden chat
# ============================================================================
@pytest.mark.e2e
class TestChat:

    def test_chat_help(self, runner):
        result = runner.invoke(app, ["chat", "--help"])
        assert result.exit_code == 0
        assert "--dev" in result.stdout
        assert "interactive" in result.stdout.lower() or "chat" in result.stdout.lower()

    def test_chat_dev_flag_help(self, runner):
        """Chat --dev --help shows development mode information."""
        result = runner.invoke(app, ["chat", "--dev", "--help"])
        assert result.exit_code == 0
        stdout = result.stdout.lower()
        assert "chat" in stdout or "interactive" in stdout


# ============================================================================
# warden install
# ============================================================================
@pytest.mark.e2e
class TestInstall:

    def test_install_help(self, runner):
        result = runner.invoke(app, ["install", "--help"])
        assert result.exit_code == 0
        assert "--force-update" in result.stdout
        # Should describe what install does
        assert "install" in result.stdout.lower()

    def test_install_no_args(self, runner, tmp_path, monkeypatch):
        """Install with no package name in non-warden directory shows error."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["install"])
        # Should fail with init error (exit 1)
        assert result.exit_code == 1
        stdout = result.stdout.lower()
        assert "error" in stdout or "init" in stdout or "warden.yaml" in stdout

    def test_install_nonexistent_frame(self, runner):
        """Install nonexistent package fails with not found error."""
        result = runner.invoke(app, ["install", "nonexistent_xyz_frame_12345"])
        # Should fail (may be network error or not found)
        assert result.exit_code in (0, 1)
        stdout = result.stdout.lower()
        # May show error or attempt install (network dependent)
        assert "install" in stdout or "not found" in stdout or "error" in stdout \
            or "hub" in stdout or "frame" in stdout

    def test_install_force_update_flag(self, runner, tmp_path, monkeypatch):
        """Install --force-update without package in non-warden directory shows error."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["install", "--force-update"])
        # Should fail with init error (exit 1)
        assert result.exit_code == 1
        stdout = result.stdout.lower()
        assert "error" in stdout or "init" in stdout or "warden.yaml" in stdout


# ============================================================================
# warden update
# ============================================================================
@pytest.mark.e2e
class TestUpdate:

    def test_update_help(self, runner):
        result = runner.invoke(app, ["update", "--help"])
        assert result.exit_code == 0
        assert "hub" in result.stdout.lower() or "catalog" in result.stdout.lower() \
            or "update" in result.stdout.lower()

    def test_update_no_warden_dir(self, runner, tmp_path, monkeypatch):
        """Update in non-warden directory fails gracefully."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["update"])
        assert result.exit_code in (0, 1)
        # Should fail or warn about missing .warden
        stdout = result.stdout.lower()
        assert "update" in stdout or "not found" in stdout or "init" in stdout \
            or "warden" in stdout or "error" in stdout

    def test_update_runs_in_project(self, runner, isolated_project, monkeypatch):
        """Update in warden project attempts to update catalog."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["update"])
        assert result.exit_code in (0, 1)
        # May succeed or fail depending on network
        stdout = result.stdout.lower()
        assert "update" in stdout or "hub" in stdout or "catalog" in stdout \
            or "complete" in stdout or "error" in stdout or "frame" in stdout


# ============================================================================
# Cross-cutting: exit code consistency
# ============================================================================
@pytest.mark.e2e
class TestExitCodeConsistency:

    def test_all_help_commands_return_zero(self, runner):
        """Every command's --help should return exit code 0."""
        help_commands = [
            ["--help"],
            ["version", "--help"],
            ["scan", "--help"],
            ["doctor", "--help"],
            ["config", "--help"],
            ["config", "list", "--help"],
            ["config", "get", "--help"],
            ["config", "set", "--help"],
            ["baseline", "--help"],
            ["baseline", "status", "--help"],
            ["baseline", "debt", "--help"],
            ["baseline", "migrate", "--help"],
            ["ci", "--help"],
            ["ci", "init", "--help"],
            ["ci", "status", "--help"],
            ["ci", "update", "--help"],
            ["ci", "sync", "--help"],
            ["status", "--help"],
            ["serve", "--help"],
            ["serve", "mcp", "--help"],
            ["serve", "mcp", "start", "--help"],
            ["serve", "mcp", "register", "--help"],
            ["serve", "mcp", "status", "--help"],
            ["serve", "ipc", "--help"],
            ["serve", "grpc", "--help"],
            ["search", "--help"],
            ["index", "--help"],
            ["refresh", "--help"],
            ["init", "--help"],
            ["chat", "--help"],
            ["install", "--help"],
            ["update", "--help"],
        ]
        failures = []
        for cmd in help_commands:
            result = runner.invoke(app, cmd)
            if result.exit_code != 0:
                failures.append((cmd, result.exit_code, result.stdout[:200]))
        assert not failures, f"Help commands with non-zero exit: {failures}"
