"""
Unit tests for LocalModelManager.

All network calls and subprocess invocations are mocked.
"""

import json
import subprocess
from pathlib import Path
from unittest import mock
from urllib.error import URLError

import pytest
import yaml

from warden.services.local_model_manager import LocalModelManager, _get_ollama_host


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def manager():
    return LocalModelManager(ollama_host="http://localhost:11434")


@pytest.fixture()
def config_file(tmp_path):
    """Write a minimal warden.yaml with Ollama provider and return its path."""

    def _write(content: dict) -> Path:
        p = tmp_path / "warden.yaml"
        with open(p, "w") as f:
            yaml.dump(content, f)
        return p

    return _write


# ---------------------------------------------------------------------------
# _get_ollama_host — env var validation
# ---------------------------------------------------------------------------


def test_get_ollama_host_default(monkeypatch):
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    assert _get_ollama_host() == "http://localhost:11434"


def test_get_ollama_host_custom(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "http://localhost:12345")
    assert _get_ollama_host() == "http://localhost:12345"


def test_get_ollama_host_invalid_scheme(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "ftp://localhost:11434")
    assert _get_ollama_host() == "http://localhost:11434"


# ---------------------------------------------------------------------------
# is_installed
# ---------------------------------------------------------------------------


def test_is_installed_true(manager):
    with mock.patch("shutil.which", return_value="/usr/local/bin/ollama"):
        assert manager.is_installed() is True


def test_is_installed_false(manager):
    with mock.patch("shutil.which", return_value=None):
        assert manager.is_installed() is False


# ---------------------------------------------------------------------------
# install_ollama
# ---------------------------------------------------------------------------


def test_install_ollama_brew_success(manager):
    with (
        mock.patch("platform.system", return_value="Darwin"),
        mock.patch("shutil.which", return_value="/opt/homebrew/bin/brew"),
        mock.patch("subprocess.run", return_value=mock.MagicMock(returncode=0)) as mock_run,
    ):
        assert manager.install_ollama() is True

    mock_run.assert_called_once_with(["brew", "install", "ollama"], timeout=300)


def test_install_ollama_curl_linux(manager):
    with (
        mock.patch("platform.system", return_value="Linux"),
        mock.patch("shutil.which", return_value=None),
        mock.patch("subprocess.run", return_value=mock.MagicMock(returncode=0)) as mock_run,
    ):
        assert manager.install_ollama() is True

    args, _ = mock_run.call_args
    assert args[0] == ["bash", "-c", "curl -fsSL https://ollama.com/install.sh | sh"]


def test_install_ollama_failure(manager):
    with (
        mock.patch("platform.system", return_value="Linux"),
        mock.patch("shutil.which", return_value=None),
        mock.patch("subprocess.run", return_value=mock.MagicMock(returncode=1)),
    ):
        assert manager.install_ollama() is False


def test_install_ollama_timeout(manager):
    with (
        mock.patch("platform.system", return_value="Linux"),
        mock.patch("shutil.which", return_value=None),
        mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=[], timeout=300)),
    ):
        assert manager.install_ollama() is False


# ---------------------------------------------------------------------------
# ensure_ollama_running
# ---------------------------------------------------------------------------


def test_ensure_ollama_running_already_up(manager):
    """If /api/tags responds, returns True without starting anything."""
    with mock.patch("urllib.request.urlopen"):
        assert manager.ensure_ollama_running() is True


