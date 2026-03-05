"""Rate limiter for LLM API calls (ID 17)."""

import asyncio
import time
from dataclasses import dataclass


@dataclass
class RateLimitConfig:
    """Rate limiter configuration."""

    tpm: int = 5000  # Tokens per minute
    rpm: int = 10  # Requests per minute
    burst: int = 0  # Burst capacity (0 = auto, set to tpm for tokens / rpm for requests)


class RateLimiter:
    """
    Rate limiter for LLM API calls with token and request limits.

    Implements token bucket algorithm for both token and request rate limiting.
    """

    def __init__(self, config: RateLimitConfig):
        """Initialize rate limiter with configuration."""
        self.config = config
        # burst=0 means auto: allow one full minute's budget as initial burst
        # so the first request(s) go through immediately without artificial wait.
        token_burst = config.burst if config.burst > 0 else config.tpm
        request_burst = config.burst if config.burst > 0 else config.rpm
        self.token_limiter = TokenBucketLimiter(tpm=config.tpm, burst=token_burst)
        self.request_limiter = TokenBucketLimiter(tpm=config.rpm, burst=request_burst)

    async def acquire(self, tokens: int = 1):
        """
        Acquire rate limit tokens.

        Args:
            tokens: Number of tokens to acquire

        Note:
            Blocks until both token and request limits allow the operation.
        """
        await self.token_limiter.acquire(tokens)
        await self.request_limiter.acquire(1)  # One request

    # Alias used by callers across the codebase
    acquire_async = acquire


class TokenBucketLimiter:
    """Token bucket rate limiter implementation."""

    def __init__(self, tpm=60, burst=10):
        self.tpm, self.burst, self.tokens = tpm, burst, burst
        self.last = time.time()
        self._lock = asyncio.Lock()

    async def acquire(self, n=1):
        if n <= 0:
            return
        # Use manual acquire/release so we can drop the lock while sleeping.
        # Mixing async-with and manual release inside the same block causes a
        # double-release on __aexit__, corrupting lock state under concurrency.
        await self._lock.acquire()
        try:
            now = time.time()
            elapsed = now - self.last
            self.tokens = min(self.burst, self.tokens + elapsed * self.tpm / 60)
            self.last = now
            if self.tokens < n:
                wait = (n - self.tokens) * 60 / self.tpm
                self.tokens = 0
                self._lock.release()
                await asyncio.sleep(wait)
                await self._lock.acquire()
            else:
                self.tokens -= n
            self._lock.release()
        except Exception:
            # Ensure the lock is always released on unexpected errors
            if self._lock.locked():
                self._lock.release()
            raise
