"""
Global Rate Limiter Singleton

Provides a thread-safe global rate limiter for all LLM providers.
Prevents rate limit violations across the entire application.

Issue #17 Fix: Global rate limiting implementation
Issue #429 Fix: Wire LlmConfiguration tpm_limit/rpm_limit into GlobalRateLimiter
"""

import asyncio
import logging
import threading
from typing import TYPE_CHECKING, Optional

from warden.llm.rate_limiter import RateLimitConfig, RateLimiter

if TYPE_CHECKING:
    from warden.llm.config import LlmConfiguration

_logger = logging.getLogger(__name__)

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
            "qwen": RateLimiter(RateLimitConfig(rpm=60, tpm=100000)),      # qwencode (local DashScope)
            "qwen_cloud": RateLimiter(RateLimitConfig(rpm=60, tpm=100000)),  # Qwen Cloud (OpenAI-compat)
            "ollama": RateLimiter(RateLimitConfig(rpm=60, tpm=100000)),
            # Smart tier providers (conservative limits)
            "groq": RateLimiter(RateLimitConfig(rpm=30, tpm=6000)),
            "openai": RateLimiter(RateLimitConfig(rpm=10, tpm=40000)),
            "azure": RateLimiter(RateLimitConfig(rpm=10, tpm=40000)),
            "anthropic": RateLimiter(RateLimitConfig(rpm=10, tpm=40000)),
            "gemini": RateLimiter(RateLimitConfig(rpm=15, tpm=30000)),
            # Default fallback
            "default": RateLimiter(RateLimitConfig(rpm=10, tpm=10000)),
        }

        # Concurrency Semaphores (Chaos Engineering: Resource Isolation)
        # Prevents local LLM (Ollama) from thrashing CPU with too many parallel batches.
        # Initialized lazily to ensure correct event loop binding.
        self._semaphores: dict[str, asyncio.Semaphore] = {}

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
        limiter = self._limiters.get(provider_key, self._limiters["default"])

        # 1. Acquire Token/RPM Rate Limit
        await limiter.acquire(tokens=tokens)

        # Concurrency enforcement for local providers is handled by callers
        # via `concurrency_limit()` + `async with sem:` pattern (see OllamaClient).

    def _get_semaphore(self, provider: str, limit: int = 1) -> asyncio.Semaphore:
        """Get or create an asyncio semaphore for a provider."""
        if provider not in self._semaphores:
            self._semaphores[provider] = asyncio.Semaphore(limit)
        return self._semaphores[provider]

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
        Get the rate limiter for a specific provider.

        Args:
            provider: Provider name

        Returns:
            RateLimiter instance for the provider
        """
        return self._limiters.get(provider.lower(), self._limiters["default"])

    def configure_from_llm_config(self, config: "LlmConfiguration") -> None:
        """Update the default rate limiter limits from LlmConfiguration.

        Applies ``config.tpm_limit`` and ``config.rpm_limit`` to the
        ``"default"`` bucket so that project-level config.yaml settings
        (e.g. free-tier 6 rpm / 1000 tpm) take effect globally.

        If ``config.provider_rate_limits`` is set, also updates the matching
        provider-specific buckets.  Unknown provider keys are silently ignored
        (they will receive the default bucket at runtime).

        Args:
            config: Loaded LlmConfiguration instance.
        """
        tpm = max(1, config.tpm_limit)
        rpm = max(1, config.rpm_limit)
        self._limiters["default"] = RateLimiter(RateLimitConfig(tpm=tpm, rpm=rpm))
        _logger.debug(
            "global_rate_limiter_configured",
            tpm_limit=tpm,
            rpm_limit=rpm,
        )

        # Update provider-specific limits from config if provided
        provider_limits = getattr(config, "provider_rate_limits", None)
        if provider_limits and isinstance(provider_limits, dict):
            for provider_key, limits in provider_limits.items():
                if provider_key in self._limiters:
                    existing = self._limiters[provider_key]
                    new_tpm = limits.get("tpm", existing.config.tpm)
                    new_rpm = limits.get("rpm", existing.config.rpm)
                    self._limiters[provider_key] = RateLimiter(
                        RateLimitConfig(tpm=new_tpm, rpm=new_rpm)
                    )
                    _logger.info(
                        "provider_rate_limit_configured",
                        provider=provider_key,
                        tpm=new_tpm,
                        rpm=new_rpm,
                    )

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
