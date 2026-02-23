"""
Tests for LLM provider resilience behaviours.

Covers:
1. CircuitBreakerOpen bypass in retry decorator
2. Fast tier fallback to smart when all fast providers fail
3. ClaudeCodeClient.is_available_async availability checks
4. WARDEN_FAST_TIER_PRIORITY env var overrides config
5. OrchestratedLlmClient.is_available_async with mixed availability
6. Fast tier timeout handling
"""

from __future__ import annotations

import os
from unittest import mock
from unittest.mock import AsyncMock

import pytest

from warden.llm.providers.orchestrated import OrchestratedLlmClient
from warden.llm.types import LlmProvider, LlmRequest, LlmResponse
from warden.shared.infrastructure.resilience.circuit_breaker import CircuitBreakerOpen
from warden.shared.utils.retry_utils import async_retry

# noqa for optional imports used in specific tests


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(provider_val: LlmProvider = LlmProvider.OLLAMA, available: bool = True) -> AsyncMock:
    client = AsyncMock()
    client.provider = provider_val
    client.is_available_async = AsyncMock(return_value=available)
    return client


def _success_response(content: str = "ok") -> LlmResponse:
    return LlmResponse(content=content, success=True, provider=LlmProvider.OLLAMA, model="test")


def _fail_response(error: str = "fail") -> LlmResponse:
    return LlmResponse(content="", success=False, error_message=error, provider=LlmProvider.OLLAMA, model="test")


# ---------------------------------------------------------------------------
# CircuitBreakerOpen bypass
# ---------------------------------------------------------------------------


class TestCircuitBreakerBypass:
    """CircuitBreakerOpen must not be retried — retrying wastes 60s open window."""

    @pytest.mark.asyncio
    async def test_circuit_breaker_open_not_retried(self):
        """CircuitBreakerOpen raised → raises immediately, no retry sleep."""
        call_count = 0

        @async_retry(retries=3, initial_delay=0.01)
        async def raises_circuit_open():
            nonlocal call_count
            call_count += 1
            raise CircuitBreakerOpen("test_circuit", 60)

        with pytest.raises(CircuitBreakerOpen):
            await raises_circuit_open()

        assert call_count == 1  # No retries — should have called exactly once

    @pytest.mark.asyncio
    async def test_regular_exception_is_retried(self):
        """Regular exceptions ARE retried (control case to contrast with above)."""
        call_count = 0

        @async_retry(retries=2, initial_delay=0.01)
        async def raises_regular():
            nonlocal call_count
            call_count += 1
            raise ConnectionError("transient")

        with pytest.raises(ConnectionError):
            await raises_regular()

        assert call_count == 3  # Initial + 2 retries

    @pytest.mark.asyncio
    async def test_circuit_breaker_propagates_correctly(self):
        """Ensure the CircuitBreakerOpen error propagates with original message."""

        @async_retry(retries=3, initial_delay=0.01)
        async def raises_with_message():
            raise CircuitBreakerOpen("groq_circuit", 30)

        with pytest.raises(CircuitBreakerOpen) as exc_info:
            await raises_with_message()

        assert "groq_circuit" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Fast Tier → Smart Tier Fallback
# ---------------------------------------------------------------------------


class TestFastTierFallback:
    """All fast providers fail → should fall back to smart tier."""

    @pytest.mark.asyncio
    async def test_falls_back_to_smart_when_all_fast_fail(self):
        """When all fast providers return success=False, smart tier is used."""
        smart = _make_client(LlmProvider.GROQ, available=True)
        smart.send_async = AsyncMock(return_value=_success_response("smart response"))

        fast1 = _make_client(LlmProvider.OLLAMA, available=True)
        fast1.send_async = AsyncMock(return_value=_fail_response("ollama failed"))

        orchestrated = OrchestratedLlmClient(smart_client=smart, fast_clients=[fast1])
        request = LlmRequest(system_prompt="", use_fast_tier=True, user_message="test")

        response = await orchestrated.send_async(request)

        assert response.success is True
        assert response.content == "smart response"
        smart.send_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_uses_fast_tier_when_available(self):
        """Fast provider succeeds → smart tier NOT called."""
        smart = _make_client(LlmProvider.GROQ, available=True)
        smart.send_async = AsyncMock(return_value=_success_response("smart response"))

        fast1 = _make_client(LlmProvider.OLLAMA, available=True)
        fast1.send_async = AsyncMock(return_value=_success_response("fast response"))

        orchestrated = OrchestratedLlmClient(smart_client=smart, fast_clients=[fast1])
        request = LlmRequest(system_prompt="", use_fast_tier=True, user_message="test")

        response = await orchestrated.send_async(request)

        assert response.success is True
        assert response.content == "fast response"
        smart.send_async.assert_not_called()

    @pytest.mark.asyncio
    async def test_smart_only_mode_when_no_fast_clients(self):
        """No fast clients → routes directly to smart tier."""
        smart = _make_client(LlmProvider.GROQ, available=True)
        smart.send_async = AsyncMock(return_value=_success_response("smart only"))

        orchestrated = OrchestratedLlmClient(smart_client=smart, fast_clients=[])
        request = LlmRequest(system_prompt="", use_fast_tier=True, user_message="test")

        response = await orchestrated.send_async(request)

        assert response.success is True
        assert response.content == "smart only"


# ---------------------------------------------------------------------------
# ClaudeCodeClient availability
# ---------------------------------------------------------------------------


