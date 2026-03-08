"""
Global Rate Limiter Singleton

Provides a thread-safe global rate limiter for all LLM providers.
Prevents rate limit violations across the entire application.

Issue #17 Fix: Global rate limiting implementation
"""

import asyncio
import threading
from typing import Optional

from warden.llm.rate_limiter import RateLimitConfig, RateLimiter

# Module-level threading lock for safe singleton initialization.
# Threading lock is safe across event loops unlike asyncio.Lock.
_init_lock = threading.Lock()


class GlobalRateLimiter:
    """
    Singleton global rate limiter for all LLM API calls.

    Usage:
        limiter = GlobalRateLimiter.get_instance()
        await limiter.acquire("openai", tokens=1000)
    """

    _instance: Optional["GlobalRateLimiter"] = None

    # Static configuration for provider limits
    _LIMIT_CONFIGS = {
        "qwen": RateLimitConfig(rpm=60, tpm=100000),
        "ollama": RateLimitConfig(rpm=60, tpm=100000),
        "openai": RateLimitConfig(rpm=10, tpm=40000),
        "azure": RateLimitConfig(rpm=10, tpm=40000),
        "anthropic": RateLimitConfig(rpm=10, tpm=40000),
        "gemini": RateLimitConfig(rpm=15, tpm=30000),
        "default": RateLimitConfig(rpm=10, tpm=10000),
    }

    def __init__(self):
        """Initialize global rate limiter."""
        if GlobalRateLimiter._instance is not None:
            raise RuntimeError("Use GlobalRateLimiter.get_instance() instead")

        # Maps (loop_id, provider_key) -> RateLimiter to ensure event-loop isolation.
        self._loop_limiters: dict[tuple[int, str], RateLimiter] = {}

        # Concurrency Semaphores (Chaos Engineering: Resource Isolation)
        # Maps (loop_id, provider_key) -> Semaphore
        self._loop_semaphores: dict[tuple[int, str], asyncio.Semaphore] = {}

    @classmethod
    async def get_instance(cls) -> "GlobalRateLimiter":
        """
        Get or create the global rate limiter instance (thread-safe).

        Uses a module-level threading lock to avoid TOCTOU race conditions
        that occur with lazy asyncio.Lock initialization.

        Returns:
            Singleton instance of GlobalRateLimiter
        """
        if cls._instance is not None:
            return cls._instance
        with _init_lock:
            if cls._instance is None:
                cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance (for testing purposes)."""
        with _init_lock:
            cls._instance = None

    async def acquire(self, provider: str = "default", tokens: int = 0) -> None:
        """
        Acquire rate limit permission and concurrency slot for a provider.

        Args:
            provider: Provider name (e.g., "openai", "azure")
            tokens: Number of tokens to reserve

        Raises:
            asyncio.TimeoutError: If rate limit cannot be acquired within timeout
        """
        provider_key = provider.lower()
        limiter = self.get_limiter(provider_key)

        # 1. Acquire Token/RPM Rate Limit
        await limiter.acquire(tokens=tokens)

    def _get_semaphore(self, provider: str, limit: int = 1) -> asyncio.Semaphore:
        """Get or create an asyncio semaphore for a provider, bound to the current loop."""
        loop = asyncio.get_running_loop()
        key = (id(loop), provider)
        if key not in self._loop_semaphores:
            self._loop_semaphores[key] = asyncio.Semaphore(limit)
        return self._loop_semaphores[key]

    def concurrency_limit(self, provider: str) -> asyncio.Semaphore:
        """Return the concurrency semaphore for a provider. (#314)

        Not async — semaphore creation is synchronous dict lookup.
        Callers use: ``async with limiter.concurrency_limit(provider):``
        """
        provider_key = provider.lower()
        # For local LLMs, allow up to 3 concurrent requests so fast+smart tier can race.
        # 3 is empirically safe on 8-core machines; CI overrides via WARDEN_OLLAMA_CONCURRENCY.
        import os as _os

        try:
            _local_limit = int(_os.environ.get("WARDEN_OLLAMA_CONCURRENCY", "3"))
        except ValueError:
            _local_limit = 3
        limit = _local_limit if ("ollama" in provider_key or "qwen" in provider_key) else 10
        return self._get_semaphore(provider_key, limit=limit)

    def get_limiter(self, provider: str = "default") -> RateLimiter:
        """
        Get the rate limiter for a specific provider, bound to current event loop.

        Args:
            provider: Provider name

        Returns:
            RateLimiter instance for the provider
        """
        provider_key = provider.lower()
        loop = asyncio.get_running_loop()
        key = (id(loop), provider_key)

        if key not in self._loop_limiters:
            config = self._LIMIT_CONFIGS.get(provider_key, self._LIMIT_CONFIGS["default"])
            self._loop_limiters[key] = RateLimiter(config)

        return self._loop_limiters[key]

    def get_stats(self, provider: str = "default") -> dict:
        """
        Get current rate limit statistics for a provider.

        Args:
            provider: Provider name

        Returns:
            Dictionary with current rate limit stats
        """
        limiter = self.get_limiter(provider)
        return {
            "provider": provider,
            "rpm": limiter.config.rpm,
            "tpm": limiter.config.tpm,
        }
