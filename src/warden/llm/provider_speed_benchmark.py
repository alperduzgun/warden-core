"""
Provider Speed Benchmark Service

Measures local LLM provider throughput at runtime and calculates a safe
max_tokens budget that fits within the phase timeout.

Cloud providers (Groq, OpenAI, Anthropic, etc.) are bypassed — they are
fast enough that the static config default is always fine.

Singleton pattern mirrors GlobalRateLimiter (global_rate_limiter.py).
"""

import asyncio
import threading
import time
from dataclasses import dataclass
from typing import Any

from warden.llm.types import LlmRequest
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)

# Module-level threading lock — safe across event loops (same as GlobalRateLimiter)
_init_lock = threading.Lock()


@dataclass(frozen=True)
class ProviderSpeedResult:
    """Immutable value object for a single benchmark measurement."""

    cache_key: str
    tok_per_sec: float
    safe_max_tokens: int
    measured_at: float  # time.monotonic()


class ProviderSpeedBenchmarkService:
    """
    Singleton service that benchmarks local LLM throughput and computes a
    safe max_tokens budget for a given phase timeout.

    Cloud providers are bypassed immediately — no measurement overhead.

    Thread-safe singleton initialization (threading.Lock double-check).
    Async-safe benchmark execution (asyncio.Lock per service instance).

    Usage:
        svc = ProviderSpeedBenchmarkService.get_instance()
        tokens = await svc.get_safe_max_tokens(client, timeout_s=120, default=800)
    """

    # Tuning constants
    SAFETY_MARGIN: float = 0.75
    BENCHMARK_TIMEOUT_S: float = 30.0
    BENCHMARK_TOKEN_COUNT: int = 20
    CACHE_TTL_S: float = 300.0  # 5 minutes
    MAX_TOKENS_CEILING: int = 4000
    MAX_TOKENS_FLOOR: int = 100

    # Providers where throughput measurement makes sense
    _LOCAL_PROVIDER_VALUES: frozenset[str] = frozenset({"ollama", "claude_code", "codex"})

    _instance: "ProviderSpeedBenchmarkService | None" = None

    def __init__(self) -> None:
        if ProviderSpeedBenchmarkService._instance is not None:
            raise RuntimeError("Use ProviderSpeedBenchmarkService.get_instance() instead")
        self._cache: dict[str, tuple[ProviderSpeedResult, float]] = {}
        # Lazily created — ensures the correct running event loop is used
        self._benchmark_lock: asyncio.Lock | None = None

    # ------------------------------------------------------------------
    # Singleton lifecycle
    # ------------------------------------------------------------------

    @classmethod
    def get_instance(cls) -> "ProviderSpeedBenchmarkService":
        """Get or create the singleton instance (thread-safe double-check)."""
        if cls._instance is not None:
            return cls._instance
        with _init_lock:
            if cls._instance is None:
                cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton (test isolation only)."""
        with _init_lock:
            cls._instance = None

    # ------------------------------------------------------------------
    # Async lock (lazy init)
    # ------------------------------------------------------------------

    async def _get_lock(self) -> asyncio.Lock:
        """Return the asyncio.Lock, creating it lazily on first call."""
        if self._benchmark_lock is None:
            self._benchmark_lock = asyncio.Lock()
        return self._benchmark_lock

    # ------------------------------------------------------------------
    # Pure helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_local_provider(client: Any) -> bool:
        """
        Return True for Ollama, Claude Code, Codex, or localhost endpoints.

        Checks the provider enum/string value first, then falls back to
        inspecting the endpoint URL for loopback addresses.
        """
        provider_raw: Any = getattr(client, "provider", "")
        # getattr handles both enum (.value) and plain string providers
        provider_str = str(getattr(provider_raw, "value", provider_raw)).lower()

        if provider_str in ProviderSpeedBenchmarkService._LOCAL_PROVIDER_VALUES:
            return True

        # Detect generic local HTTP endpoint (LMStudio, LocalAI, etc.)
        endpoint = getattr(client, "endpoint", getattr(client, "_endpoint", ""))
        str_endpoint = str(endpoint).lower()
        return any(loopback in str_endpoint for loopback in ("localhost", "127.0.0.1", "::1", "0:0:0:0:0:0:0:1"))

    @staticmethod
    def _get_cache_key(client: Any) -> str:
        """Stable key: 'provider_value@endpoint'."""
        provider_raw: Any = getattr(client, "provider", "unknown")
        provider_str = str(getattr(provider_raw, "value", provider_raw)).lower()
        endpoint = getattr(client, "endpoint", getattr(client, "_endpoint", ""))
        return f"{provider_str}@{endpoint}"

    @staticmethod
    def _calculate(tok_per_sec: float, timeout_s: float) -> int:
        """
        Compute safe max_tokens given measured throughput and phase timeout.

        Formula: floor(tok_per_sec × timeout_s × SAFETY_MARGIN)
        Clamped to [MAX_TOKENS_FLOOR, MAX_TOKENS_CEILING].
        """
        cls = ProviderSpeedBenchmarkService
        if tok_per_sec <= 0:
            return cls.MAX_TOKENS_FLOOR
        raw = int(tok_per_sec * timeout_s * cls.SAFETY_MARGIN)
        return min(cls.MAX_TOKENS_CEILING, max(cls.MAX_TOKENS_FLOOR, raw))

    # ------------------------------------------------------------------
    # I/O core
    # ------------------------------------------------------------------

    async def _run_benchmark_async(self, client: Any) -> ProviderSpeedResult:
        """
        Send a minimal request to measure tokens/second.

        Uses client.send_async() directly (no complete_async wrapper) to
        avoid ExternalServiceError masking actual benchmark errors.

        Token count: completion_tokens from response if available, else
        len(content) // 4 heuristic.
        """
        cache_key = self._get_cache_key(client)
        request = LlmRequest(
            system_prompt="Respond with a short sentence.",
            user_message="Say 'hello world' in 3 different ways.",
            max_tokens=self.BENCHMARK_TOKEN_COUNT,
            timeout_seconds=self.BENCHMARK_TIMEOUT_S,
            use_fast_tier=True,
        )

        t0 = time.monotonic()
        response = await client.send_async(request)
        elapsed = time.monotonic() - t0

        if response.completion_tokens and response.completion_tokens > 0:
            tokens_produced = response.completion_tokens
        else:
            tokens_produced = max(1, len(response.content) // 4)

        tok_per_sec = tokens_produced / max(elapsed, 0.001)
        # safe_max_tokens stored with a fixed reference timeout; recalculated per call
        safe_max = self._calculate(tok_per_sec, 120.0)

        result = ProviderSpeedResult(
            cache_key=cache_key,
            tok_per_sec=tok_per_sec,
            safe_max_tokens=safe_max,
            measured_at=time.monotonic(),
        )

        logger.info(
            "benchmark_complete",
            provider=cache_key,
            tok_per_sec=round(tok_per_sec, 1),
            safe_max_tokens=safe_max,
            phase_timeout_s=120.0,
            elapsed_s=round(elapsed, 2),
        )

        return result

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_safe_max_tokens(
        self,
        client: Any,
        phase_timeout_s: float,
        default_max_tokens: int,
    ) -> int:
        """
        Return a max_tokens budget that fits within *phase_timeout_s*.

        - Cloud providers  → ``default_max_tokens`` (no benchmark overhead)
        - Local providers  → benchmark once, cache for CACHE_TTL_S
        - Any failure      → ``default_max_tokens`` (fail-safe fallback)
        """
        if not self._is_local_provider(client):
            return default_max_tokens

        cache_key = self._get_cache_key(client)
        now = time.monotonic()

        # Fast path: valid cache hit — no I/O
        if cache_key in self._cache:
            result, cached_at = self._cache[cache_key]
            age = now - cached_at
            if age < self.CACHE_TTL_S:
                safe = self._calculate(result.tok_per_sec, phase_timeout_s)
                logger.debug(
                    "benchmark_cache_hit",
                    provider=cache_key,
                    age_s=round(age, 1),
                    cached_max_tokens=safe,
                )
                return safe

        # Slow path: run benchmark (serialised per service instance)
        lock = await self._get_lock()
        async with lock:
            # Double-check after acquiring lock (another coroutine may have filled it)
            if cache_key in self._cache:
                result, cached_at = self._cache[cache_key]
                if time.monotonic() - cached_at < self.CACHE_TTL_S:
                    return self._calculate(result.tok_per_sec, phase_timeout_s)

            try:
                result = await asyncio.wait_for(
                    self._run_benchmark_async(client),
                    timeout=self.BENCHMARK_TIMEOUT_S,
                )
                self._cache[cache_key] = (result, time.monotonic())
                return self._calculate(result.tok_per_sec, phase_timeout_s)

            except Exception as exc:
                logger.warning(
                    "benchmark_failed",
                    provider=cache_key,
                    reason=str(exc),
                    fallback=default_max_tokens,
                )
                return default_max_tokens


def get_benchmark_service() -> ProviderSpeedBenchmarkService:
    """Module-level sync factory (mirrors get_global_metrics_collector)."""
    return ProviderSpeedBenchmarkService.get_instance()
