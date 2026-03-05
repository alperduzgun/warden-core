"""
Provider-level circuit breaker for LLM orchestration.

Prevents cascading timeouts when a provider is repeatedly failing.
Instead of waiting for full timeout on every request (e.g., 5 frames x 3 retries x 30s = 450s),
an open circuit fails fast and the orchestrator skips to the next provider immediately.

States:
    CLOSED  - Provider is healthy, requests flow normally.
    OPEN    - Provider has exceeded failure threshold, requests are rejected immediately.
    HALF_OPEN - After open_duration elapses, allow one probe request to test recovery.

Usage:
    cb = ProviderCircuitBreaker()
    if cb.is_open(provider):
        skip provider
    try:
        response = await provider.send_async(request)
        cb.record_success(provider)
    except Exception:
        cb.record_failure(provider)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import timedelta
from enum import Enum

from warden.shared.infrastructure.logging import get_logger

from .types import LlmProvider

logger = get_logger(__name__)


class ProviderCircuitState(Enum):
    """Circuit breaker states per provider."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class _ProviderState:
    """Internal state tracking for a single provider's circuit breaker."""

    state: ProviderCircuitState = ProviderCircuitState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: float | None = None
    last_state_change: float = field(default_factory=time.time)


class ProviderCircuitBreaker:
    """Orchestrator-level circuit breaker that tracks failures per LLM provider.

    This is intentionally separate from the per-provider ``@resilient`` decorator.
    The ``@resilient`` decorator handles retries and timeouts *within* a single
    provider call.  This circuit breaker sits *above* that layer in the orchestrator
    and decides whether to even *attempt* a provider based on its recent track record.

    Parameters:
        fail_threshold: Number of consecutive failures before opening the circuit.
        open_duration: How long the circuit stays open before transitioning to half-open.
        success_threshold: Number of consecutive successes in half-open state
                           required to close the circuit again.
    """

    def __init__(
        self,
        fail_threshold: int = 3,
        open_duration: timedelta = timedelta(minutes=5),
        success_threshold: int = 1,
    ) -> None:
        self.fail_threshold = fail_threshold
        self.open_duration = open_duration
        self.success_threshold = success_threshold
        self._states: dict[LlmProvider, _ProviderState] = {}

    def _get_state(self, provider: LlmProvider) -> _ProviderState:
        """Get or create state for a provider."""
        if provider not in self._states:
            self._states[provider] = _ProviderState()
        return self._states[provider]

    def _maybe_transition_to_half_open(self, provider: LlmProvider, state: _ProviderState) -> None:
        """Check if an OPEN circuit should transition to HALF_OPEN."""
        if state.state != ProviderCircuitState.OPEN:
            return
        if state.last_failure_time is None:
            return
        elapsed = time.time() - state.last_failure_time
        if elapsed >= self.open_duration.total_seconds():
            state.state = ProviderCircuitState.HALF_OPEN
            state.success_count = 0
            state.last_state_change = time.time()
            logger.info(
                "provider_circuit_half_open",
                provider=provider.value,
                elapsed_seconds=round(elapsed, 1),
                message="Circuit transitioned to half-open, allowing probe request",
            )

    def get_state(self, provider: LlmProvider) -> ProviderCircuitState:
        """Get the current circuit state for a provider, applying time-based transitions."""
        state = self._get_state(provider)
        self._maybe_transition_to_half_open(provider, state)
        return state.state

    def is_open(self, provider: LlmProvider) -> bool:
        """Check if a provider's circuit is open (should be skipped).

        Returns True only when the circuit is in the OPEN state.
        HALF_OPEN returns False to allow a probe request through.
        """
        return self.get_state(provider) == ProviderCircuitState.OPEN

    def record_failure(self, provider: LlmProvider) -> None:
        """Record a failure for a provider.

        In CLOSED state: increments failure count; opens circuit if threshold reached.
        In HALF_OPEN state: immediately re-opens the circuit (probe failed).
        In OPEN state: no-op (shouldn't happen if callers check is_open first).
        """
        state = self._get_state(provider)
        state.failure_count += 1
        state.last_failure_time = time.time()

        if state.state == ProviderCircuitState.CLOSED:
            if state.failure_count >= self.fail_threshold:
                state.state = ProviderCircuitState.OPEN
                state.last_state_change = time.time()
                logger.warning(
                    "provider_circuit_opened",
                    provider=provider.value,
                    failure_count=state.failure_count,
                    open_duration_seconds=self.open_duration.total_seconds(),
                    message=(
                        f"Provider circuit opened after {state.failure_count} consecutive failures. "
                        f"Will skip for {self.open_duration.total_seconds()}s."
                    ),
                )
        elif state.state == ProviderCircuitState.HALF_OPEN:
            # Probe request failed -- back to OPEN
            state.state = ProviderCircuitState.OPEN
            state.last_state_change = time.time()
            logger.warning(
                "provider_circuit_reopened",
                provider=provider.value,
                message="Half-open probe failed, circuit re-opened",
            )

    def record_success(self, provider: LlmProvider) -> None:
        """Record a success for a provider.

        In CLOSED state: resets failure count (provider is healthy).
        In HALF_OPEN state: increments success count; closes circuit if threshold reached.
        In OPEN state: no-op (shouldn't happen if callers check is_open first).
        """
        state = self._get_state(provider)

        if state.state == ProviderCircuitState.CLOSED:
            # Reset failure count on success -- provider is healthy
            state.failure_count = 0
        elif state.state == ProviderCircuitState.HALF_OPEN:
            state.success_count += 1
            if state.success_count >= self.success_threshold:
                state.state = ProviderCircuitState.CLOSED
                state.failure_count = 0
                state.success_count = 0
                state.last_state_change = time.time()
                logger.info(
                    "provider_circuit_closed",
                    provider=provider.value,
                    message="Provider recovered, circuit closed",
                )

    def reset(self, provider: LlmProvider) -> None:
        """Manually reset a provider's circuit to CLOSED state."""
        if provider in self._states:
            self._states[provider] = _ProviderState()
            logger.info(
                "provider_circuit_reset",
                provider=provider.value,
                message="Circuit manually reset to closed",
            )

    def get_open_providers(self) -> list[LlmProvider]:
        """Return list of providers whose circuits are currently open."""
        return [p for p in self._states if self.is_open(p)]

    def summary(self) -> dict[str, str]:
        """Return a summary of all tracked provider circuit states."""
        result = {}
        for provider in self._states:
            result[provider.value] = self.get_state(provider).value
        return result
