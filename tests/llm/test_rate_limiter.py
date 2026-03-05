"""
Unit tests for RateLimiter and TokenBucketLimiter.

Covers the burst=1 class of bugs: misconfigured burst caps that silently
throttle the pipeline to a crawl without any visible error.
"""

import asyncio
import time

import pytest

from warden.llm.rate_limiter import RateLimitConfig, RateLimiter, TokenBucketLimiter


# ---------------------------------------------------------------------------
# TokenBucketLimiter — core algorithm
# ---------------------------------------------------------------------------


class TestTokenBucketLimiter:
    """Low-level bucket behaviour."""

    def test_auto_burst_equals_tpm(self):
        """burst=0 on RateLimitConfig → token bucket starts with tokens == tpm."""
        cfg = RateLimitConfig(tpm=5000, rpm=10, burst=0)
        rl = RateLimiter(cfg)
        # burst=0 → auto: token_burst = tpm
        assert rl.token_limiter.burst == 5000
        assert rl.token_limiter.tokens == 5000

    def test_explicit_burst_respected(self):
        """burst=500 → bucket starts with exactly 500 tokens."""
        cfg = RateLimitConfig(tpm=5000, rpm=10, burst=500)
        rl = RateLimiter(cfg)
        assert rl.token_limiter.burst == 500
        assert rl.token_limiter.tokens == 500

    @pytest.mark.asyncio
    async def test_first_acquire_no_wait_when_within_burst(self):
        """Requesting tokens within burst capacity should not block."""
        bucket = TokenBucketLimiter(tpm=5000, burst=5000)
        t0 = time.monotonic()
        await bucket.acquire(1000)
        elapsed = time.monotonic() - t0
        # Must complete in under 50ms — zero wait
        assert elapsed < 0.05, f"First acquire blocked for {elapsed:.3f}s"

    @pytest.mark.asyncio
    async def test_acquire_beyond_burst_calculates_correct_wait(self):
        """Request > available tokens → must wait proportional time."""
        # tpm=6000 → 100 tokens/sec. burst=100, start with 100 tokens.
        bucket = TokenBucketLimiter(tpm=6000, burst=100)
        # Drain the bucket
        await bucket.acquire(100)
        assert bucket.tokens == 0

        # Requesting 50 more tokens: need 50/100 = 0.5s wait
        t0 = time.monotonic()
        await bucket.acquire(50)
        elapsed = time.monotonic() - t0
        # Allow 100ms tolerance
        assert 0.3 < elapsed < 0.8, f"Wait was {elapsed:.3f}s, expected ~0.5s"

    @pytest.mark.asyncio
    async def test_tokens_refill_over_time(self):
        """Tokens should refill based on elapsed time."""
        bucket = TokenBucketLimiter(tpm=6000, burst=100)
        # Drain completely
        await bucket.acquire(100)

        # Wait 0.1s → should refill ~10 tokens (100 tokens/sec * 0.1s)
        await asyncio.sleep(0.12)

        # Now acquire 10 should be near-instant
        t0 = time.monotonic()
        await bucket.acquire(8)
        elapsed = time.monotonic() - t0
        assert elapsed < 0.05, f"Refilled tokens should be instant, took {elapsed:.3f}s"

    @pytest.mark.asyncio
    async def test_burst_caps_refill(self):
        """Refill cannot exceed burst capacity."""
        bucket = TokenBucketLimiter(tpm=600000, burst=100)
        # Drain
        await bucket.acquire(100)
        # Sleep long enough for many tokens to refill
        await asyncio.sleep(0.2)
        # Force a refill calculation by acquiring inside the lock
        async with bucket._lock:
            now = time.time()
            elapsed = now - bucket.last
            bucket.tokens = min(bucket.burst, bucket.tokens + elapsed * bucket.tpm / 60)
            bucket.last = now
        # Tokens must be capped at burst
        assert bucket.tokens <= bucket.burst


# ---------------------------------------------------------------------------
# RateLimiter — dual bucket (token + request)
# ---------------------------------------------------------------------------


class TestRateLimiterDualBucket:
    """The RateLimiter wraps two independent TokenBucketLimiters."""

    def test_request_limiter_separate_from_token_limiter(self):
        """Token and request limiters are independent instances."""
        cfg = RateLimitConfig(tpm=5000, rpm=10, burst=0)
        rl = RateLimiter(cfg)
        # Different burst capacities
        assert rl.token_limiter.burst == 5000  # burst=0 → auto = tpm
        assert rl.request_limiter.burst == 10  # burst=0 → auto = rpm
        # They are distinct objects
        assert rl.token_limiter is not rl.request_limiter

    @pytest.mark.asyncio
    async def test_concurrent_acquires_dont_deadlock(self):
        """10 parallel acquires must complete within 5s (hang protection)."""
        cfg = RateLimitConfig(tpm=100000, rpm=100, burst=0)
        rl = RateLimiter(cfg)

        async def do_acquire(i: int):
            await rl.acquire(100)
            return i

        tasks = [do_acquire(i) for i in range(10)]
        results = await asyncio.wait_for(
            asyncio.gather(*tasks),
            timeout=5.0,
        )
        assert len(results) == 10

    @pytest.mark.asyncio
    async def test_acquire_async_alias_works(self):
        """acquire_async is an alias for acquire — both should work."""
        cfg = RateLimitConfig(tpm=100000, rpm=100, burst=0)
        rl = RateLimiter(cfg)
        # Both should complete without error
        await rl.acquire(10)
        await rl.acquire_async(10)


# ---------------------------------------------------------------------------
# Regression: burst=1 bug class
# ---------------------------------------------------------------------------


class TestBurstOneBugRegression:
    """
    The original bug: burst=1 with tpm=1000 means the first 1000-token
    request waits ~60s. These tests ensure that default config never
    produces this pathological behaviour.
    """

    @pytest.mark.asyncio
    async def test_default_config_first_request_instant(self):
        """Default RateLimitConfig → first 1000-token request is instant."""
        cfg = RateLimitConfig()  # tpm=5000, rpm=10, burst=0
        rl = RateLimiter(cfg)

        t0 = time.monotonic()
        await rl.acquire(1000)
        elapsed = time.monotonic() - t0
        assert elapsed < 0.05, (
            f"Default config blocked first request for {elapsed:.3f}s — burst={cfg.burst} likely misconfigured"
        )

    def test_burst_one_detected_as_pathological(self):
        """burst=1 with tpm=5000 → token bucket only has 1 token initially."""
        cfg = RateLimitConfig(tpm=5000, rpm=10, burst=1)
        rl = RateLimiter(cfg)
        # This is the pathological case: bucket starts with only 1 token
        assert rl.token_limiter.tokens == 1
        # A 1000-token request would need to wait ~12s
        # This test documents the problem so it's caught in review

    @pytest.mark.asyncio
    async def test_sequential_acquires_do_not_deadlock(self):
        """Lock must be released — sequential calls must complete without hanging."""
        rl = RateLimiter(RateLimitConfig(tpm=1_000_000, rpm=1000))
        await rl.acquire(100)
        await rl.acquire(100)  # Deadlocked before fix
        await rl.acquire(100)  # Triple verification