def test_ensure_ollama_running_starts_server(manager):
    """When Ollama is down, launch it and wait until it's ready."""
    call_count = 0

    def _urlopen(url, timeout=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise URLError("connection refused")
        # Simulate server becoming ready on second check
        mock_resp = mock.MagicMock()
        mock_resp.read.return_value = json.dumps({"models": []}).encode()
        return mock_resp

    with (
        mock.patch("urllib.request.urlopen", side_effect=_urlopen),
        mock.patch("shutil.which", return_value="/usr/local/bin/ollama"),
        mock.patch("subprocess.Popen") as mock_popen,
        mock.patch("time.sleep"),
    ):
        result = manager.ensure_ollama_running()

    assert result is True
    mock_popen.assert_called_once_with(
        ["ollama", "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def test_ensure_ollama_running_no_binary(manager):
    """When Ollama binary is missing and server is down, return False."""
    with (
        mock.patch("urllib.request.urlopen", side_effect=URLError("refused")),
        mock.patch("shutil.which", return_value=None),
    ):
        assert manager.ensure_ollama_running() is False


def test_ensure_ollama_running_timeout(manager):
    """If server never becomes ready within retries, return False."""
    with (
        mock.patch("urllib.request.urlopen", side_effect=URLError("refused")),
        mock.patch("shutil.which", return_value="/usr/local/bin/ollama"),
        mock.patch("subprocess.Popen"),
        mock.patch("time.sleep"),
        mock.patch(
            "warden.services.local_model_manager._HEALTH_CHECK_RETRIES",
            2,
        ),
    ):
        assert manager.ensure_ollama_running() is False


# ---------------------------------------------------------------------------
# is_model_available
# ---------------------------------------------------------------------------


def _mock_tags_response(models: list[str]):
    resp = mock.MagicMock()
    resp.read.return_value = json.dumps({"models": [{"name": m} for m in models]}).encode()
    return resp


def test_is_model_available_true(manager):
    with mock.patch("urllib.request.urlopen", return_value=_mock_tags_response(["qwen2.5-coder:7b", "llama3:8b"])):
        assert manager.is_model_available("qwen2.5-coder:7b") is True


def test_is_model_available_false(manager):
    with mock.patch("urllib.request.urlopen", return_value=_mock_tags_response(["llama3:8b"])):
        assert manager.is_model_available("qwen2.5-coder:7b") is False


def test_is_model_available_ollama_down(manager):
    with mock.patch("urllib.request.urlopen", side_effect=URLError("refused")):
        assert manager.is_model_available("qwen2.5-coder:7b") is False


# ---------------------------------------------------------------------------
# pull_model
# ---------------------------------------------------------------------------


def test_pull_model_success(manager):
    with (
        mock.patch("shutil.which", return_value="/usr/bin/ollama"),
        mock.patch("subprocess.run", return_value=mock.MagicMock(returncode=0)) as mock_run,
    ):
        assert manager.pull_model("qwen2.5-coder:7b", show_progress=False) is True

    mock_run.assert_called_once_with(
        ["ollama", "pull", "qwen2.5-coder:7b"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=600,
    )


def test_pull_model_failure(manager):
    with (
        mock.patch("shutil.which", return_value="/usr/bin/ollama"),
        mock.patch("subprocess.run", return_value=mock.MagicMock(returncode=1)),
    ):
        assert manager.pull_model("nonexistent:model", show_progress=False) is False


def test_pull_model_timeout(manager):
    with (
        mock.patch("shutil.which", return_value="/usr/bin/ollama"),
        mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=[], timeout=600)),
    ):
        assert manager.pull_model("huge:model", show_progress=False) is False


def test_pull_model_no_binary(manager):
    with mock.patch("shutil.which", return_value=None):
        assert manager.pull_model("qwen2.5-coder:7b") is False


def test_pull_model_show_progress_uses_stdout(manager):
    """show_progress=True → stdout/stderr are None (inherited)."""
    with (
        mock.patch("shutil.which", return_value="/usr/bin/ollama"),
        mock.patch("subprocess.run", return_value=mock.MagicMock(returncode=0)) as mock_run,
    ):
        manager.pull_model("qwen2.5-coder:7b", show_progress=True)

    _, kwargs = mock_run.call_args
    assert kwargs.get("stdout") is None
    assert kwargs.get("stderr") is None


# ---------------------------------------------------------------------------
# get_configured_models — ollama provider
# ---------------------------------------------------------------------------


def test_get_configured_models_ollama_provider(config_file):
    cfg = config_file(
        {
            "llm": {
                "provider": "ollama",
                "model": "qwen2.5-coder:7b",
                "fast_model": "qwen2.5-coder:3b",
            }
        }
    )
    manager = LocalModelManager()
    models = manager.get_configured_models(cfg)
    assert "qwen2.5-coder:7b" in models
    assert "qwen2.5-coder:3b" in models
    assert len(models) == 2


def test_get_configured_models_deduplicates(config_file):
    cfg = config_file(
        {
            "llm": {
                "provider": "ollama",
                "model": "qwen2.5-coder:7b",
                "fast_model": "qwen2.5-coder:7b",  # same as smart
            }
        }
    )
    manager = LocalModelManager()
    models = manager.get_configured_models(cfg)
    assert models.count("qwen2.5-coder:7b") == 1


def test_get_configured_models_hybrid_mode(config_file):
    """Cloud provider + use_local_llm=True → only fast_model returned."""
    cfg = config_file(
        {
            "llm": {
                "provider": "groq",
                "model": "llama-3.3-70b",
                "fast_model": "qwen2.5-coder:3b",
                "use_local_llm": True,
            }
        }
    )
    manager = LocalModelManager()
    models = manager.get_configured_models(cfg)
    assert "qwen2.5-coder:3b" in models
    assert "llama-3.3-70b" not in models


def test_get_configured_models_cloud_only(config_file):
    """Cloud provider without use_local_llm → empty list."""
    cfg = config_file({"llm": {"provider": "groq", "model": "llama-3.3-70b"}})
    manager = LocalModelManager()
    assert manager.get_configured_models(cfg) == []


def test_get_configured_models_no_config(tmp_path):
    """Missing config file → empty list, no exception."""
    manager = LocalModelManager()
    assert manager.get_configured_models(tmp_path / "nonexistent.yaml") == []


def test_get_configured_models_empty_config(tmp_path):
    cfg = tmp_path / "warden.yaml"
    cfg.write_text("")
    manager = LocalModelManager()
    assert manager.get_configured_models(cfg) == []
