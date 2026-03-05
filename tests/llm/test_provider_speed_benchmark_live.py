"""
Live smoke test: ProviderSpeedBenchmarkService vs real Ollama (qwen2.5-coder:3b).

Skipped automatically if Ollama is not reachable.
Run manually:

    pytest tests/llm/test_provider_speed_benchmark_live.py -v -s

Only exercises the public API (get_safe_max_tokens).
Cache behaviour and pure-function contracts are covered by unit tests.
"""

from __future__ import annotations

import pytest

from warden.llm.provider_speed_benchmark import ProviderSpeedBenchmarkService


def _ollama_reachable() -> bool:
    try:
        import urllib.request

        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2)
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _ollama_reachable(), reason="Ollama not reachable at localhost:11434")


def _make_ollama_client():
    """Ollama client (qwen2.5-coder:3b)."""
    from warden.llm.factory import create_client
    from warden.llm.types import LlmProvider

    return create_client(LlmProvider.OLLAMA)


@pytest.mark.asyncio
async def test_live_benchmark_smoke():
    """
    Service returns a valid max_tokens value with real Ollama — no crash.

    Two outcomes are both acceptable:
      - Benchmark succeeds → returns calculated value in [FLOOR, CEILING]
      - Benchmark times out (slow hardware) → returns default_max_tokens=800

    Either way the result must be in [FLOOR, CEILING] and the second call
    must return the same value as the first (cache or same fallback).
    """
    ProviderSpeedBenchmarkService.reset_instance()
    svc = ProviderSpeedBenchmarkService.get_instance()
    client = _make_ollama_client()

    floor = ProviderSpeedBenchmarkService.MAX_TOKENS_FLOOR
    ceiling = ProviderSpeedBenchmarkService.MAX_TOKENS_CEILING

    tokens_1 = await svc.get_safe_max_tokens(client, phase_timeout_s=120.0, default_max_tokens=800)
    assert floor <= tokens_1 <= ceiling, f"safe_max_tokens={tokens_1} outside [{floor}, {ceiling}]"
    print(f"\n  safe_max_tokens (call 1): {tokens_1}")

    tokens_2 = await svc.get_safe_max_tokens(client, phase_timeout_s=120.0, default_max_tokens=800)
    assert tokens_2 == tokens_1, f"Second call returned {tokens_2}, expected {tokens_1}"
    print(f"  safe_max_tokens (call 2, same client): {tokens_2}")

    ProviderSpeedBenchmarkService.reset_instance()
