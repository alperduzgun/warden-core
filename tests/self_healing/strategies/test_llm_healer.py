"""Tests for LLMHealer strategy."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from warden.self_healing.models import ErrorCategory
from warden.self_healing.strategies.llm_healer import (
    LLMHealer,
    _ask_llm_diagnosis,
    _parse_llm_fix,
)


class TestLLMHealer:
    def setup_method(self):
        self.healer = LLMHealer()

    def test_name(self):
        assert self.healer.name == "llm_healer"

    def test_handles(self):
        assert ErrorCategory.UNKNOWN in self.healer.handles

    def test_priority(self):
        assert self.healer.priority == 50

    @pytest.mark.asyncio
    async def test_can_heal_always_true(self):
        assert await self.healer.can_heal(Exception(), ErrorCategory.UNKNOWN) is True

    @pytest.mark.asyncio
    async def test_heal_with_install_suggestion(self):
        with (
            patch(
                "warden.self_healing.strategies.llm_healer._ask_llm_diagnosis",
                return_value="INSTALL: some-pkg",
            ),
            patch(
                "warden.self_healing.strategies.llm_healer._try_pip_install",
                return_value=True,
            ),
        ):
            result = await self.healer.heal(RuntimeError("test"))
        assert result.fixed is True
        assert "some-pkg" in result.packages_installed

    @pytest.mark.asyncio
    async def test_heal_diagnosis_only(self):
        with patch(
            "warden.self_healing.strategies.llm_healer._ask_llm_diagnosis",
            return_value="The error is caused by a corrupted database.",
        ):
            result = await self.healer.heal(RuntimeError("test"))
        assert result.fixed is False
        assert "corrupted database" in result.diagnosis

    @pytest.mark.asyncio
    async def test_heal_llm_unavailable(self):
        with patch(
            "warden.self_healing.strategies.llm_healer._ask_llm_diagnosis",
            return_value=None,
        ):
            result = await self.healer.heal(RuntimeError("unknown failure"))
        assert result.fixed is False
        assert "RuntimeError" in result.diagnosis


class TestAskLlmDiagnosis:
    @pytest.mark.asyncio
    async def test_llm_called_with_correct_prompt(self):
        mock_response = MagicMock()
        mock_response.content = "INSTALL: test-pkg"

        mock_client = AsyncMock()
        mock_client.is_available_async.return_value = True
        mock_client.complete_async.return_value = mock_response

        with patch("warden.llm.factory.create_client", return_value=mock_client):
            result = await _ask_llm_diagnosis(
                RuntimeError("test error"), "traceback text", "test context"
            )

        assert result == "INSTALL: test-pkg"
        mock_client.complete_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_llm_unavailable_returns_none(self):
        mock_client = AsyncMock()
        mock_client.is_available_async.return_value = False

        with patch("warden.llm.factory.create_client", return_value=mock_client):
            result = await _ask_llm_diagnosis(RuntimeError("test"), "tb", "ctx")

        assert result is None

    @pytest.mark.asyncio
    async def test_llm_exception_returns_none(self):
        with patch(
            "warden.llm.factory.create_client",
            side_effect=Exception("LLM factory failed"),
        ):
            result = await _ask_llm_diagnosis(RuntimeError("test"), "tb", "ctx")

        assert result is None


class TestParseLlmFix:
    def test_install_directive(self):
        assert _parse_llm_fix("INSTALL: tiktoken") == ["tiktoken"]

    def test_multiple_install_directives(self):
        assert _parse_llm_fix("INSTALL: tiktoken\nINSTALL: sentence-transformers") == [
            "tiktoken",
            "sentence-transformers",
        ]

    def test_pip_install_in_text(self):
        assert _parse_llm_fix("You should run: pip install tiktoken") == ["tiktoken"]

    def test_both_formats(self):
        result = _parse_llm_fix("INSTALL: tiktoken\nAlternatively, pip install pyyaml")
        assert "tiktoken" in result
        assert "pyyaml" in result

    def test_no_packages_found(self):
        assert _parse_llm_fix("The error is caused by a misconfiguration.") == []

    def test_deduplicates_packages(self):
        assert _parse_llm_fix("INSTALL: tiktoken\npip install tiktoken") == ["tiktoken"]

    def test_install_with_extras(self):
        assert _parse_llm_fix("INSTALL: transformers[torch]") == ["transformers[torch]"]

    def test_parse_llm_fix_no_redos(self):
        """Large input with many tokens should not cause regex CPU hang."""
        # 50 space-separated tokens that look like package names
        payload = "INSTALL: " + " ".join(f"pkg{i}" for i in range(50))
        start = time.monotonic()
        result = _parse_llm_fix(payload)
        elapsed_ms = (time.monotonic() - start) * 1000
        # Should complete well under 100ms even on slow machines
        assert elapsed_ms < 100, f"Regex took {elapsed_ms:.1f}ms (potential ReDoS)"
        # With the {0,2} limit, should only capture up to 3 tokens
        assert len(result) >= 1
