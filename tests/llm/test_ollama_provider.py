"""
Unit tests for warden.llm.providers.ollama.OllamaClient

Covers:
1. Initialization — default/custom config, field values
2. send_async — successful response parsing from streaming NDJSON
3. send_async error handling — HTTP errors, timeouts, JSON parse failures
4. send_async model cache — known-missing model short-circuits HTTP call
5. is_available_async — health endpoint and model-tags endpoint logic
6. Model validation — 404 raises ModelNotFoundError, caches the model name
7. Response mapping — token counts, duration fields, content assembly
8. JSON format injection — "json" keyword in prompts triggers format=json payload
9. set_safe_num_predict — caps num_predict applied in payload
10. provider property — returns LlmProvider.OLLAMA
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from warden.llm.config import ProviderConfig
from warden.llm.providers.ollama import ModelNotFoundError, OllamaClient
from warden.llm.types import LlmProvider, LlmRequest, LlmResponse


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------


def _make_config(
    model: str = "qwen2.5-coder:3b",
    endpoint: str = "http://localhost:11434",
) -> ProviderConfig:
    return ProviderConfig(
        enabled=True,
        default_model=model,
        endpoint=endpoint,
    )


def _make_client(model: str = "qwen2.5-coder:3b") -> OllamaClient:
    return OllamaClient(_make_config(model=model))


def _make_request(
    system_prompt: str = "You are helpful.",
    user_message: str = "Hello",
    max_tokens: int = 20,
    model: str | None = None,
) -> LlmRequest:
    return LlmRequest(
        system_prompt=system_prompt,
        user_message=user_message,
        max_tokens=max_tokens,
        model=model,
    )


def _build_stream_lines(
    content: str = "hello world",
    prompt_eval_count: int = 10,
    eval_count: int = 5,
    prompt_eval_duration: int = 200_000_000,
    eval_duration: int = 500_000_000,
) -> list[str]:
    """Build fake Ollama streaming NDJSON lines (non-done then done)."""
    lines: list[str] = []
    for word in content.split():
        chunk = {"message": {"content": word + " "}, "done": False}
        lines.append(json.dumps(chunk))
    done_chunk = {
        "done": True,
        "prompt_eval_count": prompt_eval_count,
        "eval_count": eval_count,
        "prompt_eval_duration": prompt_eval_duration,
        "eval_duration": eval_duration,
    }
    lines.append(json.dumps(done_chunk))
    return lines


def _build_mock_http_context(stream_lines: list[str]):
    """
    Return (mock_async_client_ctx, mock_sem) for patching httpx.AsyncClient
    and GlobalRateLimiter.

    mock_async_client_ctx is the object passed to httpx.AsyncClient(...).
    It is an async context manager whose __aenter__ returns a client with
    a .stream() method that itself is an async context manager yielding a
    response object whose .aiter_lines() is an async generator.
    """
    async def _aiter_lines():
        for line in stream_lines:
            if line:
                yield line

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.aiter_lines = _aiter_lines

    mock_stream_ctx = MagicMock()
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_inner_client = MagicMock()
    mock_inner_client.stream = MagicMock(return_value=mock_stream_ctx)

    mock_async_client_ctx = MagicMock()
    mock_async_client_ctx.__aenter__ = AsyncMock(return_value=mock_inner_client)
    mock_async_client_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_sem = MagicMock()
    mock_sem.__aenter__ = AsyncMock(return_value=None)
    mock_sem.__aexit__ = AsyncMock(return_value=False)

    return mock_async_client_ctx, mock_sem, mock_response, mock_inner_client


def _patch_rate_limiter(mock_sem):
    """Return a patch context manager for the GlobalRateLimiter singleton."""
    mock_limiter = AsyncMock()
    mock_limiter.acquire = AsyncMock()
    mock_limiter.concurrency_limit = MagicMock(return_value=mock_sem)

    patcher = patch(
        "warden.llm.global_rate_limiter.GlobalRateLimiter.get_instance",
        new_callable=AsyncMock,
        return_value=mock_limiter,
    )
    return patcher, mock_limiter


# ---------------------------------------------------------------------------
# TestOllamaClientInit
# ---------------------------------------------------------------------------


class TestOllamaClientInit:
    """Initialization tests — config fields are applied correctly."""

    def test_default_endpoint(self):
        client = OllamaClient(ProviderConfig(enabled=True))
        assert client._endpoint == "http://localhost:11434"

    def test_custom_endpoint(self):
        client = _make_client()
        assert client._endpoint == "http://localhost:11434"

    def test_custom_endpoint_value(self):
        config = ProviderConfig(
            enabled=True,
            default_model="llama3",
            endpoint="http://gpu-box:11434",
        )
        client = OllamaClient(config)
        assert client._endpoint == "http://gpu-box:11434"

    def test_default_model_from_config(self):
        client = _make_client(model="llama3.2:1b")
        assert client._default_model == "llama3.2:1b"

    def test_fallback_default_model(self):
        """When config.default_model is None, fall back to qwen2.5-coder:3b."""
        client = OllamaClient(ProviderConfig(enabled=True))
        assert client._default_model == "qwen2.5-coder:3b"

    def test_missing_models_cache_starts_empty(self):
        client = _make_client()
        assert len(client._missing_models) == 0

    def test_safe_num_predict_initialized(self):
        from warden.llm.provider_speed_benchmark import ProviderSpeedBenchmarkService

        client = _make_client()
        assert client._safe_num_predict == ProviderSpeedBenchmarkService.MAX_TOKENS_CEILING

    def test_provider_property_returns_ollama(self):
        client = _make_client()
        assert client.provider == LlmProvider.OLLAMA


# ---------------------------------------------------------------------------
# TestOllamaSetSafeNumPredict
# ---------------------------------------------------------------------------


class TestOllamaSetSafeNumPredict:
    """set_safe_num_predict validation and floor enforcement."""

    def test_sets_value(self):
        client = _make_client()
        client.set_safe_num_predict(512)
        assert client._safe_num_predict == 512

    def test_floor_of_one(self):
        """Values <= 0 are clamped to 1."""
        client = _make_client()
        client.set_safe_num_predict(0)
        assert client._safe_num_predict == 1

    def test_negative_clamped_to_one(self):
        client = _make_client()
        client.set_safe_num_predict(-100)
        assert client._safe_num_predict == 1

    def test_large_value_accepted(self):
        client = _make_client()
        client.set_safe_num_predict(8192)
        assert client._safe_num_predict == 8192


# ---------------------------------------------------------------------------
# TestOllamaSendAsyncSuccess
# ---------------------------------------------------------------------------


class TestOllamaSendAsyncSuccess:
    """send_async — successful streaming path."""

    @pytest.mark.asyncio
    async def test_returns_success_response(self):
        client = _make_client()
        request = _make_request(user_message="Hello", max_tokens=20)

        stream_lines = _build_stream_lines(
            content="hello world",
            prompt_eval_count=10,
            eval_count=5,
            prompt_eval_duration=200_000_000,
            eval_duration=500_000_000,
        )
        mock_ctx, mock_sem, _, _ = _build_mock_http_context(stream_lines)
        rl_patcher, _ = _patch_rate_limiter(mock_sem)

        with patch("warden.llm.providers.ollama.httpx.AsyncClient", return_value=mock_ctx):
            with rl_patcher:
                response = await client.send_async(request)

        assert response.success is True
        assert response.provider == LlmProvider.OLLAMA

    @pytest.mark.asyncio
    async def test_content_assembled_from_stream_tokens(self):
        client = _make_client()
        request = _make_request(user_message="Ping", max_tokens=20)

        stream_lines = _build_stream_lines(content="ping pong response")
        mock_ctx, mock_sem, _, _ = _build_mock_http_context(stream_lines)
        rl_patcher, _ = _patch_rate_limiter(mock_sem)

        with patch("warden.llm.providers.ollama.httpx.AsyncClient", return_value=mock_ctx):
            with rl_patcher:
                response = await client.send_async(request)

        # The stream appends a space after each word; strip for comparison
        assert "ping" in response.content
        assert "pong" in response.content
        assert "response" in response.content

    @pytest.mark.asyncio
    async def test_token_counts_populated(self):
        client = _make_client()
        request = _make_request(max_tokens=20)

        stream_lines = _build_stream_lines(
            prompt_eval_count=42,
            eval_count=7,
        )
        mock_ctx, mock_sem, _, _ = _build_mock_http_context(stream_lines)
        rl_patcher, _ = _patch_rate_limiter(mock_sem)

        with patch("warden.llm.providers.ollama.httpx.AsyncClient", return_value=mock_ctx):
            with rl_patcher:
                response = await client.send_async(request)

        assert response.prompt_tokens == 42
        assert response.completion_tokens == 7
        assert response.total_tokens == 49

    @pytest.mark.asyncio
    async def test_prefill_and_generation_duration_ms(self):
        client = _make_client()
        request = _make_request(max_tokens=20)

        stream_lines = _build_stream_lines(
            prompt_eval_duration=400_000_000,  # 400 ms
            eval_duration=800_000_000,  # 800 ms
        )
        mock_ctx, mock_sem, _, _ = _build_mock_http_context(stream_lines)
        rl_patcher, _ = _patch_rate_limiter(mock_sem)

        with patch("warden.llm.providers.ollama.httpx.AsyncClient", return_value=mock_ctx):
            with rl_patcher:
                response = await client.send_async(request)

        assert response.prefill_duration_ms == pytest.approx(400.0, abs=0.1)
        assert response.generation_duration_ms == pytest.approx(800.0, abs=0.1)

    @pytest.mark.asyncio
    async def test_zero_timing_yields_none(self):
        """Missing/zero timing in done chunk → prefill/gen duration is None."""
        client = _make_client()
        request = _make_request(max_tokens=5)

        stream_lines = _build_stream_lines(
            prompt_eval_duration=0,
            eval_duration=0,
        )
        mock_ctx, mock_sem, _, _ = _build_mock_http_context(stream_lines)
        rl_patcher, _ = _patch_rate_limiter(mock_sem)

        with patch("warden.llm.providers.ollama.httpx.AsyncClient", return_value=mock_ctx):
            with rl_patcher:
                response = await client.send_async(request)

        assert response.prefill_duration_ms is None
        assert response.generation_duration_ms is None

    @pytest.mark.asyncio
    async def test_uses_request_model_over_default(self):
        """request.model overrides the client default_model in the payload."""
        client = _make_client(model="qwen2.5-coder:3b")
        request = _make_request(max_tokens=5, model="llama3.2:1b")

        stream_lines = _build_stream_lines(content="ok")
        mock_ctx, mock_sem, _, mock_inner = _build_mock_http_context(stream_lines)
        rl_patcher, _ = _patch_rate_limiter(mock_sem)

        with patch("warden.llm.providers.ollama.httpx.AsyncClient", return_value=mock_ctx):
            with rl_patcher:
                response = await client.send_async(request)

        assert response.success is True
        call_kwargs = mock_inner.stream.call_args[1]
        assert call_kwargs["json"]["model"] == "llama3.2:1b"

    @pytest.mark.asyncio
    async def test_model_echoed_in_response(self):
        client = _make_client(model="qwen2.5-coder:3b")
        request = _make_request(max_tokens=5)

        stream_lines = _build_stream_lines(content="done")
        mock_ctx, mock_sem, _, _ = _build_mock_http_context(stream_lines)
        rl_patcher, _ = _patch_rate_limiter(mock_sem)

        with patch("warden.llm.providers.ollama.httpx.AsyncClient", return_value=mock_ctx):
            with rl_patcher:
                response = await client.send_async(request)

        assert response.model == "qwen2.5-coder:3b"

    @pytest.mark.asyncio
    async def test_duration_ms_positive(self):
        """duration_ms must be a non-negative integer."""
        client = _make_client()
        request = _make_request(max_tokens=10)

        stream_lines = _build_stream_lines(content="fast")
        mock_ctx, mock_sem, _, _ = _build_mock_http_context(stream_lines)
        rl_patcher, _ = _patch_rate_limiter(mock_sem)

        with patch("warden.llm.providers.ollama.httpx.AsyncClient", return_value=mock_ctx):
            with rl_patcher:
                response = await client.send_async(request)

        assert isinstance(response.duration_ms, int)
        assert response.duration_ms >= 0


# ---------------------------------------------------------------------------
# TestOllamaJsonFormat
# ---------------------------------------------------------------------------


class TestOllamaJsonFormat:
    """JSON keyword in prompts causes format=json in payload."""

    @pytest.mark.asyncio
    async def test_json_in_system_prompt_adds_format(self):
        client = _make_client()
        request = _make_request(
            system_prompt="Return a JSON object with findings.",
            user_message="Analyze this code.",
            max_tokens=10,
        )

        stream_lines = _build_stream_lines(content='{"findings":[]}')
        mock_ctx, mock_sem, _, mock_inner = _build_mock_http_context(stream_lines)
        rl_patcher, _ = _patch_rate_limiter(mock_sem)

        with patch("warden.llm.providers.ollama.httpx.AsyncClient", return_value=mock_ctx):
            with rl_patcher:
                await client.send_async(request)

        call_kwargs = mock_inner.stream.call_args[1]
        assert call_kwargs["json"].get("format") == "json"

    @pytest.mark.asyncio
    async def test_json_in_user_message_adds_format(self):
        client = _make_client()
        request = _make_request(
            system_prompt="You are helpful.",
            user_message="Return the result as JSON.",
            max_tokens=10,
        )

        stream_lines = _build_stream_lines(content="{}")
        mock_ctx, mock_sem, _, mock_inner = _build_mock_http_context(stream_lines)
        rl_patcher, _ = _patch_rate_limiter(mock_sem)

        with patch("warden.llm.providers.ollama.httpx.AsyncClient", return_value=mock_ctx):
            with rl_patcher:
                await client.send_async(request)

        call_kwargs = mock_inner.stream.call_args[1]
        assert call_kwargs["json"].get("format") == "json"

    @pytest.mark.asyncio
    async def test_no_json_keyword_omits_format(self):
        """When no JSON keyword, format key must NOT appear in payload."""
        client = _make_client()
        request = _make_request(
            system_prompt="You are helpful.",
            user_message="Tell me a joke.",
            max_tokens=10,
        )

        stream_lines = _build_stream_lines(content="why did the chicken cross")
        mock_ctx, mock_sem, _, mock_inner = _build_mock_http_context(stream_lines)
        rl_patcher, _ = _patch_rate_limiter(mock_sem)

        with patch("warden.llm.providers.ollama.httpx.AsyncClient", return_value=mock_ctx):
            with rl_patcher:
                await client.send_async(request)

        call_kwargs = mock_inner.stream.call_args[1]
        assert "format" not in call_kwargs["json"]

    @pytest.mark.asyncio
    async def test_safe_num_predict_caps_payload_num_predict(self):
        """num_predict in payload = min(request.max_tokens, safe_num_predict)."""
        client = _make_client()
        client.set_safe_num_predict(50)

        request = _make_request(max_tokens=200)

        stream_lines = _build_stream_lines(content="ok")
        mock_ctx, mock_sem, _, mock_inner = _build_mock_http_context(stream_lines)
        rl_patcher, _ = _patch_rate_limiter(mock_sem)

        with patch("warden.llm.providers.ollama.httpx.AsyncClient", return_value=mock_ctx):
            with rl_patcher:
                await client.send_async(request)

        call_kwargs = mock_inner.stream.call_args[1]
        assert call_kwargs["json"]["options"]["num_predict"] == 50


# ---------------------------------------------------------------------------
# TestOllamaSendAsyncErrorHandling
# ---------------------------------------------------------------------------


class TestOllamaSendAsyncErrorHandling:
    """send_async error paths — HTTP errors, generic exceptions."""

    @pytest.mark.asyncio
    async def test_404_raises_model_not_found_error(self):
        """HTTP 404 → ModelNotFoundError raised (non-retryable)."""
        client = _make_client(model="missing-model:7b")
        request = _make_request(max_tokens=5)

        mock_http_error_response = MagicMock(spec=httpx.Response)
        mock_http_error_response.status_code = 404

        http_status_error = httpx.HTTPStatusError(
            "Not Found",
            request=MagicMock(),
            response=mock_http_error_response,
        )

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock(side_effect=http_status_error)
        mock_response.status_code = 404

        mock_stream_ctx = MagicMock()
        mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_inner_client = MagicMock()
        mock_inner_client.stream = MagicMock(return_value=mock_stream_ctx)

        mock_async_client_ctx = MagicMock()
        mock_async_client_ctx.__aenter__ = AsyncMock(return_value=mock_inner_client)
        mock_async_client_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_sem = MagicMock()
        mock_sem.__aenter__ = AsyncMock(return_value=None)
        mock_sem.__aexit__ = AsyncMock(return_value=False)

        rl_patcher, _ = _patch_rate_limiter(mock_sem)

        with patch("warden.llm.providers.ollama.httpx.AsyncClient", return_value=mock_async_client_ctx):
            with rl_patcher:
                with pytest.raises(ModelNotFoundError):
                    await client.send_async(request)

    @pytest.mark.asyncio
    async def test_404_caches_missing_model(self):
        """After a 404, the model name is added to _missing_models."""
        client = _make_client(model="ghost-model:3b")
        request = _make_request(max_tokens=5)

        mock_http_error_response = MagicMock(spec=httpx.Response)
        mock_http_error_response.status_code = 404

        http_status_error = httpx.HTTPStatusError(
            "Not Found",
            request=MagicMock(),
            response=mock_http_error_response,
        )

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock(side_effect=http_status_error)

        mock_stream_ctx = MagicMock()
        mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_inner_client = MagicMock()
        mock_inner_client.stream = MagicMock(return_value=mock_stream_ctx)

        mock_async_client_ctx = MagicMock()
        mock_async_client_ctx.__aenter__ = AsyncMock(return_value=mock_inner_client)
        mock_async_client_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_sem = MagicMock()
        mock_sem.__aenter__ = AsyncMock(return_value=None)
        mock_sem.__aexit__ = AsyncMock(return_value=False)

        rl_patcher, _ = _patch_rate_limiter(mock_sem)

        with patch("warden.llm.providers.ollama.httpx.AsyncClient", return_value=mock_async_client_ctx):
            with rl_patcher:
                with pytest.raises(ModelNotFoundError):
                    await client.send_async(request)

        assert "ghost-model:3b" in client._missing_models

    @pytest.mark.asyncio
    async def test_cached_missing_model_returns_error_without_http(self):
        """Pre-cached missing model short-circuits before making any HTTP call."""
        client = _make_client(model="cached-miss:3b")
        client._missing_models.add("cached-miss:3b")

        request = _make_request(max_tokens=5)

        mock_sem = MagicMock()
        mock_sem.__aenter__ = AsyncMock(return_value=None)
        mock_sem.__aexit__ = AsyncMock(return_value=False)
        rl_patcher, mock_limiter = _patch_rate_limiter(mock_sem)

        with patch("warden.llm.providers.ollama.httpx.AsyncClient") as mock_http_cls:
            with rl_patcher:
                response = await client.send_async(request)

        # No HTTP client should have been created
        mock_http_cls.assert_not_called()
        assert response.success is False
        assert "cached-miss:3b" in response.error_message

    @pytest.mark.asyncio
    async def test_non_404_http_error_returns_error_response(self):
        """Non-404 HTTP errors return LlmResponse with success=False."""
        client = _make_client()
        request = _make_request(max_tokens=5)

        mock_http_error_response = MagicMock(spec=httpx.Response)
        mock_http_error_response.status_code = 500

        http_status_error = httpx.HTTPStatusError(
            "Internal Server Error",
            request=MagicMock(),
            response=mock_http_error_response,
        )

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock(side_effect=http_status_error)

        mock_stream_ctx = MagicMock()
        mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_inner_client = MagicMock()
        mock_inner_client.stream = MagicMock(return_value=mock_stream_ctx)

        mock_async_client_ctx = MagicMock()
        mock_async_client_ctx.__aenter__ = AsyncMock(return_value=mock_inner_client)
        mock_async_client_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_sem = MagicMock()
        mock_sem.__aenter__ = AsyncMock(return_value=None)
        mock_sem.__aexit__ = AsyncMock(return_value=False)

        rl_patcher, _ = _patch_rate_limiter(mock_sem)

        with patch("warden.llm.providers.ollama.httpx.AsyncClient", return_value=mock_async_client_ctx):
            with rl_patcher:
                response = await client.send_async(request)

        assert response.success is False
        assert response.provider == LlmProvider.OLLAMA

    @pytest.mark.asyncio
    async def test_generic_exception_returns_error_response(self):
        """Unexpected exceptions are caught and returned as error responses."""
        client = _make_client()
        request = _make_request(max_tokens=5)

        mock_sem = MagicMock()
        mock_sem.__aenter__ = AsyncMock(return_value=None)
        mock_sem.__aexit__ = AsyncMock(return_value=False)
        rl_patcher, mock_limiter = _patch_rate_limiter(mock_sem)

        mock_limiter.acquire = AsyncMock(side_effect=RuntimeError("unexpected crash"))

        with rl_patcher:
            response = await client.send_async(request)

        assert response.success is False
        assert response.provider == LlmProvider.OLLAMA

    @pytest.mark.asyncio
    async def test_connection_error_returns_error_response(self):
        """ConnectError (connection refused) returns error response, does not raise."""
        client = _make_client()
        request = _make_request(max_tokens=5)

        mock_sem = MagicMock()
        mock_sem.__aenter__ = AsyncMock(return_value=None)
        mock_sem.__aexit__ = AsyncMock(return_value=False)
        rl_patcher, mock_limiter = _patch_rate_limiter(mock_sem)

        mock_limiter.acquire = AsyncMock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        with rl_patcher:
            response = await client.send_async(request)

        assert response.success is False


# ---------------------------------------------------------------------------
# TestOllamaIsAvailableAsync
# ---------------------------------------------------------------------------


class TestOllamaIsAvailableAsync:
    """is_available_async — health check and model list logic."""

    @pytest.mark.asyncio
    async def test_returns_true_when_running_and_model_present(self):
        client = _make_client(model="qwen2.5-coder:3b")

        health_response = MagicMock()
        health_response.status_code = 200

        tags_response = MagicMock()
        tags_response.status_code = 200
        tags_response.json.return_value = {
            "models": [
                {"name": "qwen2.5-coder:3b"},
                {"name": "llama3.2:1b"},
            ]
        }

        mock_http_client = AsyncMock()
        mock_http_client.get = AsyncMock(side_effect=[health_response, tags_response])
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=False)

        with patch("warden.llm.providers.ollama.httpx.AsyncClient", return_value=mock_http_client):
            result = await client.is_available_async()

        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_ollama_not_running(self):
        """Health check fails → False returned."""
        client = _make_client()

        mock_http_client = AsyncMock()
        mock_http_client.get = AsyncMock(
            side_effect=httpx.ConnectError("Connection refused")
        )
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=False)

        with patch("warden.llm.providers.ollama.httpx.AsyncClient", return_value=mock_http_client):
            result = await client.is_available_async()

        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_when_health_returns_non_200(self):
        """Health endpoint returns non-200 → False."""
        client = _make_client()

        health_response = MagicMock()
        health_response.status_code = 503

        mock_http_client = AsyncMock()
        mock_http_client.get = AsyncMock(return_value=health_response)
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=False)

        with patch("warden.llm.providers.ollama.httpx.AsyncClient", return_value=mock_http_client):
            result = await client.is_available_async()

        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_when_model_not_in_tags(self):
        """Ollama running but required model not pulled → False."""
        client = _make_client(model="missing-model:7b")

        health_response = MagicMock()
        health_response.status_code = 200

        tags_response = MagicMock()
        tags_response.status_code = 200
        tags_response.json.return_value = {
            "models": [
                {"name": "qwen2.5-coder:3b"},
            ]
        }

        mock_http_client = AsyncMock()
        mock_http_client.get = AsyncMock(side_effect=[health_response, tags_response])
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=False)

        with patch("warden.llm.providers.ollama.httpx.AsyncClient", return_value=mock_http_client):
            result = await client.is_available_async()

        assert result is False

    @pytest.mark.asyncio
    async def test_model_match_with_latest_tag(self):
        """Model without tag matches '<name>:latest' in tags list."""
        client = _make_client(model="llama3")

        health_response = MagicMock()
        health_response.status_code = 200

        tags_response = MagicMock()
        tags_response.status_code = 200
        tags_response.json.return_value = {
            "models": [
                {"name": "llama3:latest"},
            ]
        }

        mock_http_client = AsyncMock()
        mock_http_client.get = AsyncMock(side_effect=[health_response, tags_response])
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=False)

        with patch("warden.llm.providers.ollama.httpx.AsyncClient", return_value=mock_http_client):
            result = await client.is_available_async()

        assert result is True

    @pytest.mark.asyncio
    async def test_exception_during_availability_returns_false(self):
        """Any unexpected exception → False (never raises)."""
        client = _make_client()

        mock_http_client = AsyncMock()
        mock_http_client.get = AsyncMock(side_effect=Exception("random failure"))
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=False)

        with patch("warden.llm.providers.ollama.httpx.AsyncClient", return_value=mock_http_client):
            result = await client.is_available_async()

        assert result is False

    @pytest.mark.asyncio
    async def test_returns_true_when_tags_non_200_but_health_ok(self):
        """
        When /api/tags returns non-200, we cannot verify model presence.
        The current implementation returns True in this case (defensive).
        """
        client = _make_client(model="qwen2.5-coder:3b")

        health_response = MagicMock()
        health_response.status_code = 200

        tags_response = MagicMock()
        tags_response.status_code = 404  # Unexpected, old Ollama version

        mock_http_client = AsyncMock()
        mock_http_client.get = AsyncMock(side_effect=[health_response, tags_response])
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=False)

        with patch("warden.llm.providers.ollama.httpx.AsyncClient", return_value=mock_http_client):
            result = await client.is_available_async()

        # When /api/tags fails, the client falls through to return True
        assert result is True


# ---------------------------------------------------------------------------
# TestModelNotFoundError
# ---------------------------------------------------------------------------


class TestModelNotFoundError:
    """ModelNotFoundError class properties."""

    def test_is_non_retryable(self):
        assert ModelNotFoundError.non_retryable is True

    def test_is_exception_subclass(self):
        err = ModelNotFoundError("test message")
        assert isinstance(err, Exception)

    def test_message_preserved(self):
        msg = "Model 'x' not found. Run 'ollama pull x'."
        err = ModelNotFoundError(msg)
        assert str(err) == msg


# ---------------------------------------------------------------------------
# TestOllamaStreamingPayload
# ---------------------------------------------------------------------------


class TestOllamaStreamingPayload:
    """Verify the exact streaming payload sent to the Ollama API."""

    @pytest.mark.asyncio
    async def test_stream_flag_is_true(self):
        """Payload must always include stream=True."""
        client = _make_client()
        request = _make_request(max_tokens=10)

        stream_lines = _build_stream_lines(content="ok")
        mock_ctx, mock_sem, _, mock_inner = _build_mock_http_context(stream_lines)
        rl_patcher, _ = _patch_rate_limiter(mock_sem)

        with patch("warden.llm.providers.ollama.httpx.AsyncClient", return_value=mock_ctx):
            with rl_patcher:
                await client.send_async(request)

        call_kwargs = mock_inner.stream.call_args[1]
        assert call_kwargs["json"]["stream"] is True

    @pytest.mark.asyncio
    async def test_temperature_passed_in_options(self):
        """Temperature from request is placed in options block."""
        client = _make_client()
        request = LlmRequest(
            system_prompt="test",
            user_message="test",
            max_tokens=10,
            temperature=0.5,
        )

        stream_lines = _build_stream_lines(content="ok")
        mock_ctx, mock_sem, _, mock_inner = _build_mock_http_context(stream_lines)
        rl_patcher, _ = _patch_rate_limiter(mock_sem)

        with patch("warden.llm.providers.ollama.httpx.AsyncClient", return_value=mock_ctx):
            with rl_patcher:
                await client.send_async(request)

        call_kwargs = mock_inner.stream.call_args[1]
        assert call_kwargs["json"]["options"]["temperature"] == 0.5

    @pytest.mark.asyncio
    async def test_messages_contain_system_and_user(self):
        """Payload messages list must contain system + user roles."""
        client = _make_client()
        request = _make_request(
            system_prompt="Be concise.",
            user_message="What is 2+2?",
            max_tokens=10,
        )

        stream_lines = _build_stream_lines(content="4")
        mock_ctx, mock_sem, _, mock_inner = _build_mock_http_context(stream_lines)
        rl_patcher, _ = _patch_rate_limiter(mock_sem)

        with patch("warden.llm.providers.ollama.httpx.AsyncClient", return_value=mock_ctx):
            with rl_patcher:
                await client.send_async(request)

        call_kwargs = mock_inner.stream.call_args[1]
        messages = call_kwargs["json"]["messages"]
        roles = [m["role"] for m in messages]
        assert "system" in roles
        assert "user" in roles

    @pytest.mark.asyncio
    async def test_system_and_user_content_correct(self):
        client = _make_client()
        request = _make_request(
            system_prompt="Be concise.",
            user_message="What is 2+2?",
            max_tokens=10,
        )

        stream_lines = _build_stream_lines(content="4")
        mock_ctx, mock_sem, _, mock_inner = _build_mock_http_context(stream_lines)
        rl_patcher, _ = _patch_rate_limiter(mock_sem)

        with patch("warden.llm.providers.ollama.httpx.AsyncClient", return_value=mock_ctx):
            with rl_patcher:
                await client.send_async(request)

        call_kwargs = mock_inner.stream.call_args[1]
        messages = {m["role"]: m["content"] for m in call_kwargs["json"]["messages"]}
        assert messages["system"] == "Be concise."
        assert messages["user"] == "What is 2+2?"

    @pytest.mark.asyncio
    async def test_post_url_uses_configured_endpoint(self):
        """stream() is called with the endpoint-derived URL."""
        client = OllamaClient(
            ProviderConfig(
                enabled=True,
                default_model="qwen2.5-coder:3b",
                endpoint="http://gpu-box:11434",
            )
        )
        request = _make_request(max_tokens=5)

        stream_lines = _build_stream_lines(content="ok")
        mock_ctx, mock_sem, _, mock_inner = _build_mock_http_context(stream_lines)
        rl_patcher, _ = _patch_rate_limiter(mock_sem)

        with patch("warden.llm.providers.ollama.httpx.AsyncClient", return_value=mock_ctx):
            with rl_patcher:
                await client.send_async(request)

        positional_args = mock_inner.stream.call_args[0]
        url_arg = positional_args[1] if len(positional_args) > 1 else mock_inner.stream.call_args[1].get("url", "")
        # stream("POST", <url>, ...) — second positional
        assert "gpu-box:11434" in positional_args[1]
