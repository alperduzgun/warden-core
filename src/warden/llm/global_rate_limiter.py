"""
Global Rate Limiter Singleton

Provides a thread-safe global rate limiter for all LLM providers.
Prevents rate limit violations across the entire application.

Issue #17 Fix: Global rate limiting implementation
"""

import asyncio
import threading
from typing import Dict, Optional

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

    def __init__(self):
        """Initialize global rate limiter with provider-specific limits."""
        if GlobalRateLimiter._instance is not None:
            raise RuntimeError("Use GlobalRateLimiter.get_instance() instead")

        # Provider-specific rate limiters
        self._limiters: dict[str, RateLimiter] = {
            # Fast tier providers (high limits)
            "qwen": RateLimiter(RateLimitConfig(rpm=60, tpm=100000)),
            "ollama": RateLimiter(RateLimitConfig(rpm=60, tpm=100000)),

            # Smart tier providers (conservative limits)
            "openai": RateLimiter(RateLimitConfig(rpm=10, tpm=40000)),
            "azure": RateLimiter(RateLimitConfig(rpm=10, tpm=40000)),
            "anthropic": RateLimiter(RateLimitConfig(rpm=10, tpm=40000)),
            "gemini": RateLimiter(RateLimitConfig(rpm=15, tpm=30000)),

            # Default fallback
            "default": RateLimiter(RateLimitConfig(rpm=10, tpm=10000)),
        }

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
        Acquire rate limit permission for a provider.

        Args:
            provider: Provider name (e.g., "openai", "azure")
            tokens: Number of tokens to reserve

        Raises:
            asyncio.TimeoutError: If rate limit cannot be acquired within timeout
        """
        limiter = self._limiters.get(provider.lower(), self._limiters["default"])
        await limiter.acquire(tokens=tokens)

    def get_limiter(self, provider: str = "default") -> RateLimiter:
        """
        Get the rate limiter for a specific provider.

        Args:
            provider: Provider name

        Returns:
            RateLimiter instance for the provider
        """
        return self._limiters.get(provider.lower(), self._limiters["default"])

    def get_stats(self, provider: str = "default") -> dict:
        """
        Get current rate limit statistics for a provider.

        Args:
            provider: Provider name

        Returns:
            Dictionary with current rate limit stats
        """
        limiter = self._limiters.get(provider.lower(), self._limiters["default"])
        return {
            "provider": provider,
            "rpm": limiter.config.rpm,
            "tpm": limiter.config.tpm,
        }
