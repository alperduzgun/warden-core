"""E2E tests for new init flags and LLM config subcommands.

Covers:
- warden init --help shows new flags (--agent/--no-agent, --baseline, --intel, --grammars)
- warden config llm status/test/use basic behavior
"""

import json
from pathlib import Path

import pytest
from warden.main import app


@pytest.mark.e2e
def test_init_help_shows_new_flags(runner, monkeypatch):
    # Ensure settings parsing doesn't break due to external env
    monkeypatch.setenv("CORS_ORIGINS", "[]")
    result = runner.invoke(app, ["init", "--help"])
    assert result.exit_code == 0
    out = result.stdout
    for flag in ("--agent", "--no-agent", "--baseline", "--no-baseline", "--intel", "--no-intel", "--grammars", "--no-grammars"):
        assert flag in out, f"missing flag: {flag}"


@pytest.mark.e2e
def test_config_llm_help_and_status(runner, isolated_project, monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "[]")
    monkeypatch.chdir(isolated_project)

    # Help should list subcommands
    help_res = runner.invoke(app, ["config", "llm", "--help"])
    assert help_res.exit_code == 0
    assert "status" in help_res.stdout
    assert "use" in help_res.stdout
    assert "test" in help_res.stdout

    # Status should render without crashing in fixture project
    status_res = runner.invoke(app, ["config", "llm", "status"])
    assert status_res.exit_code == 0
    assert "LLM Status" in status_res.stdout


@pytest.mark.e2e
def test_config_llm_use_and_test_ollama(runner, isolated_project, monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "[]")
    monkeypatch.chdir(isolated_project)

    # Switch provider to ollama and verify persisted
    use_res = runner.invoke(app, ["config", "llm", "use", "ollama"])
    assert use_res.exit_code == 0

    cfg_path = Path(".warden/config.yaml")
    data = json.loads(runner.invoke(app, ["config", "list", "--json"]).stdout)
    assert data.get("llm", {}).get("provider") == "ollama"

    # Test should succeed with a basic check (does not require network)
    test_res = runner.invoke(app, ["config", "llm", "test"])
    assert test_res.exit_code == 0
    # Output should at least mention provider name
    assert "ollama" in test_res.stdout.lower()

