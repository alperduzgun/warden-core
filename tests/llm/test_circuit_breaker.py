"""
Tests for warden.llm.circuit_breaker.ProviderCircuitBreaker.

Covers:
1. CLOSED -> OPEN transition after fail_threshold consecutive failures
2. OPEN -> HALF_OPEN transition after open_duration elapses
3. HALF_OPEN -> CLOSED transition after success_threshold successes
4. HALF_OPEN -> OPEN re-transition on probe failure
5. Success resets failure count in CLOSED state
6. is_open returns True only in OPEN state
7. get_open_providers and summary helpers
8. reset manually closes a circuit
9. Integration with OrchestratedLlmClient - fast tier skips open-circuit providers
10. Integration with OrchestratedLlmClient - smart tier fallback skips open-circuit providers
"""

from __future__ import annotations

import time
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest

from warden.llm.circuit_breaker import ProviderCircuitBreaker, ProviderCircuitState
from warden.llm.providers.orchestrated import OrchestratedLlmClient
from warden.llm.types import LlmProvider, LlmRequest, LlmResponse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(provider_val: LlmProvider = LlmProvider.OLLAMA, available: bool = True) -> AsyncMock:
    client = AsyncMock()
    client.provider = provider_val
    client.is_available_async = AsyncMock(return_value=available)
    return client


def _success_response(content: str = "ok", provider: LlmProvider = LlmProvider.OLLAMA) -> LlmResponse:
    return LlmResponse(content=content, success=True, provider=provider, model="test")


def _fail_response(error: str = "fail", provider: LlmProvider = LlmProvider.OLLAMA) -> LlmResponse:
    return LlmResponse(content="", success=False, error_message=error, provider=provider, model="test")


# ---------------------------------------------------------------------------
# Unit tests for ProviderCircuitBreaker
# ---------------------------------------------------------------------------


