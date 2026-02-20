"""Rate limiter for LLM API calls (ID 17)."""

import asyncio
import time
from dataclasses import dataclass


@dataclass
class RateLimitConfig:
    """Rate limiter configuration."""

    tpm: int = 5000  # Tokens per minute
    rpm: int = 10  # Requests per minute
    burst: int = 1  # Burst capacity


class RateLimiter:
    """
    Rate limiter for LLM API calls with token and request limits.

    Implements token bucket algorithm for both token and request rate limiting.
    """

    def __init__(self, config: RateLimitConfig):
        """Initialize rate limiter with configuration."""
        self.config = config
        self.token_limiter = TokenBucketLimiter(tpm=config.tpm, burst=config.burst)
        self.request_limiter = TokenBucketLimiter(tpm=config.rpm, burst=config.burst)

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
        async with self._lock:
            now = time.time()
            elapsed = now - self.last
            self.tokens = min(self.burst, self.tokens + elapsed * self.tpm / 60)
            self.last = now
            if self.tokens < n:
                wait = (n - self.tokens) * 60 / self.tpm
                self.tokens = 0
                # Release lock while sleeping so other acquires can queue
                self._lock.release()
                try:
                    await asyncio.sleep(wait)
                finally:
                    await self._lock.acquire()
            else:
                self.tokens -= n
