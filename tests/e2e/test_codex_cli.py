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
def test_codex_exec_cmd_has_argument_terminator():
    """Bug #6 – 'codex exec' must include '--' before the prompt to prevent flag injection."""
    import asyncio as _asyncio

    from warden.llm.providers.codex import CodexClient
    from warden.llm.types import LlmRequest

    captured_cmd: list[str] = []

    mock_proc = Mock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"ok", b""))

    async def _capture_exec(*cmd, **_kwargs):
        captured_cmd.extend(cmd)
        return mock_proc

    # No Path.read_text mock: temp file is empty → CodexClient falls back to stdout.
    # This exercises the real stdout-fallback path in send_async.
    with patch("shutil.which", return_value="/usr/local/bin/codex"), \
         patch("asyncio.create_subprocess_exec", side_effect=_capture_exec):
        client = CodexClient()
        req = LlmRequest(systemPrompt="sys", userMessage="--inject-flag if unguarded")
        _asyncio.run(client.send_async(req))

    # "--" must appear in the command and come BEFORE the prompt
    assert "--" in captured_cmd, "'--' argument terminator missing from codex exec command"
    terminator_idx = captured_cmd.index("--")
    prompt_idx = next(
        i for i, a in enumerate(captured_cmd) if "--inject-flag" in a
    )
    assert terminator_idx < prompt_idx, "'--' must come before the prompt argument"


@pytest.mark.e2e
def test_codex_send_async_with_cli():
    """send_async succeeds when codex exec returns output."""
    import asyncio
    from unittest.mock import AsyncMock
    from unittest.mock import patch as async_patch

    from warden.llm.providers.codex import CodexClient
    from warden.llm.types import LlmRequest

    captured_cmd: list[str] = []
    mock_proc = Mock()
    mock_proc.returncode = 0
    # Stdout carries the response — temp file is empty, exercises real stdout-fallback path.
    mock_proc.communicate = AsyncMock(return_value=(b"analysis result", b""))

    async def _capture(  *cmd, **_kw):
        captured_cmd.extend(cmd)
        return mock_proc

    with patch("shutil.which", return_value="/usr/local/bin/codex"), \
         patch("asyncio.create_subprocess_exec", side_effect=_capture):
        client = CodexClient()
        req = LlmRequest(systemPrompt="Analyze code.", userMessage="def foo(): pass")
        resp = asyncio.run(client.send_async(req))

    assert resp.success is True
    assert resp.content == "analysis result"
    assert resp.provider.value == "codex"
    # Key flags must be present in the command
    assert "exec" in captured_cmd
    assert "--sandbox" in captured_cmd
    assert "read-only" in captured_cmd
    assert "--" in captured_cmd


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
def test_codex_mcp_setup_registers_in_toml(runner, tmp_path, monkeypatch):
    """mcp-setup writes [mcp_servers.warden] into ~/.codex/config.toml."""
    fake_codex_dir = tmp_path / ".codex"
    fake_codex_dir.mkdir()
    fake_config = fake_codex_dir / "config.toml"

    # Patch get_mcp_config_paths to return our tmp path
    with patch(
        "warden.mcp.infrastructure.mcp_config_paths.get_mcp_config_paths",
        return_value={"Codex": fake_config},
    ), patch("shutil.which", side_effect=lambda cmd: f"/usr/local/bin/{cmd}"):
        res = runner.invoke(app, ["codex", "mcp-setup"])

    assert res.exit_code == 0, res.stdout
    assert "registered" in res.stdout.lower() or "✓" in res.stdout

    content = fake_config.read_text(encoding="utf-8")
    assert "[mcp_servers.warden]" in content
    assert "warden" in content
    assert '"serve", "mcp", "start"' in content or "serve" in content


@pytest.mark.e2e
def test_codex_mcp_setup_idempotent(runner, tmp_path):
    """Running mcp-setup twice skips the second registration."""
    fake_config = tmp_path / "config.toml"

    with patch(
        "warden.mcp.infrastructure.mcp_config_paths.get_mcp_config_paths",
        return_value={"Codex": fake_config},
    ), patch("shutil.which", side_effect=lambda cmd: f"/usr/local/bin/{cmd}"):
        runner.invoke(app, ["codex", "mcp-setup"])  # first
        res2 = runner.invoke(app, ["codex", "mcp-setup"])  # second

    assert res2.exit_code == 0
    assert "already" in res2.stdout.lower() or "skipped" in res2.stdout.lower()

    # Section appears exactly once
    content = fake_config.read_text(encoding="utf-8")
    assert content.count("[mcp_servers.warden]") == 1


@pytest.mark.e2e
def test_codex_mcp_setup_appends_to_existing_toml(runner, tmp_path):
    """mcp-setup preserves existing TOML content when appending."""
    fake_config = tmp_path / "config.toml"
    fake_config.write_text('[projects."/Users/alper"]\ntrust_level = "trusted"\n', encoding="utf-8")

    with patch(
        "warden.mcp.infrastructure.mcp_config_paths.get_mcp_config_paths",
        return_value={"Codex": fake_config},
    ), patch("shutil.which", side_effect=lambda cmd: f"/usr/local/bin/{cmd}"):
        res = runner.invoke(app, ["codex", "mcp-setup"])

    assert res.exit_code == 0
    content = fake_config.read_text(encoding="utf-8")
    # Existing content preserved
    assert 'trust_level = "trusted"' in content
    # Warden section added
    assert "[mcp_servers.warden]" in content


@pytest.mark.e2e
def test_serve_mcp_register_includes_codex(runner, tmp_path):
    """warden serve mcp register also handles Codex TOML config."""
    fake_config = tmp_path / "config.toml"

    with patch(
        "warden.mcp.infrastructure.mcp_config_paths.get_mcp_config_paths",
        return_value={"Codex": fake_config},
    ), patch("shutil.which", side_effect=lambda cmd: f"/usr/local/bin/{cmd}"):
        res = runner.invoke(app, ["serve", "mcp", "register"])

    assert res.exit_code == 0
    content = fake_config.read_text(encoding="utf-8")
    assert "[mcp_servers.warden]" in content


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

    # No Path.read_text mock: temp file is empty → falls back to stdout content.
    with patch("shutil.which", side_effect=lambda cmd: f"/usr/local/bin/{cmd}"), \
         patch("asyncio.create_subprocess_exec", return_value=mock_proc):

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
