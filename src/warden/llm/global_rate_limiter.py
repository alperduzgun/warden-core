"""
Global Rate Limiter Singleton

Provides a thread-safe global rate limiter for all LLM providers.
Prevents rate limit violations across the entire application.

Issue #17 Fix: Global rate limiting implementation
"""

import asyncio
from typing import Dict, Optional
from warden.llm.rate_limiter import RateLimiter


class GlobalRateLimiter:
    """
    Singleton global rate limiter for all LLM API calls.

    Usage:
        limiter = GlobalRateLimiter.get_instance()
        await limiter.acquire("openai", tokens=1000)
    """

    _instance: Optional["GlobalRateLimiter"] = None
    _lock = asyncio.Lock()

    def __init__(self):
        """Initialize global rate limiter with provider-specific limits."""
        if GlobalRateLimiter._instance is not None:
            raise RuntimeError("Use GlobalRateLimiter.get_instance() instead")

        # Provider-specific rate limiters
        self._limiters: Dict[str, RateLimiter] = {
            # Fast tier providers (high limits)
            "qwen": RateLimiter(max_requests_per_minute=60, max_tokens_per_minute=100000),
            "ollama": RateLimiter(max_requests_per_minute=60, max_tokens_per_minute=100000),

            # Smart tier providers (conservative limits)
            "openai": RateLimiter(max_requests_per_minute=10, max_tokens_per_minute=40000),
            "azure": RateLimiter(max_requests_per_minute=10, max_tokens_per_minute=40000),
            "anthropic": RateLimiter(max_requests_per_minute=10, max_tokens_per_minute=40000),
            "gemini": RateLimiter(max_requests_per_minute=15, max_tokens_per_minute=30000),

            # Default fallback
            "default": RateLimiter(max_requests_per_minute=10, max_tokens_per_minute=10000),
        }

    @classmethod
    async def get_instance(cls) -> "GlobalRateLimiter":
        """
        Get or create the global rate limiter instance (thread-safe).

        Returns:
            Singleton instance of GlobalRateLimiter
        """
        if cls._instance is None:
            async with cls._lock:
                if cls._instance is None:  # Double-check locking
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance (for testing purposes)."""
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
        await limiter.acquire_async(tokens=tokens)

    def get_limiter(self, provider: str = "default") -> RateLimiter:
        """
        Get the rate limiter for a specific provider.

        Args:
            provider: Provider name

        Returns:
            RateLimiter instance for the provider
        """
        return self._limiters.get(provider.lower(), self._limiters["default"])

    def get_stats(self, provider: str = "default") -> Dict:
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
            "max_requests_per_minute": limiter.max_requests_per_minute,
            "max_tokens_per_minute": limiter.max_tokens_per_minute,
            "current_requests": limiter.request_count,
            "current_tokens": limiter.token_count,
        }
