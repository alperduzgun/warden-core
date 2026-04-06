"""
Tests for the Qwen (Alibaba Cloud DashScope) LLM provider.

Covers: success path, 429 rate-limit handling, JSON mode payload, default model.
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from warden.llm.providers.qwen import QwenClient, _parse_retry_after
from warden.llm.types import LlmProvider, LlmRequest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(api_key: str = "sk-test-key-1234567890", model: str | None = None, endpoint: str | None = None):
    cfg = MagicMock()
    cfg.api_key = api_key
    cfg.default_model = model
    cfg.endpoint = endpoint
    return cfg


def _openai_response(content: str = "Hello from Qwen", model: str = "qwen-coder-turbo") -> dict:
    """Build a minimal OpenAI-format response dict."""
    return {
        "choices": [{"message": {"content": content}}],
        "model": model,
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        },
    }


def _mock_http_success(content: str = "Hello from Qwen"):
    """Return a context-manager mock for httpx.AsyncClient that yields success."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = _openai_response(content=content)

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=mock_response)

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    return mock_ctx


def _mock_rate_limiter():
    """Return a GlobalRateLimiter mock that does nothing on acquire."""
    limiter = AsyncMock()
    limiter.acquire = AsyncMock()
    return limiter


# ---------------------------------------------------------------------------
# Test: successful send_async
# ---------------------------------------------------------------------------


class TestQwenSendAsyncSuccess:
    """QwenClient.send_async returns a successful LlmResponse on 200."""

    @pytest.mark.asyncio
    async def test_response_success_flag(self):
        """success must be True when API returns valid choices."""
        # Arrange
        QwenClient._rate_limited_until = 0.0
        client = QwenClient(_make_config())
        request = LlmRequest(system_prompt="sys", user_message="hello", max_tokens=100)

        # Act
        with patch(
            "warden.llm.global_rate_limiter.GlobalRateLimiter.get_instance",
            new=AsyncMock(return_value=_mock_rate_limiter()),
        ):
            with patch("httpx.AsyncClient", return_value=_mock_http_success()):
                response = await client.send_async(request)

        # Assert
        assert response.success is True
        assert response.error_message is None

    @pytest.mark.asyncio
    async def test_response_content_extracted(self):
        """Content must be extracted from choices[0].message.content."""
        QwenClient._rate_limited_until = 0.0
        client = QwenClient(_make_config())
        request = LlmRequest(system_prompt="sys", user_message="hi", max_tokens=50)

        with patch(
            "warden.llm.global_rate_limiter.GlobalRateLimiter.get_instance",
            new=AsyncMock(return_value=_mock_rate_limiter()),
        ):
            with patch("httpx.AsyncClient", return_value=_mock_http_success(content="Qwen response text")):
                response = await client.send_async(request)

        assert response.content == "Qwen response text"

    @pytest.mark.asyncio
    async def test_response_provider_set(self):
        """provider field must be LlmProvider.QWEN."""
        QwenClient._rate_limited_until = 0.0
        client = QwenClient(_make_config())
        request = LlmRequest(system_prompt="sys", user_message="hi", max_tokens=50)

        with patch(
            "warden.llm.global_rate_limiter.GlobalRateLimiter.get_instance",
            new=AsyncMock(return_value=_mock_rate_limiter()),
        ):
            with patch("httpx.AsyncClient", return_value=_mock_http_success()):
                response = await client.send_async(request)

        assert response.provider == LlmProvider.QWEN

    @pytest.mark.asyncio
    async def test_token_counts_populated(self):
        """Token usage fields must be populated from API response."""
        QwenClient._rate_limited_until = 0.0
        client = QwenClient(_make_config())
        request = LlmRequest(system_prompt="sys", user_message="hi", max_tokens=50)

        with patch(
            "warden.llm.global_rate_limiter.GlobalRateLimiter.get_instance",
            new=AsyncMock(return_value=_mock_rate_limiter()),
        ):
            with patch("httpx.AsyncClient", return_value=_mock_http_success()):
                response = await client.send_async(request)

        assert response.prompt_tokens == 10
        assert response.completion_tokens == 5
        assert response.total_tokens == 15


# ---------------------------------------------------------------------------
# Test: 429 rate-limit handling
# ---------------------------------------------------------------------------


