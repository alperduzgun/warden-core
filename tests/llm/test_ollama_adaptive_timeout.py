"""
Tests for adaptive OllamaClient read timeout and _apply_read_timeout helper.

Covers:
1. OllamaClient.set_read_timeout — floor clamping, value propagation to httpx
2. Ollama timing stats extraction from done chunk
3. _apply_read_timeout traversal logic (direct, orchestrated smart, orchestrated fast)
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from warden.analysis.application.llm_phase_base import _apply_read_timeout
from warden.llm.config import ProviderConfig
from warden.llm.provider_speed_benchmark import ProviderSpeedBenchmarkService
from warden.llm.providers.ollama import OllamaClient
from warden.llm.types import LlmProvider, LlmRequest, LlmResponse


def _read_timeout_thresholds() -> tuple[float, float, float]:
    """Return (default, floor, ceiling) derived from BENCHMARK_TIMEOUT_S."""
    gen_buf = ProviderSpeedBenchmarkService.BENCHMARK_TIMEOUT_S / 3
    return (
        ProviderSpeedBenchmarkService.BENCHMARK_TIMEOUT_S + gen_buf,
        gen_buf,
        3 * ProviderSpeedBenchmarkService.BENCHMARK_TIMEOUT_S + gen_buf,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(model: str = "qwen2.5-coder:3b") -> ProviderConfig:
    return ProviderConfig(
        enabled=True,
        default_model=model,
        endpoint="http://localhost:11434",
    )


def _make_ollama_client() -> OllamaClient:
    return OllamaClient(_make_config())


# ---------------------------------------------------------------------------
# TestSetReadTimeout
# ---------------------------------------------------------------------------


class TestSetReadTimeout:
    def test_default_read_timeout(self):
        """Default _read_timeout = BENCHMARK_TIMEOUT_S + generation_buffer."""
        default, _, _ = _read_timeout_thresholds()
        client = _make_ollama_client()
        assert client._read_timeout == default

    def test_set_read_timeout_updates_value(self):
        _, floor, _ = _read_timeout_thresholds()
        client = _make_ollama_client()
        above_floor = floor + 60.0
        client.set_read_timeout(above_floor)
        assert client._read_timeout == above_floor

    def test_floor_enforced(self):
        """Values below generation_buffer are clamped to it."""
        _, floor, _ = _read_timeout_thresholds()
        client = _make_ollama_client()
        client.set_read_timeout(1.0)
        assert client._read_timeout == floor

    def test_exact_floor_boundary(self):
        _, floor, _ = _read_timeout_thresholds()
        client = _make_ollama_client()
        client.set_read_timeout(floor)
        assert client._read_timeout == floor

    def test_ceiling_not_enforced(self):
        """No artificial ceiling — values above ceiling are valid."""
        _, _, ceiling = _read_timeout_thresholds()
        client = _make_ollama_client()
        above_ceiling = ceiling + 100.0
        client.set_read_timeout(above_ceiling)
        assert client._read_timeout == above_ceiling


# ---------------------------------------------------------------------------
# TestOllamaStatExtraction
# ---------------------------------------------------------------------------


class TestOllamaStatExtraction:
    """Verify that send_async populates prefill_duration_ms / generation_duration_ms."""

    def _make_streaming_chunks(
        self,
        content: str = "hello world",
        prompt_eval_count: int = 50,
        eval_count: int = 5,
        prompt_eval_duration: int = 500_000_000,  # 500 ms in ns
        eval_duration: int = 1_000_000_000,  # 1 s in ns
    ) -> list[bytes]:
        """Build fake Ollama streaming NDJSON lines."""
        words = content.split()
        lines: list[bytes] = []
        for word in words:
            chunk = {"message": {"content": word + " "}, "done": False}
            lines.append((json.dumps(chunk) + "\n").encode())

        done_chunk = {
            "done": True,
            "prompt_eval_count": prompt_eval_count,
            "eval_count": eval_count,
            "prompt_eval_duration": prompt_eval_duration,
            "eval_duration": eval_duration,
        }
        lines.append((json.dumps(done_chunk) + "\n").encode())
        return lines

    @pytest.mark.asyncio
    async def test_prefill_and_generation_populated(self):
        """send_async must populate prefill_duration_ms and generation_duration_ms."""
        client = _make_ollama_client()
        request = LlmRequest(
            system_prompt="You are helpful.",
            user_message="Hello",
            max_tokens=20,
        )

        chunks = self._make_streaming_chunks(
            content="hello world",
            prompt_eval_count=50,
            eval_count=5,
            prompt_eval_duration=500_000_000,  # 500 ms in ns
            eval_duration=1_000_000_000,  # 1000 ms in ns
        )
        raw_lines = b"".join(chunks)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()

        async def fake_aiter_lines():
            for line in raw_lines.decode().splitlines():
                if line:
                    yield line

        mock_response.aiter_lines = fake_aiter_lines

        mock_stream = MagicMock()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_response)
        mock_stream.__aexit__ = AsyncMock(return_value=False)

        mock_client = MagicMock()
        mock_client.stream = MagicMock(return_value=mock_stream)

        mock_async_client = MagicMock()
        mock_async_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_async_client.__aexit__ = AsyncMock(return_value=False)

        mock_sem = MagicMock()
        mock_sem.__aenter__ = AsyncMock(return_value=None)
        mock_sem.__aexit__ = AsyncMock(return_value=False)

        mock_limiter = AsyncMock()
        mock_limiter.concurrency_limit = MagicMock(return_value=mock_sem)

        with patch("warden.llm.providers.ollama.httpx.AsyncClient", return_value=mock_async_client):
            with patch("warden.llm.global_rate_limiter.GlobalRateLimiter") as mock_rl:
                mock_rl.get_instance = AsyncMock(return_value=mock_limiter)
                response = await client.send_async(request)

        assert response.success is True
        assert response.prompt_tokens == 50
        assert response.completion_tokens == 5
        assert response.prefill_duration_ms == pytest.approx(500.0, abs=0.01)  # 500_000_000 / 1e6
        assert response.generation_duration_ms == pytest.approx(1000.0, abs=0.01)  # 1_000_000_000 / 1e6

    @pytest.mark.asyncio
    async def test_zero_timing_fields_produce_none(self):
        """Missing/zero timing fields in done chunk → None (not 0.0)."""
        client = _make_ollama_client()
        request = LlmRequest(system_prompt="x", user_message="y", max_tokens=5)

        chunks = self._make_streaming_chunks(
            content="hi",
            prompt_eval_count=10,
            eval_count=2,
            prompt_eval_duration=0,  # 0 → should produce None
            eval_duration=0,
        )
        raw_lines = b"".join(chunks)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()

        async def fake_aiter_lines():
            for line in raw_lines.decode().splitlines():
                if line:
                    yield line

        mock_response.aiter_lines = fake_aiter_lines

        mock_stream = MagicMock()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_response)
        mock_stream.__aexit__ = AsyncMock(return_value=False)

        mock_client = MagicMock()
        mock_client.stream = MagicMock(return_value=mock_stream)

        mock_async_client = MagicMock()
        mock_async_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_async_client.__aexit__ = AsyncMock(return_value=False)

        mock_sem = MagicMock()
        mock_sem.__aenter__ = AsyncMock(return_value=None)
        mock_sem.__aexit__ = AsyncMock(return_value=False)

        mock_limiter = AsyncMock()
        mock_limiter.concurrency_limit = MagicMock(return_value=mock_sem)

        with patch("warden.llm.providers.ollama.httpx.AsyncClient", return_value=mock_async_client):
            with patch("warden.llm.global_rate_limiter.GlobalRateLimiter") as mock_rl:
                mock_rl.get_instance = AsyncMock(return_value=mock_limiter)
                response = await client.send_async(request)

        assert response.prefill_duration_ms is None
        assert response.generation_duration_ms is None


# ---------------------------------------------------------------------------
# TestApplyReadTimeout
# ---------------------------------------------------------------------------


class TestApplyReadTimeout:
    def test_direct_ollama_client(self):
        """_apply_read_timeout sets timeout on a direct OllamaClient."""
        _, floor, _ = _read_timeout_thresholds()
        client = _make_ollama_client()
        value = floor + 60.0
        _apply_read_timeout(client, value)
        assert client._read_timeout == value

    def test_orchestrated_fast_client(self):
        """_apply_read_timeout reaches OllamaClient in fast_clients list."""
        _, floor, _ = _read_timeout_thresholds()
        ollama = _make_ollama_client()
        orchestrated = MagicMock()
        del orchestrated.set_read_timeout  # not a direct client
        orchestrated.smart_client = MagicMock(spec=[])  # no set_read_timeout
        orchestrated.fast_clients = [ollama]

        value = floor + 50.0
        _apply_read_timeout(orchestrated, value)
        assert ollama._read_timeout == value

    def test_orchestrated_smart_client_is_ollama(self):
        """_apply_read_timeout reaches OllamaClient when it's the smart_client."""
        _, floor, _ = _read_timeout_thresholds()
        ollama = _make_ollama_client()
        orchestrated = MagicMock()
        del orchestrated.set_read_timeout
        orchestrated.smart_client = ollama
        orchestrated.fast_clients = []

        value = floor + 45.0
        _apply_read_timeout(orchestrated, value)
        assert ollama._read_timeout == value

    def test_no_ollama_client_no_error(self):
        """If no OllamaClient is reachable, function silently returns."""
        _, floor, _ = _read_timeout_thresholds()
        plain = MagicMock(spec=[])  # no set_read_timeout, no smart_client, no fast_clients
        _apply_read_timeout(plain, floor + 60.0)  # must not raise

    def test_floor_respected_through_helper(self):
        """set_read_timeout floor is enforced when called through _apply_read_timeout."""
        _, floor, _ = _read_timeout_thresholds()
        client = _make_ollama_client()
        _apply_read_timeout(client, floor / 2)
        assert client._read_timeout == floor

    def test_both_smart_and_fast_updated(self):
        """When both smart and fast clients are OllamaClient instances, both are updated."""
        _, floor, _ = _read_timeout_thresholds()
        smart_ollama = _make_ollama_client()
        fast_ollama = _make_ollama_client()

        orchestrated = MagicMock()
        del orchestrated.set_read_timeout
        orchestrated.smart_client = smart_ollama
        orchestrated.fast_clients = [fast_ollama]

        value = floor + 70.0
        _apply_read_timeout(orchestrated, value)
        assert smart_ollama._read_timeout == value
        assert fast_ollama._read_timeout == value
