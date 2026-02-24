"""
Tests for scan.py preflight check logic:
  - _needs_ollama()
  - _preflight_ollama_check()
"""

from pathlib import Path
from unittest import mock

import pytest
import yaml
from rich.console import Console

from warden.cli.commands.scan import _needs_ollama, _preflight_ollama_check


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def ollama_config(tmp_path, monkeypatch):
    """Create a warden.yaml with Ollama provider and chdir to tmp_path."""
    cfg = tmp_path / "warden.yaml"
    with open(cfg, "w") as f:
        yaml.dump(
            {
                "llm": {
                    "provider": "ollama",
                    "model": "qwen2.5-coder:7b",
                    "fast_model": "qwen2.5-coder:3b",
                }
            },
            f,
        )
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture()
def cloud_config(tmp_path, monkeypatch):
    """Create a warden.yaml with a cloud provider and chdir to tmp_path."""
    cfg = tmp_path / "warden.yaml"
    with open(cfg, "w") as f:
        yaml.dump({"llm": {"provider": "groq", "model": "llama-3.3-70b"}}, f)
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture()
def null_console():
    return Console(quiet=True)


# ---------------------------------------------------------------------------
# _needs_ollama
# ---------------------------------------------------------------------------


def test_needs_ollama_true(ollama_config):
    assert _needs_ollama() is True


def test_needs_ollama_false_cloud(cloud_config):
    assert _needs_ollama() is False


def test_needs_ollama_false_env_override(ollama_config, monkeypatch):
    """WARDEN_LLM_PROVIDER env var pointing to cloud overrides config."""
    monkeypatch.setenv("WARDEN_LLM_PROVIDER", "groq")
    assert _needs_ollama() is False


def test_needs_ollama_false_no_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert _needs_ollama() is False


def test_needs_ollama_hybrid_mode(tmp_path, monkeypatch):
    """Cloud provider + use_local_llm → needs Ollama."""
    cfg = tmp_path / "warden.yaml"
    with open(cfg, "w") as f:
        yaml.dump(
            {
                "llm": {
                    "provider": "groq",
                    "model": "llama-3.3-70b",
                    "use_local_llm": True,
                    "fast_model": "qwen2.5-coder:3b",
                }
            },
            f,
        )
    monkeypatch.chdir(tmp_path)
    assert _needs_ollama() is True


# ---------------------------------------------------------------------------
# _preflight_ollama_check
# ---------------------------------------------------------------------------


def test_preflight_skipped_for_cloud_provider(cloud_config, null_console):
    """No Ollama needed → preflight passes immediately without any checks."""
    with mock.patch("warden.services.local_model_manager.LocalModelManager.ensure_ollama_running") as mock_ensure:
        result = _preflight_ollama_check(null_console)

    assert result is True
    mock_ensure.assert_not_called()


def test_preflight_ollama_not_installed(ollama_config, null_console):
    """Ollama binary missing → returns False with install hint (not 'run ollama serve')."""
    with (
        mock.patch(
            "warden.services.local_model_manager.LocalModelManager.is_installed",
            return_value=False,
        ),
        mock.patch(
            "warden.services.local_model_manager.LocalModelManager.ensure_ollama_running",
        ) as mock_ensure,
    ):
        result = _preflight_ollama_check(null_console)

    assert result is False
    # ensure_ollama_running must NOT be called when binary is missing
    mock_ensure.assert_not_called()


def test_preflight_ollama_not_running_fails(ollama_config, null_console):
    """Ollama installed but server can't start → returns False."""
    with (
        mock.patch(
            "warden.services.local_model_manager.LocalModelManager.is_installed",
            return_value=True,
        ),
        mock.patch(
            "warden.services.local_model_manager.LocalModelManager.ensure_ollama_running",
            return_value=False,
        ),
    ):
        result = _preflight_ollama_check(null_console)

    assert result is False


def test_preflight_all_models_present(ollama_config, null_console):
    """All models available → returns True without pulling."""
    with (
        mock.patch(
            "warden.services.local_model_manager.LocalModelManager.is_installed",
            return_value=True,
        ),
        mock.patch(
            "warden.services.local_model_manager.LocalModelManager.ensure_ollama_running",
            return_value=True,
        ),
        mock.patch(
            "warden.services.local_model_manager.LocalModelManager.is_model_available",
            return_value=True,
        ),
        mock.patch(
            "warden.services.local_model_manager.LocalModelManager.pull_model",
        ) as mock_pull,
    ):
        result = _preflight_ollama_check(null_console)

    assert result is True
    mock_pull.assert_not_called()


def test_preflight_model_missing_pulls_and_continues(ollama_config, null_console):
    """Missing model → pull is called → returns True on success."""
    with (
        mock.patch(
            "warden.services.local_model_manager.LocalModelManager.is_installed",
            return_value=True,
        ),
        mock.patch(
            "warden.services.local_model_manager.LocalModelManager.ensure_ollama_running",
            return_value=True,
        ),
        mock.patch(
            "warden.services.local_model_manager.LocalModelManager.is_model_available",
            return_value=False,
        ),
        mock.patch(
            "warden.services.local_model_manager.LocalModelManager.pull_model",
            return_value=True,
        ) as mock_pull,
    ):
        result = _preflight_ollama_check(null_console)

    assert result is True
    assert mock_pull.call_count >= 1


def test_preflight_pull_failure_returns_false(ollama_config, null_console):
    """If pull fails, preflight returns False to abort the scan."""
    with (
        mock.patch(
            "warden.services.local_model_manager.LocalModelManager.is_installed",
            return_value=True,
        ),
        mock.patch(
            "warden.services.local_model_manager.LocalModelManager.ensure_ollama_running",
            return_value=True,
        ),
        mock.patch(
            "warden.services.local_model_manager.LocalModelManager.is_model_available",
            return_value=False,
        ),
        mock.patch(
            "warden.services.local_model_manager.LocalModelManager.pull_model",
            return_value=False,
        ),
    ):
        result = _preflight_ollama_check(null_console)

    assert result is False