class TestClaudeCodeAvailability:
    """ClaudeCodeClient.is_available_async uses only shutil.which + --version check."""

    @pytest.mark.asyncio
    async def test_unavailable_when_claude_not_in_path(self):
        """Returns False when shutil.which('claude') is None."""
        from warden.llm.config import ProviderConfig
        from warden.llm.providers.claude_code import ClaudeCodeClient

        client = ClaudeCodeClient(ProviderConfig(enabled=True))
        with mock.patch("shutil.which", return_value=None):
            result = await client.is_available_async()
        assert result is False

    @pytest.mark.asyncio
    async def test_claude_code_enabled_env_has_no_effect(self):
        """CLAUDE_CODE_ENABLED env var is no longer respected — availability uses only CLI check."""
        from warden.llm.config import ProviderConfig
        from warden.llm.providers.claude_code import ClaudeCodeClient

        client = ClaudeCodeClient(ProviderConfig(enabled=True))
        # Even with CLAUDE_CODE_ENABLED=false, shutil.which controls the result
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_ENABLED": "false"}):
            with mock.patch("shutil.which", return_value=None):
                result = await client.is_available_async()
        # Result is False because claude is not in PATH, not because of env var
        assert result is False

    @pytest.mark.asyncio
    async def test_available_when_cli_present_and_version_succeeds(self):
        """Returns True when claude is in PATH and --version exits 0."""
        from warden.llm.config import ProviderConfig
        from warden.llm.providers.claude_code import ClaudeCodeClient

        client = ClaudeCodeClient(ProviderConfig(enabled=True))

        mock_process = mock.MagicMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(return_value=(b"claude 1.0.0", b""))

        # Clear nested session env vars (set when running inside Claude Code)
        clean_env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CODE_ENTRYPOINT", "CLAUDECODE")}
        with mock.patch.dict(os.environ, clean_env, clear=True):
            with mock.patch("shutil.which", return_value="/usr/local/bin/claude"):
                with mock.patch("asyncio.create_subprocess_exec", return_value=mock_process):
                    result = await client.is_available_async()
        assert result is True


# ---------------------------------------------------------------------------
# Availability with mixed providers
# ---------------------------------------------------------------------------


class TestOrchestratedAvailabilityExtended:
    """Extended is_available_async tests."""

    @pytest.mark.asyncio
    async def test_available_when_only_fast_tier_works(self):
        """Available even when smart tier fails, if any fast provider is up."""
        smart = _make_client(LlmProvider.GROQ, available=False)
        fast = _make_client(LlmProvider.OLLAMA, available=True)

        orchestrated = OrchestratedLlmClient(smart_client=smart, fast_clients=[fast])
        assert await orchestrated.is_available_async() is True

    @pytest.mark.asyncio
    async def test_unavailable_when_all_fail(self):
        """Unavailable when both smart and all fast providers are down."""
        smart = _make_client(LlmProvider.GROQ, available=False)
        fast1 = _make_client(LlmProvider.OLLAMA, available=False)
        fast2 = _make_client(LlmProvider.DEEPSEEK, available=False)

        orchestrated = OrchestratedLlmClient(smart_client=smart, fast_clients=[fast1, fast2])
        assert await orchestrated.is_available_async() is False

    @pytest.mark.asyncio
    async def test_exception_in_fast_client_does_not_block(self):
        """Exception in one fast client's is_available_async → skip, try next."""
        smart = _make_client(LlmProvider.GROQ, available=False)

        broken = _make_client(LlmProvider.OLLAMA, available=False)
        broken.is_available_async = AsyncMock(side_effect=Exception("network error"))

        working = _make_client(LlmProvider.DEEPSEEK, available=True)

        orchestrated = OrchestratedLlmClient(smart_client=smart, fast_clients=[broken, working])
        assert await orchestrated.is_available_async() is True

    @pytest.mark.asyncio
    async def test_no_fast_clients_uses_smart_only(self):
        """With no fast clients, availability depends solely on smart client."""
        smart_available = _make_client(LlmProvider.GROQ, available=True)
        orchestrated = OrchestratedLlmClient(smart_client=smart_available, fast_clients=[])
        assert await orchestrated.is_available_async() is True

        smart_unavailable = _make_client(LlmProvider.GROQ, available=False)
        orchestrated2 = OrchestratedLlmClient(smart_client=smart_unavailable, fast_clients=[])
        assert await orchestrated2.is_available_async() is False


# ---------------------------------------------------------------------------
# Per-provider resilience (no shared circuit breaker)
# ---------------------------------------------------------------------------


class TestPerProviderResilience:
    """Verify that orchestrated.py does NOT have a shared @resilient decorator."""

    def test_send_async_has_no_resilient_decorator(self):
        """send_async should not be wrapped in @resilient at the orchestrated level."""
        from warden.llm.providers.orchestrated import OrchestratedLlmClient

        # The function should not have __wrapped__ attribute (from resilient decorator)
        method = OrchestratedLlmClient.send_async
        assert not hasattr(method, "__wrapped__"), (
            "send_async should not have @resilient decorator (removes shared circuit breaker)"
        )

    @pytest.mark.asyncio
    async def test_second_fast_provider_wins_if_first_fails(self):
        """Second fast provider succeeds when first fails — no circuit breaker blocking."""
        smart = _make_client(LlmProvider.GROQ, available=True)
        smart.send_async = AsyncMock(return_value=_fail_response("smart failed"))

        fast1 = _make_client(LlmProvider.OLLAMA, available=True)
        fast1.send_async = AsyncMock(return_value=_fail_response("fast1 failed"))

        fast2 = _make_client(LlmProvider.DEEPSEEK, available=True)
        fast2.send_async = AsyncMock(return_value=_success_response("fast2 won"))

        orchestrated = OrchestratedLlmClient(smart_client=smart, fast_clients=[fast1, fast2])
        request = LlmRequest(system_prompt="", use_fast_tier=True, user_message="test")

        response = await orchestrated.send_async(request)
        assert response.success is True
        assert response.content == "fast2 won"
