"""
Integration tests: LLMPhaseBase + ProviderSpeedBenchmarkService.

Verifies the critical path in _call_llm_with_retry_async:
  - Local provider  → complete_async receives benchmark-derived max_tokens
                      (NOT the static config.max_tokens=800)
  - Cloud provider  → complete_async receives config.max_tokens unchanged
  - Benchmark error → falls back to config.max_tokens (no crash)
  - Cache           → only one benchmark per provider session

Note on timing:
  AsyncMock.send_async returns instantly (elapsed≈0) so tok/s → ∞ → ceiling.
  We mock time.monotonic where we need realistic elapsed values.

Note on rate limiter:
  We inject a high-capacity rate limiter in every test to avoid the 40s+ sleep
  that occurs when the default burst=1000 bucket is exhausted between calls.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch  # patch: cloud bypass test

import pytest

from warden.analysis.application.llm_phase_base import LLMPhaseBase, LLMPhaseConfig
from warden.llm.provider_speed_benchmark import ProviderSpeedBenchmarkService
from warden.llm.types import LlmProvider, LlmResponse


# ---------------------------------------------------------------------------
# Minimal concrete subclass (LLMPhaseBase is abstract)
# ---------------------------------------------------------------------------


class _Phase(LLMPhaseBase):
    @property
    def phase_name(self) -> str:
        return "integration_test"

    def get_system_prompt(self) -> str:
        return "system"

    def format_user_prompt(self, context) -> str:
        return "user"

    def parse_llm_response(self, response) -> str:
        return response


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_phase(config: LLMPhaseConfig, llm: MagicMock) -> _Phase:
    """Create a test phase with a no-op rate limiter.

    TokenBucketLimiter.acquire() has a pre-existing bug: it acquires its
    asyncio.Lock and never releases it, deadlocking on the second sequential
    call.  We mock acquire_async to bypass this entirely so integration tests
    can call _call_llm_with_retry_async multiple times without hanging.
    """
    rl = MagicMock()
    rl.acquire_async = AsyncMock(return_value=None)
    return _Phase(config=config, llm_service=llm, rate_limiter=rl)


def _ollama_llm(tokens_produced: int = 10) -> MagicMock:
    """Mock Ollama client — send_async (benchmark) and complete_async (main call)."""
    llm = MagicMock()
    llm.provider = LlmProvider.OLLAMA
    llm.endpoint = ""
    llm.config = None

    benchmark_resp = LlmResponse(
        content="hello " * tokens_produced,
        success=True,
        provider=LlmProvider.OLLAMA,
        model="qwen",
        completion_tokens=tokens_produced,
    )
    llm.send_async = AsyncMock(return_value=benchmark_resp)

    main_resp = LlmResponse(
        content='{"score": 8}',
        success=True,
        provider=LlmProvider.OLLAMA,
        model="qwen",
    )
    llm.complete_async = AsyncMock(return_value=main_resp)
    return llm


def _groq_llm() -> MagicMock:
    llm = MagicMock()
    llm.provider = LlmProvider.GROQ
    llm.endpoint = ""
    llm.config = None
    llm.complete_async = AsyncMock(
        return_value=LlmResponse(content="ok", success=True, provider=LlmProvider.GROQ, model="llama3")
    )
    return llm


@pytest.fixture(autouse=True)
def reset_benchmark():
    ProviderSpeedBenchmarkService.reset_instance()
    yield
    ProviderSpeedBenchmarkService.reset_instance()


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


class TestBenchmarkIntegration:
    @pytest.mark.asyncio
    async def test_local_provider_benchmark_is_applied(self):
        """
        For Ollama: complete_async must receive max_tokens from the benchmark,
        not the static config.max_tokens=800.

        AsyncMock returns instantly (elapsed≈0) so tok/s→∞ → ceiling=4000.
        What matters: the code called the benchmark and used its result.
        """
        config = LLMPhaseConfig(enabled=True, max_tokens=800, timeout=120, max_retries=1)
        llm = _ollama_llm(tokens_produced=10)
        phase = _make_phase(config, llm)
        assert phase.is_local is True

        await phase._call_llm_with_retry_async("sys", "user")

        assert llm.complete_async.called
        _, kwargs = llm.complete_async.call_args
        actual = kwargs.get("max_tokens")

        # Benchmark was applied (not the static config default)
        assert actual != 800, f"complete_async used static config.max_tokens=800, benchmark was ignored"
        # Result is within valid range
        assert (
            ProviderSpeedBenchmarkService.MAX_TOKENS_FLOOR <= actual <= ProviderSpeedBenchmarkService.MAX_TOKENS_CEILING
        )
        # send_async (benchmark probe) was called
        assert llm.send_async.call_count == 1

    @pytest.mark.asyncio
    async def test_cloud_provider_uses_config_max_tokens(self):
        """
        For Groq: complete_async must receive config.max_tokens=800 unchanged.
        Benchmark service must NOT be invoked.
        """
        config = LLMPhaseConfig(enabled=True, max_tokens=800, timeout=120, max_retries=1)
        llm = _groq_llm()
        phase = _make_phase(config, llm)
        assert not getattr(phase, "is_local", False)

        with patch("warden.llm.provider_speed_benchmark.ProviderSpeedBenchmarkService.get_instance") as mock_get:
            await phase._call_llm_with_retry_async("sys", "user")

        mock_get.assert_not_called()

        _, kwargs = llm.complete_async.call_args
        assert kwargs.get("max_tokens") == 800

    @pytest.mark.asyncio
    async def test_benchmark_failure_falls_back_to_config(self):
        """
        Benchmark send_async raises → effective_max_tokens = config.max_tokens=800.
        Phase must still call complete_async normally (no crash).
        """
        config = LLMPhaseConfig(enabled=True, max_tokens=800, timeout=120, max_retries=1)
        llm = _ollama_llm()
        llm.send_async = AsyncMock(side_effect=RuntimeError("ollama crashed"))
        phase = _make_phase(config, llm)
        assert phase.is_local is True

        await phase._call_llm_with_retry_async("sys", "user")

        assert llm.complete_async.called
        _, kwargs = llm.complete_async.call_args
        assert kwargs.get("max_tokens") == 800

    @pytest.mark.asyncio
    async def test_cache_prevents_repeated_benchmarks(self):
        """
        Two consecutive LLM calls on the same local provider must only
        trigger one benchmark (send_async call), not two.
        """
        config = LLMPhaseConfig(enabled=True, max_tokens=800, timeout=120, max_retries=1)
        llm = _ollama_llm(tokens_produced=10)
        phase = _make_phase(config, llm)

        await phase._call_llm_with_retry_async("sys", "first call")
        await phase._call_llm_with_retry_async("sys", "second call")

        assert llm.complete_async.call_count == 2
        assert llm.send_async.call_count == 1, f"Benchmark ran {llm.send_async.call_count}x — cache not working"

    def test_phase_timeout_passed_to_calculate(self):
        """
        The phase timeout value (config.timeout) is passed as phase_timeout_s
        to get_safe_max_tokens. Verify _calculate honours it.
        30s timeout: _calculate(10 tok/s, 30s) = 225
        120s timeout: _calculate(10 tok/s, 120s) = 900
        This is a pure-function contract — no async, no mock needed.
        """
        tokens_30 = ProviderSpeedBenchmarkService._calculate(10.0, 30.0)
        tokens_120 = ProviderSpeedBenchmarkService._calculate(10.0, 120.0)

        assert tokens_30 < tokens_120
        assert tokens_30 == 225
        assert tokens_120 == 900
