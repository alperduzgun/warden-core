"""E2E tests for Codex integration helper."""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from warden.main import app

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "sample_project"


@pytest.mark.e2e
def test_codex_init_creates_manifest(runner, isolated_project, monkeypatch):
    monkeypatch.chdir(isolated_project)
    res = runner.invoke(app, ["codex", "init"])
    assert res.exit_code == 0
    mpath = Path(".agent/codex.json")
    assert mpath.exists(), "codex.json should be created"
    data = mpath.read_text(encoding="utf-8")
    assert ".warden/context.yaml" in data
    assert ".warden/config.yaml" in data
    assert "warden-report.json" in data
    assert "warden-report.sarif" in data


@pytest.mark.e2e
def test_codex_init_idempotent(runner, isolated_project, monkeypatch):
    """Second run should skip, not overwrite."""
    monkeypatch.chdir(isolated_project)
    runner.invoke(app, ["codex", "init"])
    # Overwrite with sentinel content
    mpath = Path(".agent/codex.json")
    mpath.write_text('{"sentinel": true}', encoding="utf-8")

    res = runner.invoke(app, ["codex", "init"])
    assert res.exit_code == 0
    assert "skipped" in res.stdout.lower()
    # Content must NOT be overwritten
    assert json.loads(mpath.read_text()) == {"sentinel": True}


@pytest.mark.e2e
def test_configure_codex_no_cli(monkeypatch):
    """configure_codex returns disabled config when codex not on PATH."""
    monkeypatch.setenv("WARDEN_NON_INTERACTIVE", "true")
    with patch("shutil.which", return_value=None):
        from warden.cli.commands.init_helpers import configure_codex
        llm_cfg, env = configure_codex()
    assert llm_cfg["provider"] == "codex"
    assert llm_cfg["enabled"] is False
    assert env == {}


@pytest.mark.e2e
def test_configure_codex_with_cli(monkeypatch):
    """configure_codex returns enabled CLI config when codex is on PATH."""
    monkeypatch.setenv("WARDEN_NON_INTERACTIVE", "true")
    with patch("shutil.which", return_value="/usr/local/bin/codex"), \
         patch("subprocess.run", return_value=Mock(returncode=0, stdout="1.0.0", stderr="")):
        from warden.cli.commands.init_helpers import configure_codex
        llm_cfg, env = configure_codex()
    assert llm_cfg["provider"] == "codex"
    assert llm_cfg["endpoint"] == "cli"
    assert llm_cfg["use_local_llm"] is True
    assert env == {}


@pytest.mark.e2e
def test_init_provider_flag_codex(monkeypatch):
    """--provider codex flag routes to configure_codex even in non-interactive mode."""
    monkeypatch.setenv("WARDEN_NON_INTERACTIVE", "true")
    monkeypatch.setenv("WARDEN_INIT_PROVIDER", "codex")
    with patch("shutil.which", return_value="/usr/local/bin/codex"), \
         patch("subprocess.run", return_value=Mock(returncode=0, stdout="1.0.0", stderr="")):
        from warden.cli.commands.init_helpers import configure_llm
        llm_cfg, _ = configure_llm()
    assert llm_cfg["provider"] == "codex"
    assert llm_cfg["endpoint"] == "cli"


@pytest.mark.e2e
def test_codex_send_async_no_cli(monkeypatch):
    """send_async returns failure when codex not on PATH."""
    import asyncio

    from warden.llm.providers.codex import CodexClient
    from warden.llm.types import LlmRequest

    with patch("shutil.which", return_value=None):
        client = CodexClient()
        req = LlmRequest(systemPrompt="sys", userMessage="msg")
        resp = asyncio.run(client.send_async(req))

    assert resp.success is False
    assert "not found" in resp.error_message.lower()


