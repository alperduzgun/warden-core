"""Tests for ModelHealer strategy."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from warden.self_healing.models import ErrorCategory
from warden.self_healing.strategies.model_healer import (
    ModelHealer,
    _extract_model_name,
    _try_ollama_pull,
)


class ModelNotFoundError(Exception):
    """Test-only exception matching Ollama's error class name."""

    pass


class TestModelHealer:
    def setup_method(self):
        self.healer = ModelHealer()

    def test_name(self):
        assert self.healer.name == "model_healer"

    def test_handles(self):
        assert ErrorCategory.MODEL_NOT_FOUND in self.healer.handles

    def test_priority(self):
        assert self.healer.priority == 200

    @pytest.mark.asyncio
    async def test_can_heal_with_model_name(self):
        err = ModelNotFoundError("model 'qwen2.5-coder:3b' not found")
        assert await self.healer.can_heal(err, ErrorCategory.MODEL_NOT_FOUND) is True

    @pytest.mark.asyncio
    async def test_can_heal_no_model_name(self):
        err = Exception("some generic error")
        assert await self.healer.can_heal(err, ErrorCategory.MODEL_NOT_FOUND) is False

    @pytest.mark.asyncio
    async def test_heal_success(self):
        err = ModelNotFoundError("model 'qwen2.5-coder:3b' not found")
        with patch(
            "warden.self_healing.strategies.model_healer._try_ollama_pull",
            return_value=True,
        ):
            result = await self.healer.heal(err)
        assert result.fixed is True
        assert "qwen2.5-coder:3b" in result.models_pulled
        assert result.strategy_used == "model_healer"

    @pytest.mark.asyncio
    async def test_heal_failure(self):
        err = ModelNotFoundError("model 'big-model:70b' not found")
        with patch(
            "warden.self_healing.strategies.model_healer._try_ollama_pull",
            return_value=False,
        ):
            result = await self.healer.heal(err)
        assert result.fixed is False
        assert "Failed to pull" in result.diagnosis

    @pytest.mark.asyncio
    async def test_heal_with_model_attribute(self):
        err = Exception("model error")
        err.model = "custom-model:latest"
        with patch(
            "warden.self_healing.strategies.model_healer._try_ollama_pull",
            return_value=True,
        ):
            result = await self.healer.heal(err)
        assert result.fixed is True
        assert "custom-model:latest" in result.models_pulled


class TestExtractModelName:
    def test_model_not_found_pattern(self):
        err = Exception("model 'qwen:3b' not found")
        assert _extract_model_name(err) == "qwen:3b"

    def test_unknown_model_pattern(self):
        err = Exception("unknown model: llama3:8b")
        assert _extract_model_name(err) == "llama3:8b"

    def test_model_attribute(self):
        err = Exception("error")
        err.model = "phi3:mini"
        assert _extract_model_name(err) == "phi3:mini"

    def test_no_model_found(self):
        err = Exception("some random error")
        assert _extract_model_name(err) is None


class TestTryOllamaPull:
    def test_rejects_unsafe_names(self):
        assert _try_ollama_pull("rm -rf /") is False
        assert _try_ollama_pull("model; echo pwned") is False

    @patch("subprocess.run")
    def test_pull_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        assert _try_ollama_pull("qwen:3b") is True

    @patch("subprocess.run")
    def test_pull_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stderr=b"error")
        assert _try_ollama_pull("nonexistent:99b") is False

    @patch("subprocess.run", side_effect=FileNotFoundError)
    def test_ollama_not_installed(self, mock_run):
        assert _try_ollama_pull("qwen:3b") is False

    @patch("subprocess.run", side_effect=Exception("unexpected"))
    def test_pull_exception(self, mock_run):
        assert _try_ollama_pull("model") is False

    @patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="ollama", timeout=60))
    def test_ollama_pull_timeout_explicit_catch(self, mock_run):
        """TimeoutExpired is caught explicitly and returns False."""
        assert _try_ollama_pull("big-model:70b") is False

    def test_model_name_leading_dash_rejected(self):
        """Model names starting with dash (flag injection) are rejected."""
        assert _try_ollama_pull("--malicious") is False
        assert _try_ollama_pull("-v") is False

    def test_model_name_path_traversal_rejected(self):
        """Model names containing '..' (path traversal) are rejected."""
        assert _try_ollama_pull("../../etc/passwd") is False
        assert _try_ollama_pull("model/../secret") is False
