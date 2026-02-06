"""Rate limiter for LLM API calls (ID 17)."""
import asyncio
import time
from dataclasses import dataclass


@dataclass
class RateLimitConfig:
    """Rate limiter configuration."""
    tpm: int = 5000  # Tokens per minute
    rpm: int = 10    # Requests per minute
    burst: int = 1   # Burst capacity


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


class TokenBucketLimiter:
    """Token bucket rate limiter implementation."""

    def __init__(self, tpm=60, burst=10):
        self.tpm, self.burst, self.tokens = tpm, burst, burst
        self.last = time.time()

    async def acquire(self, n=1):
        elapsed = time.time() - self.last
        self.tokens = min(self.burst, self.tokens + elapsed * self.tpm / 60)
        self.last = time.time()
        if self.tokens < n:
            await asyncio.sleep((n - self.tokens) * 60 / self.tpm)