class TestQwen429RateLimit:
    """QwenClient.send_async handles 429 responses correctly."""

    @pytest.mark.asyncio
    async def test_429_returns_error_response(self):
        """A 429 HTTP error must produce a failed LlmResponse with rate-limit message."""
        import httpx

        # Arrange
        QwenClient._rate_limited_until = 0.0
        client = QwenClient(_make_config())
        request = LlmRequest(system_prompt="sys", user_message="hello", max_tokens=100, timeout_seconds=120.0)

        mock_http_response = MagicMock()
        mock_http_response.status_code = 429
        mock_http_response.text = "Too many requests"
        mock_http_response.headers = {"retry-after": "30"}

        http_error = httpx.HTTPStatusError(
            "429 Too Many Requests",
            request=MagicMock(),
            response=mock_http_response,
        )

        mock_client = MagicMock()
        mock_client.post = AsyncMock(side_effect=http_error)
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        # Act
        with patch(
            "warden.llm.global_rate_limiter.GlobalRateLimiter.get_instance",
            new=AsyncMock(return_value=_mock_rate_limiter()),
        ):
            with patch("httpx.AsyncClient", return_value=mock_ctx):
                response = await client.send_async(request)

        # Assert
        assert response.success is False
        assert response.error_message is not None
        assert "rate limited" in response.error_message.lower()

    @pytest.mark.asyncio
    async def test_429_sets_class_level_rate_limited_until(self):
        """After a 429 with Retry-After: 30, _rate_limited_until must be ~now+30s."""
        import httpx

        QwenClient._rate_limited_until = 0.0
        client = QwenClient(_make_config())
        request = LlmRequest(system_prompt="sys", user_message="hello", max_tokens=100, timeout_seconds=120.0)

        mock_http_response = MagicMock()
        mock_http_response.status_code = 429
        mock_http_response.text = ""
        mock_http_response.headers = {"retry-after": "30"}

        http_error = httpx.HTTPStatusError(
            "429 Too Many Requests",
            request=MagicMock(),
            response=mock_http_response,
        )

        mock_client = MagicMock()
        mock_client.post = AsyncMock(side_effect=http_error)
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        before = time.time()
        with patch(
            "warden.llm.global_rate_limiter.GlobalRateLimiter.get_instance",
            new=AsyncMock(return_value=_mock_rate_limiter()),
        ):
            with patch("httpx.AsyncClient", return_value=mock_ctx):
                await client.send_async(request)

        # _rate_limited_until should be approximately now + 30s
        assert QwenClient._rate_limited_until >= before + 29
        assert QwenClient._rate_limited_until <= before + 35  # generous margin

        # Cleanup
        QwenClient._rate_limited_until = 0.0

    @pytest.mark.asyncio
    async def test_429_no_retry_after_header_defaults_60s(self):
        """Without Retry-After header, back-off must default to 60 seconds."""
        import httpx

        QwenClient._rate_limited_until = 0.0
        client = QwenClient(_make_config())
        request = LlmRequest(system_prompt="sys", user_message="hello", max_tokens=100, timeout_seconds=120.0)

        mock_http_response = MagicMock()
        mock_http_response.status_code = 429
        mock_http_response.text = "Too many requests"
        mock_http_response.headers = {}  # No Retry-After

        http_error = httpx.HTTPStatusError(
            "429 Too Many Requests",
            request=MagicMock(),
            response=mock_http_response,
        )

        mock_client = MagicMock()
        mock_client.post = AsyncMock(side_effect=http_error)
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        before = time.time()
        with patch(
            "warden.llm.global_rate_limiter.GlobalRateLimiter.get_instance",
            new=AsyncMock(return_value=_mock_rate_limiter()),
        ):
            with patch("httpx.AsyncClient", return_value=mock_ctx):
                await client.send_async(request)

        assert QwenClient._rate_limited_until >= before + 59

        # Cleanup
        QwenClient._rate_limited_until = 0.0


# ---------------------------------------------------------------------------
# Test: _parse_retry_after helper
# ---------------------------------------------------------------------------


class TestParseRetryAfter:
    """Unit tests for the _parse_retry_after helper function."""

    def test_returns_header_value_when_present(self):
        """Should return the integer from Retry-After header."""
        mock_response = MagicMock()
        mock_response.headers = {"retry-after": "45"}
        assert _parse_retry_after(mock_response) == 45

    def test_returns_60_when_no_header(self):
        """Should return 60 as default when header is absent."""
        mock_response = MagicMock()
        mock_response.headers = {}
        assert _parse_retry_after(mock_response) == 60

    def test_returns_60_when_header_is_non_numeric(self):
        """Should return 60 when header value cannot be parsed as int."""
        mock_response = MagicMock()
        mock_response.headers = {"retry-after": "Fri, 31 Dec 9999 23:59:59 GMT"}
        assert _parse_retry_after(mock_response) == 60


# ---------------------------------------------------------------------------
# Test: JSON mode payload
# ---------------------------------------------------------------------------


