"""
Tests for ProviderSpeedBenchmarkService.

Covers:
1. _calculate — pure function, ceiling/floor clamping, zero speed
2. _is_local_provider — provider enum/string detection, localhost endpoints
3. Cache behaviour — hit skips benchmark, TTL expiry triggers new measurement
4. Singleton invariant — same object, reset_instance, thread safety
5. Chaos failure modes — exception, timeout, cloud bypass, concurrent dedup
6. End-to-end flow — full mock integration
"""

from __future__ import annotations

import asyncio
import threading
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from warden.llm.provider_speed_benchmark import (
    ProviderSpeedBenchmarkService,
    ProviderSpeedResult,
    get_benchmark_service,
)
from warden.llm.types import LlmProvider, LlmResponse

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset singleton before every test for isolation."""
    ProviderSpeedBenchmarkService.reset_instance()
    yield
    ProviderSpeedBenchmarkService.reset_instance()


def _make_ollama_client(tok_per_sec: float = 10.0, endpoint: str = "") -> MagicMock:
    """Return a mock client that looks like an Ollama provider."""
    client = MagicMock()
    client.provider = LlmProvider.OLLAMA
    tokens = max(1, int(tok_per_sec * 0.1))  # simulate ~100ms response
    response = LlmResponse(
        content="hello world " * tokens,
        success=True,
        provider=LlmProvider.OLLAMA,
        model="qwen",
        completion_tokens=tokens,
    )
    client.send_async = AsyncMock(return_value=response)
    if endpoint:
        client.endpoint = endpoint
    return client


def _make_groq_client() -> MagicMock:
    """Return a mock client that looks like a Groq (cloud) provider."""
    client = MagicMock()
    client.provider = LlmProvider.GROQ
    return client


# ---------------------------------------------------------------------------
# TestCalculate — pure function
# ---------------------------------------------------------------------------


class TestCalculate:
    def test_nominal(self):
        """10 tok/s × 120s × 0.75 = 900 tokens."""
        result = ProviderSpeedBenchmarkService._calculate(10.0, 120.0)
        assert result == 900

    def test_ceiling_cap(self):
        """Very fast provider should be capped at MAX_TOKENS_CEILING."""
        result = ProviderSpeedBenchmarkService._calculate(1000.0, 120.0)
        assert result == ProviderSpeedBenchmarkService.MAX_TOKENS_CEILING

    def test_floor(self):
        """Very slow provider (0.1 tok/s) should be clamped to MAX_TOKENS_FLOOR."""
        result = ProviderSpeedBenchmarkService._calculate(0.1, 10.0)
        assert result == ProviderSpeedBenchmarkService.MAX_TOKENS_FLOOR

    def test_zero_speed(self):
        """Zero speed returns the floor, never divides by zero."""
        result = ProviderSpeedBenchmarkService._calculate(0.0, 120.0)
        assert result == ProviderSpeedBenchmarkService.MAX_TOKENS_FLOOR

    def test_short_timeout(self):
        """Short timeout (30s) at slow provider: raw tokens below floor → clamped up."""
        result = ProviderSpeedBenchmarkService._calculate(2.0, 30.0)
        # 2 tok/s × 30s × 0.75 = 45 < MAX_TOKENS_FLOOR (150) → clamped up
        assert result == ProviderSpeedBenchmarkService.MAX_TOKENS_FLOOR


# ---------------------------------------------------------------------------
# TestIsLocalProvider
# ---------------------------------------------------------------------------


class TestIsLocalProvider:
    def test_ollama_enum(self):
        client = _make_ollama_client()
        assert ProviderSpeedBenchmarkService._is_local_provider(client) is True

    def test_claude_code_enum(self):
        client = MagicMock()
        client.provider = LlmProvider.CLAUDE_CODE
        assert ProviderSpeedBenchmarkService._is_local_provider(client) is True

    def test_codex_string(self):
        client = MagicMock()
        client.provider = "codex"
        assert ProviderSpeedBenchmarkService._is_local_provider(client) is True

    def test_groq_not_local(self):
        client = _make_groq_client()
        assert ProviderSpeedBenchmarkService._is_local_provider(client) is False

    def test_openai_not_local(self):
        client = MagicMock()
        client.provider = LlmProvider.OPENAI
        assert ProviderSpeedBenchmarkService._is_local_provider(client) is False

    def test_localhost_endpoint(self):
        """Generic local endpoint should be detected."""
        client = MagicMock()
        client.provider = LlmProvider.UNKNOWN
        client.endpoint = "http://localhost:11434"
        assert ProviderSpeedBenchmarkService._is_local_provider(client) is True

    def test_127_endpoint(self):
        client = MagicMock()
        client.provider = LlmProvider.UNKNOWN
        client.endpoint = "http://127.0.0.1:11434"
        assert ProviderSpeedBenchmarkService._is_local_provider(client) is True

    def test_remote_endpoint_not_local(self):
        client = MagicMock()
        client.provider = LlmProvider.UNKNOWN
        client.endpoint = "https://api.groq.com"
        assert ProviderSpeedBenchmarkService._is_local_provider(client) is False


# ---------------------------------------------------------------------------
# TestCacheBehaviour
# ---------------------------------------------------------------------------


class TestCacheBehaviour:
    @pytest.mark.asyncio
    async def test_cache_hit_skips_benchmark(self):
        """Second call should return cached result without calling send_async again."""
        client = _make_ollama_client(tok_per_sec=10.0)
        svc = ProviderSpeedBenchmarkService.get_instance()

        first = await svc.get_safe_max_tokens(client, phase_timeout_s=120.0, default_max_tokens=800)
        second = await svc.get_safe_max_tokens(client, phase_timeout_s=120.0, default_max_tokens=800)

        # send_async called exactly once despite two get_safe_max_tokens calls
        assert client.send_async.call_count == 1
        assert first == second

    @pytest.mark.asyncio
    async def test_ttl_expiry_triggers_new_benchmark(self):
        """Expired cache should trigger a fresh benchmark call."""
        client = _make_ollama_client(tok_per_sec=10.0)
        svc = ProviderSpeedBenchmarkService.get_instance()

        await svc.get_safe_max_tokens(client, phase_timeout_s=120.0, default_max_tokens=800)
        assert client.send_async.call_count == 1

        # Expire the cache entry
        cache_key = ProviderSpeedBenchmarkService._get_cache_key(client)
        result, _ = svc._cache[cache_key]
        svc._cache[cache_key] = (result, time.monotonic() - ProviderSpeedBenchmarkService.CACHE_TTL_S - 1)

        await svc.get_safe_max_tokens(client, phase_timeout_s=120.0, default_max_tokens=800)
        assert client.send_async.call_count == 2


# ---------------------------------------------------------------------------
# TestSingleton
# ---------------------------------------------------------------------------


class TestSingleton:
    def test_same_object(self):
        a = ProviderSpeedBenchmarkService.get_instance()
        b = ProviderSpeedBenchmarkService.get_instance()
        assert a is b

    def test_reset_creates_fresh(self):
        a = ProviderSpeedBenchmarkService.get_instance()
        ProviderSpeedBenchmarkService.reset_instance()
        b = ProviderSpeedBenchmarkService.get_instance()
        assert a is not b

    def test_direct_init_raises(self):
        ProviderSpeedBenchmarkService.get_instance()  # create singleton
        with pytest.raises(RuntimeError, match="get_instance"):
            ProviderSpeedBenchmarkService()

    def test_thread_safety_20_threads(self):
        """20 concurrent threads must all receive the same singleton."""
        results: list[ProviderSpeedBenchmarkService] = []
        lock = threading.Lock()

        def get_it():
            inst = ProviderSpeedBenchmarkService.get_instance()
            with lock:
                results.append(inst)

        threads = [threading.Thread(target=get_it) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 20
        assert all(r is results[0] for r in results)

    def test_get_benchmark_service_factory(self):
        inst = get_benchmark_service()
        assert isinstance(inst, ProviderSpeedBenchmarkService)
        assert inst is get_benchmark_service()


# ---------------------------------------------------------------------------
# TestChaosFailureModes
# ---------------------------------------------------------------------------


class TestChaosFailureModes:
    @pytest.mark.asyncio
    async def test_benchmark_timeout_returns_conservative_budget(self):
        """Benchmark TimeoutError → conservative upper-bound, NOT the full default.

        Simulates the real CI scenario: Ollama cold-starts and the benchmark
        call raises TimeoutError (BENCHMARK_TIMEOUT_S=30, TOKEN_COUNT=20).

        Upper-bound tok/s = 20/30 ≈ 0.67.  apply_floor=False is used so the
        mathematically derived budget (int(0.67×120×0.75) = 60) is preserved
        without the MAX_TOKENS_FLOOR override.
        Returning default (800) would cause the real phase call to time out too.
        """
        client = MagicMock()
        client.provider = LlmProvider.OLLAMA
        # Inject TimeoutError directly — no need to actually wait
        client.send_async = AsyncMock(side_effect=asyncio.TimeoutError())

        svc = ProviderSpeedBenchmarkService.get_instance()
        # conservative = _calculate(20/30, 120.0, apply_floor=False)
        #              = int(0.667 × 120 × 0.75) = 60
        result = await svc.get_safe_max_tokens(client, phase_timeout_s=120.0, default_max_tokens=800)

        conservative_expected = int((svc.BENCHMARK_TOKEN_COUNT / svc.BENCHMARK_TIMEOUT_S) * 120.0 * svc.SAFETY_MARGIN)
        assert result < 800  # conservative, not full budget
        assert result == conservative_expected  # derived upper-bound (apply_floor=False)

    @pytest.mark.asyncio
    async def test_benchmark_timeout_caches_result(self):
        """Benchmark TimeoutError result is cached so subsequent phases skip re-benchmarking.

        Real scenario: ANALYSIS phase benchmark times out → CLASSIFICATION phase
        should hit cache and NOT run the benchmark probe again.
        """
        client = MagicMock()
        client.provider = LlmProvider.OLLAMA
        client.send_async = AsyncMock(side_effect=asyncio.TimeoutError())

        svc = ProviderSpeedBenchmarkService.get_instance()
        cache_key = ProviderSpeedBenchmarkService._get_cache_key(client)

        # First call — benchmark times out
        first = await svc.get_safe_max_tokens(client, phase_timeout_s=120.0, default_max_tokens=800)

        # Cache must be populated after a timeout
        assert cache_key in svc._cache, "Timeout result must be cached to prevent re-benchmarking"

        # Second call (simulates next pipeline phase) — must hit cache, not re-run benchmark
        second = await svc.get_safe_max_tokens(client, phase_timeout_s=120.0, default_max_tokens=800)
        assert client.send_async.call_count == 1  # benchmark ran exactly once
        assert first == second

    @pytest.mark.asyncio
    async def test_non_timeout_exception_returns_default(self):
        """Non-timeout exception (e.g. connection refused) → return default_max_tokens.

        Only TimeoutError implies we know an upper bound on speed.
        For other failures we have no speed information, so fall back to default.
        """
        client = MagicMock()
        client.provider = LlmProvider.OLLAMA
        client.send_async = AsyncMock(side_effect=RuntimeError("connection refused"))

        svc = ProviderSpeedBenchmarkService.get_instance()
        result = await svc.get_safe_max_tokens(client, phase_timeout_s=120.0, default_max_tokens=800)
        assert result == 800

    @pytest.mark.asyncio
    async def test_cloud_provider_bypass(self):
        """Cloud provider → default_max_tokens returned, send_async never called."""
        client = _make_groq_client()
        svc = ProviderSpeedBenchmarkService.get_instance()
        result = await svc.get_safe_max_tokens(client, phase_timeout_s=120.0, default_max_tokens=800)
        assert result == 800
        # send_async should not even exist on this mock, but let's verify nothing called
        assert not hasattr(client, "send_async") or not client.send_async.called

    @pytest.mark.asyncio
    async def test_ceiling_cap_applied(self):
        """Extremely fast provider → capped at MAX_TOKENS_CEILING."""
        # 2000 tok/s × 120s × 0.75 = 180000 → should cap at 4000
        client = _make_ollama_client(tok_per_sec=2000.0)

        svc = ProviderSpeedBenchmarkService.get_instance()
        # Patch elapsed to 0.01s so tok/s is huge
        call_count = 0

        def fake_monotonic():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return 0.0
            return 0.01  # 10ms elapsed → massive tok/s

        with patch("warden.llm.provider_speed_benchmark.time.monotonic", side_effect=fake_monotonic):
            result = await svc.get_safe_max_tokens(client, phase_timeout_s=120.0, default_max_tokens=800)

        assert result == ProviderSpeedBenchmarkService.MAX_TOKENS_CEILING

    @pytest.mark.asyncio
    async def test_floor_applied_for_slow_provider(self):
        """Very slow provider → floored at MAX_TOKENS_FLOOR."""
        client = MagicMock()
        client.provider = LlmProvider.OLLAMA
        # 1 token in 100 seconds → 0.01 tok/s
        response = LlmResponse(
            content="hi",
            success=True,
            provider=LlmProvider.OLLAMA,
            model="tiny",
            completion_tokens=1,
        )
        client.send_async = AsyncMock(return_value=response)

        svc = ProviderSpeedBenchmarkService.get_instance()
        call_count = 0

        def fake_monotonic():
            nonlocal call_count
            call_count += 1
            return float(call_count * 100)  # 100s elapsed

        with patch("warden.llm.provider_speed_benchmark.time.monotonic", side_effect=fake_monotonic):
            result = await svc.get_safe_max_tokens(client, phase_timeout_s=120.0, default_max_tokens=800)

        assert result == ProviderSpeedBenchmarkService.MAX_TOKENS_FLOOR

    @pytest.mark.asyncio
    async def test_concurrent_calls_deduplicated(self):
        """Multiple concurrent calls → only one benchmark executed."""
        call_count = 0

        async def counting_send(_request):
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.05)  # simulate short I/O delay
            return LlmResponse(
                content="hello",
                success=True,
                provider=LlmProvider.OLLAMA,
                model="qwen",
                completion_tokens=5,
            )

        client = MagicMock()
        client.provider = LlmProvider.OLLAMA
        client.send_async = counting_send

        svc = ProviderSpeedBenchmarkService.get_instance()
        tasks = [svc.get_safe_max_tokens(client, phase_timeout_s=120.0, default_max_tokens=800) for _ in range(5)]
        results = await asyncio.gather(*tasks)

        # All results should be equal (same cached value)
        assert len(set(results)) == 1
        # Benchmark should have run exactly once
        assert call_count == 1


# ---------------------------------------------------------------------------
# TestEndToEnd
# ---------------------------------------------------------------------------


class TestEndToEnd:
    @pytest.mark.asyncio
    async def test_full_flow_10_tok_per_sec(self):
        """
        Verify the complete flow:
        - Benchmark runs via send_async
        - Result is cached
        - Returned max_tokens uses _calculate
        """
        # 10 tokens produced in 1 second = 10 tok/s
        client = MagicMock()
        client.provider = LlmProvider.OLLAMA
        response = LlmResponse(
            content="hello world x10",
            success=True,
            provider=LlmProvider.OLLAMA,
            model="qwen",
            completion_tokens=10,
        )
        client.send_async = AsyncMock(return_value=response)

        call_count = 0

        def fake_monotonic():
            nonlocal call_count
            call_count += 1
            return float(call_count)  # 1s elapsed per call

        with patch("warden.llm.provider_speed_benchmark.time.monotonic", side_effect=fake_monotonic):
            svc = ProviderSpeedBenchmarkService.get_instance()
            result = await svc.get_safe_max_tokens(client, phase_timeout_s=120.0, default_max_tokens=800)

        expected = ProviderSpeedBenchmarkService._calculate(10.0, 120.0)  # 900
        assert result == expected
        assert client.send_async.call_count == 1

    def test_provider_speed_result_is_frozen(self):
        """ProviderSpeedResult must be immutable (frozen dataclass)."""
        r = ProviderSpeedResult(
            cache_key="ollama@",
            tok_per_sec=10.0,
            safe_max_tokens=900,
            measured_at=0.0,
        )
        with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
            r.tok_per_sec = 999.0  # type: ignore[misc]

    def test_provider_speed_result_prefill_default(self):
        """prefill_ms_per_token defaults to 0.0 when not supplied."""
        r = ProviderSpeedResult(
            cache_key="ollama@http://localhost:11434",
            tok_per_sec=5.0,
            safe_max_tokens=450,
            measured_at=0.0,
        )
        assert r.prefill_ms_per_token == 0.0


# ---------------------------------------------------------------------------
# TestGetSafeReadTimeout
# ---------------------------------------------------------------------------


class TestGetSafeReadTimeout:
    def _seed_cache(self, svc: ProviderSpeedBenchmarkService, cache_key: str, prefill_ms_per_token: float) -> None:
        """Insert a cached result directly into the service cache."""
        result = ProviderSpeedResult(
            cache_key=cache_key,
            tok_per_sec=10.0,
            safe_max_tokens=900,
            measured_at=time.monotonic(),
            prefill_ms_per_token=prefill_ms_per_token,
        )
        svc._cache[cache_key] = (result, time.monotonic())

    def test_no_cache_returns_default(self):
        """No cache entry → 120.0 (original hardcoded default)."""
        svc = ProviderSpeedBenchmarkService.get_instance()
        result = svc.get_safe_read_timeout("ollama@http://localhost:11434", estimated_prompt_tokens=1000)
        assert result == 120.0

    def test_zero_prefill_returns_default(self):
        """prefill_ms_per_token == 0 → 120.0 (unknown, use safe default)."""
        svc = ProviderSpeedBenchmarkService.get_instance()
        self._seed_cache(svc, "ollama@http://localhost:11434", prefill_ms_per_token=0.0)
        result = svc.get_safe_read_timeout("ollama@http://localhost:11434", estimated_prompt_tokens=1000)
        assert result == 120.0

    def test_formula(self):
        """Verify formula: prefill_ms × tokens × margin / 1000 + 30s.

        prefill_ms_per_token=10ms, tokens=1000, margin=1.5:
        10 × 1000 × 1.5 / 1000 + 30 = 15 + 30 = 45 s
        """
        svc = ProviderSpeedBenchmarkService.get_instance()
        self._seed_cache(svc, "ollama@http://localhost:11434", prefill_ms_per_token=10.0)
        result = svc.get_safe_read_timeout("ollama@http://localhost:11434", estimated_prompt_tokens=1000)
        assert result == pytest.approx(45.0, abs=0.01)

    def test_ceiling_300s(self):
        """Very slow prefill → capped at 300 s."""
        svc = ProviderSpeedBenchmarkService.get_instance()
        # 500 ms/token × 2000 tokens × 1.5 / 1000 + 30 = 1530s → capped at 300
        self._seed_cache(svc, "ollama@http://localhost:11434", prefill_ms_per_token=500.0)
        result = svc.get_safe_read_timeout("ollama@http://localhost:11434", estimated_prompt_tokens=2000)
        assert result == 300.0

    def test_floor_30s(self):
        """Near-zero prefill → floored at 30 s (still need time for generation)."""
        svc = ProviderSpeedBenchmarkService.get_instance()
        # 0.001 ms/token × 100 tokens × 1.5 / 1000 + 30 ≈ 30s
        self._seed_cache(svc, "ollama@http://localhost:11434", prefill_ms_per_token=0.001)
        result = svc.get_safe_read_timeout("ollama@http://localhost:11434", estimated_prompt_tokens=100)
        assert result >= 30.0

    def test_custom_safety_margin(self):
        """Custom margin applies correctly."""
        svc = ProviderSpeedBenchmarkService.get_instance()
        self._seed_cache(svc, "ollama@http://localhost:11434", prefill_ms_per_token=10.0)
        # 10 × 1000 × 2.0 / 1000 + 30 = 50 s
        result = svc.get_safe_read_timeout(
            "ollama@http://localhost:11434",
            estimated_prompt_tokens=1000,
            safety_margin=2.0,
        )
        assert result == pytest.approx(50.0, abs=0.01)


# ---------------------------------------------------------------------------
# TestNativeStats — benchmark uses Ollama's generation_duration_ms
# ---------------------------------------------------------------------------


class TestNativeStats:
    @pytest.mark.asyncio
    async def test_native_generation_stats_used_for_tok_per_sec(self):
        """When response carries generation_duration_ms, use it instead of wall-clock.

        Wall-clock elapsed is 5 s (includes rate-limiter overhead).
        Native gen_ms = 1000 ms → true 10 tok/s.
        Without native stats: tok/s = 10 / 5 = 2 → would underestimate.
        """
        client = MagicMock()
        client.provider = LlmProvider.OLLAMA
        response = LlmResponse(
            content="hi " * 10,
            success=True,
            provider=LlmProvider.OLLAMA,
            model="qwen",
            completion_tokens=10,
            generation_duration_ms=1000.0,  # 1 s native → 10 tok/s
            prefill_duration_ms=None,
        )
        client.send_async = AsyncMock(return_value=response)

        svc = ProviderSpeedBenchmarkService.get_instance()

        call_count = 0

        def fake_monotonic():
            nonlocal call_count
            call_count += 1
            return float(call_count * 5)  # 5s wall-clock gap

        with patch("warden.llm.provider_speed_benchmark.time.monotonic", side_effect=fake_monotonic):
            result_tokens = await svc.get_safe_max_tokens(client, phase_timeout_s=120.0, default_max_tokens=800)

        # Should use native 10 tok/s, not wall-clock 2 tok/s
        expected = ProviderSpeedBenchmarkService._calculate(10.0, 120.0)  # 900
        assert result_tokens == expected

    @pytest.mark.asyncio
    async def test_prefill_stats_stored_in_result(self):
        """When response carries prefill_duration_ms + prompt_tokens, prefill rate is stored."""
        client = MagicMock()
        client.provider = LlmProvider.OLLAMA
        # 500 ms to prefill 50 input tokens → 10 ms/token
        response = LlmResponse(
            content="hello",
            success=True,
            provider=LlmProvider.OLLAMA,
            model="qwen",
            completion_tokens=5,
            prompt_tokens=50,
            prefill_duration_ms=500.0,
            generation_duration_ms=None,
        )
        client.send_async = AsyncMock(return_value=response)

        svc = ProviderSpeedBenchmarkService.get_instance()
        await svc.get_safe_max_tokens(client, phase_timeout_s=120.0, default_max_tokens=800)

        cache_key = svc._get_cache_key(client)
        stored_result, _ = svc._cache[cache_key]
        assert stored_result.prefill_ms_per_token == pytest.approx(10.0, abs=0.01)

    @pytest.mark.asyncio
    async def test_wall_clock_fallback_when_no_native_stats(self):
        """No native stats → wall-clock elapsed used (existing behaviour preserved)."""
        client = MagicMock()
        client.provider = LlmProvider.OLLAMA
        response = LlmResponse(
            content="hello",
            success=True,
            provider=LlmProvider.OLLAMA,
            model="qwen",
            completion_tokens=10,
            # No generation_duration_ms / prefill_duration_ms
        )
        client.send_async = AsyncMock(return_value=response)

        svc = ProviderSpeedBenchmarkService.get_instance()

        call_count = 0

        def fake_monotonic():
            nonlocal call_count
            call_count += 1
            return float(call_count)  # 1s elapsed

        with patch("warden.llm.provider_speed_benchmark.time.monotonic", side_effect=fake_monotonic):
            await svc.get_safe_max_tokens(client, phase_timeout_s=120.0, default_max_tokens=800)

        cache_key = svc._get_cache_key(client)
        stored_result, _ = svc._cache[cache_key]
        # Wall-clock: 10 tokens / 1s = 10 tok/s
        assert stored_result.tok_per_sec == pytest.approx(10.0, abs=0.1)
        # No native prefill data → 0.0
        assert stored_result.prefill_ms_per_token == 0.0