class TestProviderCircuitBreakerStates:
    """Test state transitions of the provider circuit breaker."""

    def test_initial_state_is_closed(self):
        """New provider starts in CLOSED state."""
        cb = ProviderCircuitBreaker()
        assert cb.get_state(LlmProvider.OLLAMA) == ProviderCircuitState.CLOSED
        assert cb.is_open(LlmProvider.OLLAMA) is False

    def test_opens_after_fail_threshold(self):
        """Circuit opens after fail_threshold consecutive failures."""
        cb = ProviderCircuitBreaker(fail_threshold=3)

        cb.record_failure(LlmProvider.OLLAMA)
        assert cb.is_open(LlmProvider.OLLAMA) is False

        cb.record_failure(LlmProvider.OLLAMA)
        assert cb.is_open(LlmProvider.OLLAMA) is False

        cb.record_failure(LlmProvider.OLLAMA)
        assert cb.is_open(LlmProvider.OLLAMA) is True

    def test_success_resets_failure_count(self):
        """A success in CLOSED state resets the failure count."""
        cb = ProviderCircuitBreaker(fail_threshold=3)

        cb.record_failure(LlmProvider.OLLAMA)
        cb.record_failure(LlmProvider.OLLAMA)
        # 2 failures, one more would open

        cb.record_success(LlmProvider.OLLAMA)
        # Should reset count

        cb.record_failure(LlmProvider.OLLAMA)
        cb.record_failure(LlmProvider.OLLAMA)
        # Only 2 failures since reset, not 3
        assert cb.is_open(LlmProvider.OLLAMA) is False

    def test_transitions_to_half_open_after_duration(self):
        """After open_duration, circuit transitions to HALF_OPEN."""
        cb = ProviderCircuitBreaker(
            fail_threshold=1,
            open_duration=timedelta(seconds=1),
        )

        cb.record_failure(LlmProvider.GROQ)
        assert cb.is_open(LlmProvider.GROQ) is True

        # Simulate time passing
        state = cb._get_state(LlmProvider.GROQ)
        state.last_failure_time = time.time() - 2  # 2 seconds ago

        assert cb.get_state(LlmProvider.GROQ) == ProviderCircuitState.HALF_OPEN
        assert cb.is_open(LlmProvider.GROQ) is False  # HALF_OPEN allows probe

    def test_half_open_success_closes_circuit(self):
        """Success in HALF_OPEN transitions to CLOSED."""
        cb = ProviderCircuitBreaker(
            fail_threshold=1,
            open_duration=timedelta(seconds=1),
            success_threshold=1,
        )

        # Open the circuit
        cb.record_failure(LlmProvider.GROQ)
        assert cb.is_open(LlmProvider.GROQ) is True

        # Simulate time passing to reach HALF_OPEN
        state = cb._get_state(LlmProvider.GROQ)
        state.last_failure_time = time.time() - 2

        assert cb.get_state(LlmProvider.GROQ) == ProviderCircuitState.HALF_OPEN

        # Probe succeeds
        cb.record_success(LlmProvider.GROQ)
        assert cb.get_state(LlmProvider.GROQ) == ProviderCircuitState.CLOSED
        assert cb.is_open(LlmProvider.GROQ) is False

    def test_half_open_failure_reopens_circuit(self):
        """Failure in HALF_OPEN transitions back to OPEN."""
        cb = ProviderCircuitBreaker(
            fail_threshold=1,
            open_duration=timedelta(seconds=1),
        )

        # Open the circuit
        cb.record_failure(LlmProvider.GROQ)

        # Simulate time passing to reach HALF_OPEN
        state = cb._get_state(LlmProvider.GROQ)
        state.last_failure_time = time.time() - 2

        assert cb.get_state(LlmProvider.GROQ) == ProviderCircuitState.HALF_OPEN

        # Probe fails
        cb.record_failure(LlmProvider.GROQ)
        assert cb.is_open(LlmProvider.GROQ) is True

    def test_independent_providers(self):
        """Each provider has independent circuit state."""
        cb = ProviderCircuitBreaker(fail_threshold=2)

        cb.record_failure(LlmProvider.OLLAMA)
        cb.record_failure(LlmProvider.OLLAMA)
        assert cb.is_open(LlmProvider.OLLAMA) is True

        # GROQ should still be closed
        assert cb.is_open(LlmProvider.GROQ) is False

    def test_reset(self):
        """Manual reset returns circuit to CLOSED."""
        cb = ProviderCircuitBreaker(fail_threshold=1)

        cb.record_failure(LlmProvider.OLLAMA)
        assert cb.is_open(LlmProvider.OLLAMA) is True

        cb.reset(LlmProvider.OLLAMA)
        assert cb.is_open(LlmProvider.OLLAMA) is False
        assert cb.get_state(LlmProvider.OLLAMA) == ProviderCircuitState.CLOSED


class TestProviderCircuitBreakerHelpers:
    """Test helper/query methods."""

    def test_get_open_providers(self):
        """get_open_providers returns only providers with OPEN circuits."""
        cb = ProviderCircuitBreaker(fail_threshold=1)

        cb.record_failure(LlmProvider.OLLAMA)
        cb.record_failure(LlmProvider.GROQ)
        cb.record_success(LlmProvider.DEEPSEEK)  # Registers but stays CLOSED

        open_providers = cb.get_open_providers()
        assert LlmProvider.OLLAMA in open_providers
        assert LlmProvider.GROQ in open_providers
        assert LlmProvider.DEEPSEEK not in open_providers

    def test_summary(self):
        """summary returns dict of provider -> state."""
        cb = ProviderCircuitBreaker(fail_threshold=1)

        cb.record_failure(LlmProvider.OLLAMA)
        cb.record_success(LlmProvider.GROQ)

        result = cb.summary()
        assert result["ollama"] == "open"
        assert result["groq"] == "closed"


# ---------------------------------------------------------------------------
# Integration tests with OrchestratedLlmClient
# ---------------------------------------------------------------------------


