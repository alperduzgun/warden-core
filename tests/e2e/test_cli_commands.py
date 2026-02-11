"""E2E tests for all warden CLI commands (non-scan).

Tests every CLI command's help, basic invocation, and key behaviors.
Uses CliRunner (in-process) for deterministic, fast testing.
"""

import pytest
from warden.main import app


# ============================================================================
# warden --help / version
# ============================================================================
@pytest.mark.e2e
class TestGlobalCLI:

    def test_help(self, runner):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "warden" in result.stdout.lower()

    def test_version(self, runner):
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert "warden" in result.stdout.lower() or "version" in result.stdout.lower()


# ============================================================================
# warden doctor
# ============================================================================
@pytest.mark.e2e
class TestDoctor:

    def test_help(self, runner):
        result = runner.invoke(app, ["doctor", "--help"])
        assert result.exit_code == 0

    def test_doctor_runs(self, runner, isolated_project, monkeypatch):
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["doctor"])
        # doctor returns 0 (healthy) or 1 (issues) — both are valid
        assert result.exit_code in (0, 1)


# ============================================================================
# warden config (list / get / set)
# ============================================================================
@pytest.mark.e2e
class TestConfig:

    def test_config_list_help(self, runner):
        result = runner.invoke(app, ["config", "list", "--help"])
        assert result.exit_code == 0

    def test_config_list(self, runner, isolated_project, monkeypatch):
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["config", "list"])
        assert result.exit_code == 0

    def test_config_list_json(self, runner, isolated_project, monkeypatch):
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["config", "list", "--json"])
        assert result.exit_code == 0

    def test_config_get(self, runner, isolated_project, monkeypatch):
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["config", "get", "project.name"])
        assert result.exit_code == 0

    def test_config_set(self, runner, isolated_project, monkeypatch):
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["config", "set", "analysis.level", "deep"])
        assert result.exit_code == 0


# ============================================================================
# warden baseline (status / debt / migrate)
# ============================================================================
@pytest.mark.e2e
class TestBaseline:

    def test_baseline_status_help(self, runner):
        result = runner.invoke(app, ["baseline", "status", "--help"])
        assert result.exit_code == 0

    def test_baseline_status(self, runner, isolated_project, monkeypatch):
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["baseline", "status"])
        # 0=ok or 1=no baseline — both valid
        assert result.exit_code in (0, 1)

    def test_baseline_debt_help(self, runner):
        result = runner.invoke(app, ["baseline", "debt", "--help"])
        assert result.exit_code == 0

    def test_baseline_debt(self, runner, isolated_project, monkeypatch):
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["baseline", "debt"])
        assert result.exit_code in (0, 1)


# ============================================================================
# warden ci (init / status / update / sync)
# ============================================================================
@pytest.mark.e2e
class TestCI:

    def test_ci_init_help(self, runner):
        result = runner.invoke(app, ["ci", "init", "--help"])
        assert result.exit_code == 0

    def test_ci_status_help(self, runner):
        result = runner.invoke(app, ["ci", "status", "--help"])
        assert result.exit_code == 0

    def test_ci_status(self, runner, isolated_project, monkeypatch):
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["ci", "status"])
        assert result.exit_code in (0, 1)

    def test_ci_init(self, runner, isolated_project, monkeypatch):
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["ci", "init", "--provider", "github"])
        assert result.exit_code in (0, 1)

    def test_ci_update_dry_run(self, runner, isolated_project, monkeypatch):
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["ci", "update", "--dry-run"])
        assert result.exit_code in (0, 1)


# ============================================================================
# warden status
# ============================================================================
@pytest.mark.e2e
class TestStatus:

    def test_status_help(self, runner):
        result = runner.invoke(app, ["status", "--help"])
        assert result.exit_code == 0

    def test_status_local(self, runner, isolated_project, monkeypatch):
        """Status reads local SARIF report (no --fetch)."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["status"])
        assert result.exit_code in (0, 1)


# ============================================================================
# warden serve mcp (register / status)
# ============================================================================
@pytest.mark.e2e
class TestServeMCP:

    def test_mcp_status_help(self, runner):
        result = runner.invoke(app, ["serve", "mcp", "status", "--help"])
        assert result.exit_code == 0

    def test_mcp_status(self, runner):
        result = runner.invoke(app, ["serve", "mcp", "status"])
        assert result.exit_code in (0, 1)


# ============================================================================
# warden search (Hub — local cache)
# ============================================================================
@pytest.mark.e2e
class TestSearch:

    def test_search_help(self, runner):
        result = runner.invoke(app, ["search", "--help"])
        assert result.exit_code == 0


# ============================================================================
# warden refresh
# ============================================================================
@pytest.mark.e2e
class TestRefresh:

    def test_refresh_help(self, runner):
        result = runner.invoke(app, ["refresh", "--help"])
        assert result.exit_code == 0


# ============================================================================
# warden init (--skip-mcp, no interactive prompts)
# ============================================================================
@pytest.mark.e2e
class TestInit:

    def test_init_help(self, runner):
        result = runner.invoke(app, ["init", "--help"])
        assert result.exit_code == 0
