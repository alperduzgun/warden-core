"""
Provider Speed Benchmark Service

Measures local LLM provider throughput at runtime and calculates a safe
max_tokens budget that fits within the phase timeout.

Cloud providers (Groq, OpenAI, Anthropic, etc.) are bypassed — they are
fast enough that the static config default is always fine.

Singleton pattern mirrors GlobalRateLimiter (global_rate_limiter.py).
"""

import asyncio
import os
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
    prefill_ms_per_token: float = 0.0  # ms to prefill 1 input token; 0 = unknown
    timed_out: bool = False  # True when result is derived from a benchmark timeout


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
    # Benchmark timeout: override via WARDEN_BENCHMARK_TIMEOUT env var.
    # Default: 30s in CI (model is pre-warmed by ci.yml warmup step),
    # 90s elsewhere (cold model on slow CPU may need ~60s for prefill).
    _IS_CI: bool = os.environ.get("CI", "").lower() == "true" or os.environ.get("GITHUB_ACTIONS", "").lower() == "true"
    BENCHMARK_TIMEOUT_S: float = float(
        os.environ.get(
            "WARDEN_BENCHMARK_TIMEOUT",
            "30"
            if (os.environ.get("CI", "").lower() == "true" or os.environ.get("GITHUB_ACTIONS", "").lower() == "true")
            else "90",
        )
    )
    BENCHMARK_TOKEN_COUNT: int = 20
    CACHE_TTL_S: float = 300.0  # 5 minutes
    MAX_TOKENS_CEILING: int = 4000
    MAX_TOKENS_FLOOR: int = 150  # 3b @ ~3 tok/s = ~50s; fits within 120s read_timeout

    # Read timeout constants (derived from BENCHMARK_TIMEOUT_S)
    READ_TIMEOUT_FLOOR_S: float = 30.0  # BENCHMARK_TIMEOUT_S / 3
    READ_TIMEOUT_DEFAULT_S: float = 120.0  # BENCHMARK_TIMEOUT_S + FLOOR
    READ_TIMEOUT_CEILING_S: float = 300.0  # 3 * BENCHMARK_TIMEOUT_S + FLOOR
    READ_TIMEOUT_SAFETY_MARGIN: float = 1.5

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
        """Stable key: 'provider_value@endpoint'.

        Unwraps orchestrated/wrapper clients (which expose no _endpoint) to
        reach the actual underlying provider so the key is stable and unique.
        """
        # Unwrap orchestrated client → use smart_client as the real provider
        actual = getattr(client, "smart_client", client)
        provider_raw: Any = getattr(actual, "provider", "unknown")
        provider_str = str(getattr(provider_raw, "value", provider_raw)).lower()
        endpoint = getattr(actual, "endpoint", getattr(actual, "_endpoint", ""))
        return f"{provider_str}@{endpoint}"

    @staticmethod
    def _calculate(tok_per_sec: float, timeout_s: float, apply_floor: bool = True) -> int:
        """
        Compute safe max_tokens given measured throughput and phase timeout.

        Formula: floor(tok_per_sec × timeout_s × SAFETY_MARGIN)
        Clamped to [MAX_TOKENS_CEILING] always; floor applied only when
        apply_floor=True (normal path).  Conservative timeout estimates skip
        the floor so the mathematically derived upper-bound is preserved.
        """
        cls = ProviderSpeedBenchmarkService
        if tok_per_sec <= 0:
            return cls.MAX_TOKENS_FLOOR if apply_floor else 1
        raw = int(tok_per_sec * timeout_s * cls.SAFETY_MARGIN)
        floor = cls.MAX_TOKENS_FLOOR if apply_floor else 1
        return min(cls.MAX_TOKENS_CEILING, max(floor, raw))

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

        tokens_produced = (
            response.completion_tokens
            if response.completion_tokens and response.completion_tokens > 0
            else max(1, len(response.content) // 4)
        )

        # Prefer Ollama's native eval_duration (excludes rate-limiter/network overhead)
        # over wall-clock time for a more accurate generation speed estimate.
        gen_ms = getattr(response, "generation_duration_ms", None)
        if gen_ms and gen_ms > 0:
            tok_per_sec = tokens_produced / (gen_ms / 1000)
        else:
            tok_per_sec = tokens_produced / max(elapsed, 0.001)

        # Prefill rate: ms needed to process each input token (from Ollama's stats).
        # Used to compute a read timeout that covers worst-case prefill before the
        # first output token is produced.
        prefill_ms = getattr(response, "prefill_duration_ms", None)
        prompt_toks = response.prompt_tokens or 0
        if prefill_ms and prefill_ms > 0 and prompt_toks > 0:
            prefill_ms_per_token = prefill_ms / prompt_toks
        else:
            prefill_ms_per_token = 0.0

        # safe_max_tokens stored with a fixed reference timeout; recalculated per call
        _default_phase_timeout = self.BENCHMARK_TIMEOUT_S + self.BENCHMARK_TIMEOUT_S / 3
        safe_max = self._calculate(tok_per_sec, _default_phase_timeout)

        result = ProviderSpeedResult(
            cache_key=cache_key,
            tok_per_sec=tok_per_sec,
            safe_max_tokens=safe_max,
            measured_at=time.monotonic(),
            prefill_ms_per_token=prefill_ms_per_token,
        )

        logger.info(
            "benchmark_complete",
            provider=cache_key,
            tok_per_sec=round(tok_per_sec, 1),
            prefill_ms_per_token=round(prefill_ms_per_token, 2),
            safe_max_tokens=safe_max,
            phase_timeout_s=_default_phase_timeout,
            elapsed_s=round(elapsed, 2),
        )

        return result

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_safe_read_timeout(
        self,
        cache_key: str,
        estimated_prompt_tokens: int,
        safety_margin: float | None = None,
    ) -> float:
        """Compute a read timeout that covers prefill for *estimated_prompt_tokens*.

        Formula: prefill_s × safety_margin + floor
        """
        margin = safety_margin if safety_margin is not None else self.READ_TIMEOUT_SAFETY_MARGIN
        floor = self.READ_TIMEOUT_FLOOR_S
        default = self.READ_TIMEOUT_DEFAULT_S
        ceiling = self.READ_TIMEOUT_CEILING_S

        if cache_key not in self._cache:
            return default
        result, _ = self._cache[cache_key]
        if result.prefill_ms_per_token <= 0:
            return default
        prefill_s = result.prefill_ms_per_token * estimated_prompt_tokens / 1000
        total = prefill_s * margin + floor
        return min(ceiling, max(floor, total))

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
                # Preserve apply_floor=False for timeout-derived entries so the
                # conservative upper-bound is not overridden by MAX_TOKENS_FLOOR.
                safe = self._calculate(result.tok_per_sec, phase_timeout_s, apply_floor=not result.timed_out)
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
                    return self._calculate(result.tok_per_sec, phase_timeout_s, apply_floor=not result.timed_out)

            try:
                result = await asyncio.wait_for(
                    self._run_benchmark_async(client),
                    timeout=self.BENCHMARK_TIMEOUT_S,
                )
                self._cache[cache_key] = (result, time.monotonic())
                return self._calculate(result.tok_per_sec, phase_timeout_s)

            except Exception as exc:
                # asyncio.TimeoutError.__str__() returns '' — show type name instead.
                reason = str(exc) or type(exc).__name__

                # Benchmark timed out: Ollama generated < BENCHMARK_TOKEN_COUNT tokens
                # in BENCHMARK_TIMEOUT_S seconds.  We have an upper-bound on tok/s:
                #   tok/s_max = BENCHMARK_TOKEN_COUNT / BENCHMARK_TIMEOUT_S
                # Use that to compute a conservative safe budget rather than the full
                # default, which would cause the actual phase call to time out too.
                # asyncio.TimeoutError is a subclass of TimeoutError in Python 3.11+
                # but NOT in Python 3.10 (there it inherits from concurrent.futures.TimeoutError).
                # Use asyncio.TimeoutError directly for cross-version compatibility.
                if isinstance(exc, asyncio.TimeoutError):
                    conservative_tok_per_sec = self.BENCHMARK_TOKEN_COUNT / self.BENCHMARK_TIMEOUT_S
                    conservative = self._calculate(
                        conservative_tok_per_sec,
                        phase_timeout_s,
                        apply_floor=False,  # floor would override the measured upper-bound
                    )
                    # Cache a synthetic result so subsequent phases (e.g. CLASSIFICATION
                    # after ANALYSIS) reuse the conservative budget directly instead of
                    # re-running the already-known-failing 30s benchmark probe.
                    # timed_out=True preserves apply_floor=False on cache hits.
                    self._cache[cache_key] = (
                        ProviderSpeedResult(
                            cache_key=cache_key,
                            tok_per_sec=conservative_tok_per_sec,
                            safe_max_tokens=conservative,
                            measured_at=time.monotonic(),
                            timed_out=True,
                        ),
                        time.monotonic(),
                    )
                    logger.warning(
                        "benchmark_failed",
                        provider=cache_key,
                        reason=reason,
                        fallback=conservative,
                        note="timeout→conservative_budget",
                    )
                    return conservative

                logger.warning(
                    "benchmark_failed",
                    provider=cache_key,
                    reason=reason,
                    fallback=default_max_tokens,
                )
                return default_max_tokens


def get_benchmark_service() -> ProviderSpeedBenchmarkService:
    """Module-level sync factory (mirrors get_global_metrics_collector)."""
    return ProviderSpeedBenchmarkService.get_instance()