class TestOrchestratedCircuitBreakerIntegration:
    """Test circuit breaker integration in the orchestrated client."""

    @pytest.mark.asyncio
    async def test_fast_tier_skips_open_circuit_provider(self):
        """Provider with open circuit should be skipped in fast tier racing."""
        cb = ProviderCircuitBreaker(fail_threshold=1)

        smart = _make_client(LlmProvider.OPENAI, available=True)
        smart.send_async = AsyncMock(return_value=_success_response("smart", LlmProvider.OPENAI))

        fast_broken = _make_client(LlmProvider.OLLAMA, available=True)
        fast_broken.send_async = AsyncMock(return_value=_fail_response("ollama down", LlmProvider.OLLAMA))

        fast_working = _make_client(LlmProvider.GROQ, available=True)
        fast_working.send_async = AsyncMock(return_value=_success_response("groq ok", LlmProvider.GROQ))

        # Open OLLAMA's circuit before creating the orchestrated client
        cb.record_failure(LlmProvider.OLLAMA)

        orchestrated = OrchestratedLlmClient(
            smart_client=smart,
            fast_clients=[fast_broken, fast_working],
            circuit_breaker=cb,
        )

        request = LlmRequest(system_prompt="", user_message="test", use_fast_tier=True)
        response = await orchestrated.send_async(request)

        assert response.success is True
        assert response.content == "groq ok"
        # OLLAMA should NOT have been called (circuit open)
        fast_broken.send_async.assert_not_called()

    @pytest.mark.asyncio
    async def test_all_fast_circuits_open_falls_back_to_smart(self):
        """When all fast provider circuits are open, falls back to smart tier."""
        cb = ProviderCircuitBreaker(fail_threshold=1)

        smart = _make_client(LlmProvider.OPENAI, available=True)
        smart.send_async = AsyncMock(return_value=_success_response("smart fallback", LlmProvider.OPENAI))

        fast1 = _make_client(LlmProvider.OLLAMA, available=True)
        fast2 = _make_client(LlmProvider.GROQ, available=True)

        # Open both fast provider circuits
        cb.record_failure(LlmProvider.OLLAMA)
        cb.record_failure(LlmProvider.GROQ)

        orchestrated = OrchestratedLlmClient(
            smart_client=smart,
            fast_clients=[fast1, fast2],
            circuit_breaker=cb,
        )

        request = LlmRequest(system_prompt="", user_message="test", use_fast_tier=True)
        response = await orchestrated.send_async(request)

        assert response.success is True
        assert response.content == "smart fallback"
        fast1.send_async.assert_not_called()
        fast2.send_async.assert_not_called()

    @pytest.mark.asyncio
    async def test_smart_fallback_skips_open_circuit_fast_provider(self):
        """When smart fails and falls back to fast, circuit-open providers are skipped."""
        cb = ProviderCircuitBreaker(fail_threshold=1)

        smart = _make_client(LlmProvider.OPENAI, available=True)
        smart.send_async = AsyncMock(return_value=_fail_response("smart failed", LlmProvider.OPENAI))

        fast_broken = _make_client(LlmProvider.OLLAMA, available=True)
        fast_broken.send_async = AsyncMock(return_value=_fail_response("ollama down", LlmProvider.OLLAMA))

        fast_working = _make_client(LlmProvider.GROQ, available=True)
        fast_working.send_async = AsyncMock(return_value=_success_response("groq fallback", LlmProvider.GROQ))

        # Open OLLAMA's circuit
        cb.record_failure(LlmProvider.OLLAMA)

        orchestrated = OrchestratedLlmClient(
            smart_client=smart,
            fast_clients=[fast_broken, fast_working],
            circuit_breaker=cb,
        )

        request = LlmRequest(system_prompt="", user_message="test", use_fast_tier=False)
        response = await orchestrated.send_async(request)

        assert response.success is True
        assert response.content == "groq fallback"
        # OLLAMA should NOT have been called in fallback (circuit open)
        fast_broken.send_async.assert_not_called()

    @pytest.mark.asyncio
    async def test_failure_in_fast_tier_records_to_circuit_breaker(self):
        """Failures during fast tier racing are recorded in the circuit breaker."""
        cb = ProviderCircuitBreaker(fail_threshold=2)

        smart = _make_client(LlmProvider.OPENAI, available=True)
        smart.send_async = AsyncMock(return_value=_success_response("smart", LlmProvider.OPENAI))

        fast = _make_client(LlmProvider.OLLAMA, available=True)
        fast.send_async = AsyncMock(return_value=_fail_response("ollama error", LlmProvider.OLLAMA))

        orchestrated = OrchestratedLlmClient(
            smart_client=smart,
            fast_clients=[fast],
            circuit_breaker=cb,
        )

        # First request - fast fails, falls back to smart
        request = LlmRequest(system_prompt="", user_message="test", use_fast_tier=True)
        await orchestrated.send_async(request)

        # After 1 failure, circuit should still be closed (threshold=2)
        assert cb.is_open(LlmProvider.OLLAMA) is False

        # Second request - fast fails again
        await orchestrated.send_async(request)

        # After 2 failures, circuit should be open
        assert cb.is_open(LlmProvider.OLLAMA) is True

    @pytest.mark.asyncio
    async def test_success_in_fast_tier_records_to_circuit_breaker(self):
        """Successes during fast tier are recorded in the circuit breaker."""
        cb = ProviderCircuitBreaker(fail_threshold=3)

        smart = _make_client(LlmProvider.OPENAI, available=True)
        fast = _make_client(LlmProvider.OLLAMA, available=True)
        fast.send_async = AsyncMock(return_value=_success_response("ok", LlmProvider.OLLAMA))

        orchestrated = OrchestratedLlmClient(
            smart_client=smart,
            fast_clients=[fast],
            circuit_breaker=cb,
        )

        # Record 2 failures (one below threshold)
        cb.record_failure(LlmProvider.OLLAMA)
        cb.record_failure(LlmProvider.OLLAMA)

        # A successful request should reset the failure count
        request = LlmRequest(system_prompt="", user_message="test", use_fast_tier=True)
        response = await orchestrated.send_async(request)

        assert response.success is True
        # Failure count should be reset, so one more failure should NOT open circuit
        cb.record_failure(LlmProvider.OLLAMA)
        assert cb.is_open(LlmProvider.OLLAMA) is False

    @pytest.mark.asyncio
    async def test_smart_tier_circuit_open_still_attempts(self):
        """Smart tier is always attempted even with open circuit (last resort)."""
        cb = ProviderCircuitBreaker(fail_threshold=1)

        smart = _make_client(LlmProvider.OPENAI, available=True)
        smart.send_async = AsyncMock(return_value=_success_response("smart recovered", LlmProvider.OPENAI))

        # Open smart provider's circuit
        cb.record_failure(LlmProvider.OPENAI)
        assert cb.is_open(LlmProvider.OPENAI) is True

        orchestrated = OrchestratedLlmClient(
            smart_client=smart,
            fast_clients=[],
            circuit_breaker=cb,
        )

        request = LlmRequest(system_prompt="", user_message="test", use_fast_tier=False)
        response = await orchestrated.send_async(request)

        # Smart tier should still be attempted even with open circuit
        assert response.success is True
        smart.send_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_default_circuit_breaker_created_when_none_provided(self):
        """OrchestratedLlmClient creates a default circuit breaker if none is provided."""
        smart = _make_client(LlmProvider.OPENAI, available=True)
        orchestrated = OrchestratedLlmClient(smart_client=smart, fast_clients=[])

        assert orchestrated.circuit_breaker is not None
        assert isinstance(orchestrated.circuit_breaker, ProviderCircuitBreaker)

    @pytest.mark.asyncio
    async def test_existing_tests_pass_with_default_circuit_breaker(self):
        """Verify backward compatibility: existing behavior works with default circuit breaker."""
        smart = _make_client(LlmProvider.OPENAI, available=True)
        smart.send_async = AsyncMock(return_value=_success_response("result", LlmProvider.OPENAI))

        fast = _make_client(LlmProvider.OLLAMA, available=True)
        fast.send_async = AsyncMock(return_value=_success_response("fast result", LlmProvider.OLLAMA))

        # No explicit circuit_breaker -- should use default
        orchestrated = OrchestratedLlmClient(
            smart_client=smart,
            fast_clients=[fast],
        )

        request = LlmRequest(system_prompt="", user_message="test", use_fast_tier=True)
        response = await orchestrated.send_async(request)

        assert response.success is True
        assert response.content == "fast result"
