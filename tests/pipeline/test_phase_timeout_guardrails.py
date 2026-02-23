"""
Pipeline phase timeout guardrail tests.

Ensures no pipeline phase can silently hang due to misconfigured rate limits,
deadlocked async operations, or other runtime issues. Each test uses
asyncio.wait_for with hard timeouts — if a phase hangs, the test fails
instead of blocking CI forever.
"""

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from warden.llm.rate_limiter import RateLimitConfig, RateLimiter
from warden.llm.types import LlmResponse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_llm_response(content: str = "no issues found") -> LlmResponse:
    return LlmResponse(
        content=content,
        success=True,
        provider=None,
        model="test-model",
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
    )


def _make_fast_llm_service() -> Mock:
    """Create a mock LLM service that responds in <10ms."""
    llm = Mock()
    llm.provider = "OLLAMA"
    llm.endpoint = "http://localhost:11434"
    llm.config = None

    async def _fast_complete(**kwargs):
        await asyncio.sleep(0.005)  # 5ms
        return _mock_llm_response()

    llm.complete_async = AsyncMock(side_effect=_fast_complete)
    return llm


# ---------------------------------------------------------------------------
# Rate limiter first-batch latency
# ---------------------------------------------------------------------------


class TestRateLimiterFirstBatch:
    """The first batch of requests must never be blocked by the rate limiter."""

    @pytest.mark.asyncio
    async def test_rate_limiter_doesnt_block_first_batch(self):
        """First batch acquire (4 x 300 tokens) must complete in < 1s.

        Uses batch_size=4 which is the typical concurrent batch size.
        With default config (tpm=5000, rpm=10), 4 concurrent requests
        fit within both token and request burst capacity.
        """
        cfg = RateLimitConfig(tpm=5000, rpm=10, burst=0)
        rl = RateLimiter(cfg)

        t0 = time.monotonic()

        # 4 files per batch (typical batch_size), each ~300 tokens
        tasks = [rl.acquire(300) for _ in range(4)]
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=1.0)

        elapsed = time.monotonic() - t0
        assert elapsed < 0.1, f"First batch of 4 acquires took {elapsed:.2f}s — rate limiter is blocking first batch"

    @pytest.mark.asyncio
    async def test_local_provider_rate_limiter_instant(self):
        """Local provider (tpm=1M) → 16 acquires of 1000 tokens each = instant."""
        cfg = RateLimitConfig(tpm=1_000_000, rpm=100, burst=0)
        rl = RateLimiter(cfg)

        t0 = time.monotonic()
        tasks = [rl.acquire(1000) for _ in range(16)]
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=1.0)

        elapsed = time.monotonic() - t0
        assert elapsed < 0.1, f"Local rate limiter blocked for {elapsed:.2f}s"


# ---------------------------------------------------------------------------
# Analysis phase timeout
# ---------------------------------------------------------------------------


class TestAnalysisPhaseTimeout:
    """Analysis phase must complete within reasonable time."""

    @pytest.mark.asyncio
    async def test_analysis_phase_completes_within_timeout(self):
        """Mock LLM + 16 files → analysis must finish in 30s."""
        from warden.analysis.application.llm_analysis_phase import LLMAnalysisPhase
        from warden.analysis.application.llm_phase_base import LLMPhaseConfig

        llm = _make_fast_llm_service()
        config = LLMPhaseConfig(
            enabled=True,
            tpm_limit=1_000_000,
            rpm_limit=100,
            batch_size=4,
            max_retries=1,
            timeout=5,
        )

        phase = LLMAnalysisPhase(config=config, llm_service=llm)

        # Create 16 mock file contexts
        items = [
            {
                "file_path": f"src/module_{i}.py",
                "content": f"def func_{i}(): pass\n" * 10,
                "language": "python",
            }
            for i in range(16)
        ]

        t0 = time.monotonic()
        results = await asyncio.wait_for(
            phase.analyze_batch_with_llm_async(items),
            timeout=30.0,
        )
        elapsed = time.monotonic() - t0

        assert elapsed < 30.0, f"Analysis phase took {elapsed:.1f}s (limit: 30s)"
        assert len(results) == 16


# ---------------------------------------------------------------------------
# Full pipeline no-hang (LLM disabled)
# ---------------------------------------------------------------------------


class TestFullPipelineNoHang:
    """Pipeline with LLM disabled must be fast."""

    @pytest.mark.asyncio
    async def test_full_pipeline_no_hang_without_llm(self):
        """LLM=None, 16 files → pipeline phases should resolve in 10s."""
        from warden.analysis.application.llm_phase_base import LLMPhaseConfig

        # Phase with LLM disabled
        config = LLMPhaseConfig(enabled=False)

        # Without LLM, analyze_with_llm_async returns None immediately
        from warden.analysis.application.llm_analysis_phase import LLMAnalysisPhase

        phase = LLMAnalysisPhase(config=config, llm_service=None)

        items = [
            {
                "file_path": f"src/module_{i}.py",
                "content": f"def func_{i}(): pass\n",
                "language": "python",
            }
            for i in range(16)
        ]

        t0 = time.monotonic()
        results = await asyncio.wait_for(
            phase.analyze_batch_with_llm_async(items),
            timeout=10.0,
        )
        elapsed = time.monotonic() - t0

        assert elapsed < 10.0, f"No-LLM pipeline took {elapsed:.1f}s (limit: 10s)"
        # All results should be None (no LLM)
        assert all(r is None for r in results)
        assert len(results) == 16