class TestQwenJsonModePayload:
    """QwenClient must set response_format when prompt contains 'json'."""

    @pytest.mark.asyncio
    async def test_json_in_system_prompt_sets_response_format(self):
        """response_format=json_object must be added when system_prompt has 'json'."""
        QwenClient._rate_limited_until = 0.0
        client = QwenClient(_make_config())

        captured_payload: list[dict] = []

        async def capture_post(url, headers=None, json=None, **kwargs):
            captured_payload.append(json or {})
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = _openai_response()
            return mock_resp

        mock_client = MagicMock()
        mock_client.post = capture_post
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        request = LlmRequest(
            system_prompt="Respond in JSON format only.",
            user_message="List three items.",
            max_tokens=200,
        )

        with patch(
            "warden.llm.global_rate_limiter.GlobalRateLimiter.get_instance",
            new=AsyncMock(return_value=_mock_rate_limiter()),
        ):
            with patch("httpx.AsyncClient", return_value=mock_ctx):
                await client.send_async(request)

        assert len(captured_payload) == 1
        assert captured_payload[0].get("response_format") == {"type": "json_object"}

    @pytest.mark.asyncio
    async def test_json_in_user_message_sets_response_format(self):
        """response_format must be set when user_message starts with 'json'."""
        QwenClient._rate_limited_until = 0.0
        client = QwenClient(_make_config())

        captured_payload: list[dict] = []

        async def capture_post(url, headers=None, json=None, **kwargs):
            captured_payload.append(json or {})
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = _openai_response()
            return mock_resp

        mock_client = MagicMock()
        mock_client.post = capture_post
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        request = LlmRequest(
            system_prompt="You are helpful.",
            user_message="json: return a list of colors",
            max_tokens=200,
        )

        with patch(
            "warden.llm.global_rate_limiter.GlobalRateLimiter.get_instance",
            new=AsyncMock(return_value=_mock_rate_limiter()),
        ):
            with patch("httpx.AsyncClient", return_value=mock_ctx):
                await client.send_async(request)

        assert captured_payload[0].get("response_format") == {"type": "json_object"}

    @pytest.mark.asyncio
    async def test_no_json_in_prompt_omits_response_format(self):
        """response_format must NOT be set when prompt contains no 'json'."""
        QwenClient._rate_limited_until = 0.0
        client = QwenClient(_make_config())

        captured_payload: list[dict] = []

        async def capture_post(url, headers=None, json=None, **kwargs):
            captured_payload.append(json or {})
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = _openai_response()
            return mock_resp

        mock_client = MagicMock()
        mock_client.post = capture_post
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        request = LlmRequest(
            system_prompt="You are a helpful assistant.",
            user_message="Tell me a story.",
            max_tokens=200,
        )

        with patch(
            "warden.llm.global_rate_limiter.GlobalRateLimiter.get_instance",
            new=AsyncMock(return_value=_mock_rate_limiter()),
        ):
            with patch("httpx.AsyncClient", return_value=mock_ctx):
                await client.send_async(request)

        assert "response_format" not in captured_payload[0]


# ---------------------------------------------------------------------------
# Test: default model
# ---------------------------------------------------------------------------


class TestQwenDefaultModel:
    """QwenClient must use 'qwen-coder-turbo' when no model override is provided."""

    def test_default_model_is_qwen_turbo_from_config(self):
        """When config.default_model is None, _default_model must be 'qwen-coder-turbo'."""
        config = _make_config(model=None)
        client = QwenClient(config)
        assert client._default_model == "qwen-coder-turbo"

    def test_config_model_overrides_default(self):
        """When config.default_model is set, it must be used."""
        config = _make_config(model="qwen-max")
        client = QwenClient(config)
        assert client._default_model == "qwen-max"

    @pytest.mark.asyncio
    async def test_default_model_sent_in_payload(self):
        """When request.model is None, payload must use the configured default model."""
        QwenClient._rate_limited_until = 0.0
        client = QwenClient(_make_config(model=None))

        captured_payload: list[dict] = []

        async def capture_post(url, headers=None, json=None, **kwargs):
            captured_payload.append(json or {})
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = _openai_response()
            return mock_resp

        mock_client = MagicMock()
        mock_client.post = capture_post
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        request = LlmRequest(
            system_prompt="sys",
            user_message="hello",
            max_tokens=50,
            model=None,
        )

        with patch(
            "warden.llm.global_rate_limiter.GlobalRateLimiter.get_instance",
            new=AsyncMock(return_value=_mock_rate_limiter()),
        ):
            with patch("httpx.AsyncClient", return_value=mock_ctx):
                await client.send_async(request)

        assert captured_payload[0]["model"] == "qwen-coder-turbo"

    def test_provider_property_returns_qwen(self):
        """provider property must return LlmProvider.QWEN."""
        client = QwenClient(_make_config())
        assert client.provider == LlmProvider.QWEN


# ---------------------------------------------------------------------------
# Test: registry self-registration
# ---------------------------------------------------------------------------


class TestQwenRegistration:
    """QwenClient must be registered with the ProviderRegistry on module import."""

    def test_provider_registered_in_registry(self):
        """LlmProvider.QWEN must be registered after importing the module."""
        from warden.llm.registry import ProviderRegistry

        # Import triggers self-registration at module bottom
        import warden.llm.providers.qwen  # noqa: F401

        assert ProviderRegistry.is_registered(LlmProvider.QWEN)