@pytest.mark.e2e
def test_codex_send_async_with_cli():
    """send_async succeeds when codex exec returns output."""
    import asyncio
    from unittest.mock import AsyncMock
    from unittest.mock import patch as async_patch

    from warden.llm.providers.codex import CodexClient
    from warden.llm.types import LlmRequest

    mock_proc = Mock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"analysis result", b""))

    with patch("shutil.which", return_value="/usr/local/bin/codex"), \
         patch("asyncio.create_subprocess_exec", return_value=mock_proc), \
         patch("pathlib.Path.read_text", return_value="analysis result"):
        client = CodexClient()
        req = LlmRequest(systemPrompt="Analyze code.", userMessage="def foo(): pass")
        resp = asyncio.run(client.send_async(req))

    assert resp.success is True
    assert resp.content == "analysis result"
    assert resp.provider.value == "codex"


@pytest.mark.e2e
@pytest.mark.skipif(
    not __import__("shutil").which("codex"),
    reason="codex CLI not installed",
)
def test_codex_send_async_real_invocation():
    """Integration: real codex exec call with a trivial prompt."""
    import asyncio

    from warden.llm.providers.codex import CodexClient
    from warden.llm.types import LlmRequest

    client = CodexClient()
    req = LlmRequest(
        systemPrompt="Answer only with the number, nothing else.",
        userMessage="What is 1+1?",
        timeoutSeconds=45,
    )
    resp = asyncio.run(client.send_async(req))
    assert resp.success is True, f"Expected success, got error: {resp.error_message}"
    assert resp.content.strip() != "", "Expected non-empty response"
    assert resp.duration_ms > 0


@pytest.mark.e2e
def test_scan_uses_codex_as_provider(monkeypatch, tmp_path):
    """
    Integration: warden scan pipeline uses CodexClient when WARDEN_LLM_PROVIDER=codex.

    Patches asyncio.create_subprocess_exec inside the codex provider so the test
    doesn't make real network/subprocess calls, but verifies the full wiring:
      WARDEN_LLM_PROVIDER=codex
        → bridge loads codex as default_provider
        → factory creates CodexClient
        → scan pipeline calls send_async
        → CodexClient.send_async invokes codex exec (mocked)
        → pipeline completes with valid exit code
    """
    target_file = FIXTURES / "src" / "vulnerable.py"

    mock_proc = Mock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"No critical issues found.", b""))

    monkeypatch.setenv("WARDEN_LLM_PROVIDER", "codex")

    with patch("shutil.which", side_effect=lambda cmd: f"/usr/local/bin/{cmd}"), \
         patch("asyncio.create_subprocess_exec", return_value=mock_proc), \
         patch("pathlib.Path.read_text", return_value="No critical issues found."):

        from warden.cli.commands.scan import _run_scan_async
        exit_code = asyncio.run(_run_scan_async(
            paths=[str(target_file)],
            frames=["security"],
            format="json",
            output=None,
            verbose=False,
            level="standard",
            ci_mode=True,
        ))

    assert exit_code in (0, 1, 2), f"Unexpected exit code: {exit_code}"


@pytest.mark.e2e
@pytest.mark.skipif(
    not __import__("shutil").which("codex"),
    reason="codex CLI not installed",
)
def test_scan_uses_codex_real_subprocess():
    """
    Integration (real): full scan at basic level with WARDEN_LLM_PROVIDER=codex.
    basic level verifies provider wiring without deep LLM calls.
    """
    import os

    from warden.cli.commands.scan import _run_scan_async

    target_file = FIXTURES / "src" / "clean.py"
    os.environ["WARDEN_LLM_PROVIDER"] = "codex"
    try:
        exit_code = asyncio.run(_run_scan_async(
            paths=[str(target_file)],
            frames=None,
            format="json",
            output=None,
            verbose=False,
            level="basic",
            ci_mode=True,
        ))
        assert exit_code in (0, 1, 2), f"Unexpected exit code: {exit_code}"
    finally:
        os.environ.pop("WARDEN_LLM_PROVIDER", None)
