"""Tests for ImportHealer strategy."""

from __future__ import annotations

import subprocess
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from warden.self_healing.models import ErrorCategory
from warden.self_healing.strategies.import_healer import (
    IMPORT_TO_PIP,
    ImportHealer,
    _ask_llm_pip_name,
    _try_pip_install,
)


class TestImportHealer:
    def setup_method(self):
        self.healer = ImportHealer()

    def test_name(self):
        assert self.healer.name == "import_healer"

    def test_handles(self):
        assert ErrorCategory.IMPORT_ERROR in self.healer.handles
        assert ErrorCategory.MODULE_NOT_FOUND in self.healer.handles

    def test_priority(self):
        assert self.healer.priority == 200

    @pytest.mark.asyncio
    async def test_can_heal_with_extractable_module(self):
        err = ModuleNotFoundError("No module named 'tiktoken'")
        assert await self.healer.can_heal(err, ErrorCategory.MODULE_NOT_FOUND) is True

    @pytest.mark.asyncio
    async def test_can_heal_no_module_name(self):
        err = ImportError("something weird happened")
        assert await self.healer.can_heal(err, ErrorCategory.IMPORT_ERROR) is False

    @pytest.mark.asyncio
    async def test_heal_success(self):
        err = ModuleNotFoundError("No module named 'tiktoken'")
        with patch(
            "warden.self_healing.strategies.import_healer._try_pip_install",
            return_value=True,
        ):
            result = await self.healer.heal(err)
        assert result.fixed is True
        assert "tiktoken" in result.packages_installed
        assert result.strategy_used == "import_healer"

    @pytest.mark.asyncio
    async def test_heal_with_pip_mapping(self):
        err = ModuleNotFoundError("No module named 'yaml'")
        with patch(
            "warden.self_healing.strategies.import_healer._try_pip_install",
            return_value=True,
        ) as mock:
            result = await self.healer.heal(err)
        mock.assert_called_once_with("pyyaml")
        assert result.fixed is True

    @pytest.mark.asyncio
    async def test_heal_failure(self):
        err = ModuleNotFoundError("No module named 'nonexistent'")
        with patch(
            "warden.self_healing.strategies.import_healer._try_pip_install",
            return_value=False,
        ):
            result = await self.healer.heal(err)
        assert result.fixed is False
        assert "Failed to install" in result.diagnosis


class TestTryPipInstall:
    def test_rejects_unsafe_names(self):
        assert _try_pip_install("rm -rf /") is False
        assert _try_pip_install("pkg; echo pwned") is False
        assert _try_pip_install("") is False

    def test_accepts_valid_names(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            assert _try_pip_install("tiktoken") is True

    @patch("subprocess.run")
    def test_install_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stderr=b"error")
        assert _try_pip_install("nonexistent-pkg") is False

    @patch("subprocess.run", side_effect=Exception("subprocess failed"))
    def test_install_exception(self, mock_run):
        assert _try_pip_install("bad-pkg") is False

    @patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="pip", timeout=120))
    def test_pip_install_timeout_explicit_catch(self, mock_run):
        """TimeoutExpired is caught explicitly and returns False."""
        assert _try_pip_install("slow-pkg") is False

    def test_pip_install_whitespace_only_rejected(self):
        """Whitespace-only package names are rejected."""
        assert _try_pip_install("   ") is False
        assert _try_pip_install("") is False


class TestLlmPipNameResolution:
    @pytest.mark.asyncio
    async def test_llm_resolves_unknown_module(self):
        """LLM resolves pip name for a module not in IMPORT_TO_PIP."""
        mock_response = MagicMock()
        mock_response.content = "pyyaml"

        mock_client = AsyncMock()
        mock_client.is_available_async.return_value = True
        mock_client.complete_async.return_value = mock_response

        with patch("warden.llm.factory.create_client", return_value=mock_client):
            result = await _ask_llm_pip_name("yaml_utils")

        assert result == "pyyaml"

    @pytest.mark.asyncio
    async def test_llm_returns_unknown(self):
        """LLM responds UNKNOWN → returns None."""
        mock_response = MagicMock()
        mock_response.content = "UNKNOWN"

        mock_client = AsyncMock()
        mock_client.is_available_async.return_value = True
        mock_client.complete_async.return_value = mock_response

        with patch("warden.llm.factory.create_client", return_value=mock_client):
            result = await _ask_llm_pip_name("totally_fake_module")

        assert result is None

    @pytest.mark.asyncio
    async def test_llm_unavailable_falls_back(self):
        """LLM unavailable → returns None, no crash."""
        mock_client = AsyncMock()
        mock_client.is_available_async.return_value = False

        with patch("warden.llm.factory.create_client", return_value=mock_client):
            result = await _ask_llm_pip_name("some_module")

        assert result is None

    @pytest.mark.asyncio
    async def test_llm_rejects_unsafe_response(self):
        """LLM returns something with shell chars → rejected."""
        mock_response = MagicMock()
        mock_response.content = "rm -rf /"

        mock_client = AsyncMock()
        mock_client.is_available_async.return_value = True
        mock_client.complete_async.return_value = mock_response

        with patch("warden.llm.factory.create_client", return_value=mock_client):
            result = await _ask_llm_pip_name("evil_module")

        assert result is None

    @pytest.mark.asyncio
    async def test_heal_uses_llm_when_not_in_static_dict(self):
        """ImportHealer falls back to LLM for modules not in IMPORT_TO_PIP."""
        healer = ImportHealer()
        err = ModuleNotFoundError("No module named 'some_obscure_lib'")

        mock_response = MagicMock()
        mock_response.content = "some-obscure-lib"

        mock_client = AsyncMock()
        mock_client.is_available_async.return_value = True
        mock_client.complete_async.return_value = mock_response

        with (
            patch("warden.llm.factory.create_client", return_value=mock_client),
            patch(
                "warden.self_healing.strategies.import_healer._try_pip_install",
                return_value=True,
            ) as mock_install,
        ):
            result = await healer.heal(err)

        # LLM resolved the pip name
        mock_install.assert_called_once_with("some-obscure-lib")
        assert result.fixed is True
        assert "some-obscure-lib" in result.packages_installed

    @pytest.mark.asyncio
    async def test_heal_skips_llm_for_static_dict_hit(self):
        """ImportHealer does NOT call LLM when module is in IMPORT_TO_PIP."""
        healer = ImportHealer()
        err = ModuleNotFoundError("No module named 'yaml'")

        with (
            patch(
                "warden.self_healing.strategies.import_healer._ask_llm_pip_name",
            ) as mock_llm,
            patch(
                "warden.self_healing.strategies.import_healer._try_pip_install",
                return_value=True,
            ) as mock_install,
        ):
            result = await healer.heal(err)

        # Static dict hit → LLM never called
        mock_llm.assert_not_called()
        mock_install.assert_called_once_with("pyyaml")
        assert result.fixed is True


class TestImportToPipMapping:
    def test_common_mappings_exist(self):
        assert IMPORT_TO_PIP["yaml"] == "pyyaml"
        assert IMPORT_TO_PIP["cv2"] == "opencv-python"
        assert IMPORT_TO_PIP["PIL"] == "Pillow"
        assert IMPORT_TO_PIP["sklearn"] == "scikit-learn"
        assert IMPORT_TO_PIP["bs4"] == "beautifulsoup4"

    def test_all_values_are_strings(self):
        for key, value in IMPORT_TO_PIP.items():
            assert isinstance(key, str)
            assert isinstance(value, str)
