"""
Tests for issue #429: rate limiting wired from LlmConfiguration into GlobalRateLimiter,
and QwenCodeClient rate-limit integration.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from warden.llm.global_rate_limiter import GlobalRateLimiter
from warden.llm.rate_limiter import RateLimitConfig, RateLimiter


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_global_rate_limiter():
    """Ensure a clean singleton for every test."""
    GlobalRateLimiter.reset_instance()
    yield
    GlobalRateLimiter.reset_instance()


# ---------------------------------------------------------------------------
# configure_from_llm_config
# ---------------------------------------------------------------------------


class TestConfigureFromLlmConfig:
    """GlobalRateLimiter.configure_from_llm_config() wires LlmConfiguration limits."""

    def _make_config(self, tpm: int = 1000, rpm: int = 6):
        """Minimal config object with tpm_limit / rpm_limit attributes."""
        cfg = MagicMock()
        cfg.tpm_limit = tpm
        cfg.rpm_limit = rpm
        return cfg

    @pytest.mark.asyncio
    async def test_configure_updates_default_bucket_tpm(self):
        """After configure_from_llm_config, default limiter uses new tpm_limit."""
        limiter = await GlobalRateLimiter.get_instance()
        cfg = self._make_config(tpm=2500, rpm=15)

        limiter.configure_from_llm_config(cfg)

        stats = limiter.get_stats("default")
        assert stats["tpm"] == 2500

    @pytest.mark.asyncio
    async def test_configure_updates_default_bucket_rpm(self):
        """After configure_from_llm_config, default limiter uses new rpm_limit."""
        limiter = await GlobalRateLimiter.get_instance()
        cfg = self._make_config(tpm=5000, rpm=20)

        limiter.configure_from_llm_config(cfg)

        stats = limiter.get_stats("default")
        assert stats["rpm"] == 20

    @pytest.mark.asyncio
    async def test_configure_replaces_default_limiter_object(self):
        """configure_from_llm_config replaces the default RateLimiter instance."""
        limiter = await GlobalRateLimiter.get_instance()
        original = limiter.get_limiter("default")
        cfg = self._make_config(tpm=9999, rpm=42)

        limiter.configure_from_llm_config(cfg)

        new = limiter.get_limiter("default")
        assert new is not original
        assert new.config.tpm == 9999
        assert new.config.rpm == 42

    @pytest.mark.asyncio
    async def test_configure_does_not_change_provider_specific_limits(self):
        """configure_from_llm_config must not alter provider-specific buckets."""
        limiter = await GlobalRateLimiter.get_instance()
        openai_before = limiter.get_stats("openai")
        anthropic_before = limiter.get_stats("anthropic")

        cfg = self._make_config(tpm=100, rpm=2)
        limiter.configure_from_llm_config(cfg)

        # Provider-specific limits unchanged
        assert limiter.get_stats("openai")["tpm"] == openai_before["tpm"]
        assert limiter.get_stats("anthropic")["tpm"] == anthropic_before["tpm"]

    @pytest.mark.asyncio
    async def test_configure_clamps_zero_tpm_to_one(self):
        """Degenerate config (tpm=0) must not create a zero-rate limiter."""
        limiter = await GlobalRateLimiter.get_instance()
        cfg = self._make_config(tpm=0, rpm=0)

        limiter.configure_from_llm_config(cfg)

        stats = limiter.get_stats("default")
        assert stats["tpm"] >= 1
        assert stats["rpm"] >= 1

    @pytest.mark.asyncio
    async def test_configure_free_tier_defaults(self):
        """config.yaml free-tier defaults (tpm=1000, rpm=6) work correctly."""
        limiter = await GlobalRateLimiter.get_instance()
        cfg = self._make_config(tpm=1000, rpm=6)

        limiter.configure_from_llm_config(cfg)

        stats = limiter.get_stats("default")
        assert stats["tpm"] == 1000
        assert stats["rpm"] == 6


# ---------------------------------------------------------------------------
# QwenCodeClient rate limiting
# ---------------------------------------------------------------------------


class TestQwenCodeClientRateLimiting:
    """QwenCodeClient.send_async must call GlobalRateLimiter.acquire before the HTTP call."""

    def _make_provider_config(self):
        cfg = MagicMock()
        cfg.api_key = "test-api-key-1234567890"
        cfg.default_model = "qwen2.5-coder-32b-instruct"
        cfg.endpoint = None
        return cfg

    @pytest.mark.asyncio
    async def test_send_async_calls_rate_limiter_acquire(self):
        """send_async must acquire the 'qwen' rate limiter before every HTTP call."""
        from warden.llm.providers.qwencode import QwenCodeClient
        from warden.llm.types import LlmRequest

        client = QwenCodeClient(self._make_provider_config())

        # Mock GlobalRateLimiter singleton
        mock_limiter = AsyncMock()
        mock_limiter.acquire = AsyncMock()

        # Mock successful HTTP response
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "output": {"text": "Hello"},
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        }

        with patch(
            "warden.llm.global_rate_limiter.GlobalRateLimiter.get_instance",
            new=AsyncMock(return_value=mock_limiter),
        ):
            with patch("httpx.AsyncClient") as mock_http:
                mock_http.return_value.__aenter__ = AsyncMock(return_value=MagicMock(post=AsyncMock(return_value=mock_response)))
                mock_http.return_value.__aexit__ = AsyncMock(return_value=False)

                request = LlmRequest(
                    user_message="test",
                    system_prompt="sys",
                    max_tokens=100,
                )
                await client.send_async(request)

        # Verify rate limiter was called
        mock_limiter.acquire.assert_called_once()
        call_kwargs = mock_limiter.acquire.call_args
        # First positional arg must be "qwen"
        assert call_kwargs[0][0] == "qwen" or call_kwargs[1].get("provider") == "qwen" or (
            len(call_kwargs[0]) > 0 and call_kwargs[0][0] == "qwen"
        )

    @pytest.mark.asyncio
    async def test_send_async_rate_limiter_failure_returns_error_response(self):
        """If GlobalRateLimiter raises, send_async must return an error LlmResponse."""
        from warden.llm.providers.qwencode import QwenCodeClient
        from warden.llm.types import LlmRequest

        client = QwenCodeClient(self._make_provider_config())

        mock_limiter = AsyncMock()
        mock_limiter.acquire = AsyncMock(side_effect=asyncio.TimeoutError("rate limit timeout"))

        with patch(
            "warden.llm.global_rate_limiter.GlobalRateLimiter.get_instance",
            new=AsyncMock(return_value=mock_limiter),
        ):
            request = LlmRequest(
                user_message="test",
                system_prompt="sys",
                max_tokens=100,
            )
            response = await client.send_async(request)

        assert response.success is False
        assert response.error_message is not None

    @pytest.mark.asyncio
    async def test_send_async_passes_token_count_to_acquire(self):
        """Rate limiter acquire must be called with max_tokens + estimated tokens."""
        from warden.llm.providers.qwencode import QwenCodeClient
        from warden.llm.types import LlmRequest

        client = QwenCodeClient(self._make_provider_config())

        acquired_tokens: list[int] = []
        mock_limiter = AsyncMock()

        async def capture_acquire(provider, tokens=0):
            acquired_tokens.append(tokens)

        mock_limiter.acquire = capture_acquire

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "output": {"text": "pong"},
            "usage": {"input_tokens": 5, "output_tokens": 5, "total_tokens": 10},
        }

        with patch(
            "warden.llm.global_rate_limiter.GlobalRateLimiter.get_instance",
            new=AsyncMock(return_value=mock_limiter),
        ):
            with patch("httpx.AsyncClient") as mock_http:
                mock_http.return_value.__aenter__ = AsyncMock(
                    return_value=MagicMock(post=AsyncMock(return_value=mock_response))
                )
                mock_http.return_value.__aexit__ = AsyncMock(return_value=False)

                request = LlmRequest(
                    user_message="ping",
                    system_prompt="sys",
                    max_tokens=200,
                )
                await client.send_async(request)

        assert len(acquired_tokens) == 1
        # tokens = max_tokens + estimated_prompt_tokens (>= max_tokens)
        assert acquired_tokens[0] >= 200


# ---------------------------------------------------------------------------
# load_llm_config_async wires GlobalRateLimiter (integration smoke test)
# ---------------------------------------------------------------------------


class TestLoadLlmConfigAsyncWiresRateLimiter:
    """load_llm_config_async must call configure_from_llm_config on GlobalRateLimiter."""

    @pytest.mark.asyncio
    async def test_load_config_async_configures_global_rate_limiter(self):
        """Smoke test: after load_llm_config_async, GlobalRateLimiter default
        bucket reflects tpm_limit / rpm_limit from the override dict."""
        from warden.llm.config import load_llm_config_async

        config_override = {
            "tpm_limit": 3333,
            "rpm_limit": 11,
        }

        # Patch secrets manager so we don't need real API keys
        mock_secret = MagicMock()
        mock_secret.found = False
        mock_secret.value = None

        async def fake_get_secrets(keys):
            return {k: mock_secret for k in keys}

        with patch("warden.secrets.get_manager") as mock_mgr:
            manager_instance = MagicMock()
            manager_instance.get_secrets_async = fake_get_secrets
            mock_mgr.return_value = manager_instance

            # Prevent live Ollama / claude / codex checks
            with patch("warden.llm.config._check_ollama_availability", return_value=False):
                with patch("warden.llm.config._check_claude_code_availability", return_value=False):
                    with patch("warden.llm.config._check_codex_availability", return_value=False):
                        await load_llm_config_async(config_override)

        limiter = await GlobalRateLimiter.get_instance()
        stats = limiter.get_stats("default")
        assert stats["tpm"] == 3333
        assert stats["rpm"] == 11
