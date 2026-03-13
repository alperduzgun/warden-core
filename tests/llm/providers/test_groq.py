"""
Tests for warden.llm.providers.groq

Verifies:
1. Successful API response parsing
2. Rate-limit (429) handling with retry-after header and body parsing
3. Model filtering (rejects claude-*, gpt-*, ollama-style models)
4. Missing API key raises ValueError
5. HTTP error handling
6. Rate-limit short-circuit when budget exceeds timeout
"""

import time

import httpx
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from warden.llm.providers.groq import GroqClient, _parse_retry_after
from warden.llm.config import ProviderConfig
from warden.llm.types import LlmRequest, LlmResponse


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    """Reset class-level rate limit between tests."""
    GroqClient._rate_limited_until = 0.0
    yield
    GroqClient._rate_limited_until = 0.0


@pytest.fixture
def config():
    return ProviderConfig(enabled=True, api_key="test-key", default_model="llama-3.3-70b-versatile")


@pytest.fixture
def client(config):
    return GroqClient(config)


@pytest.fixture
def request_obj():
    return LlmRequest(
        system_prompt="You are a helpful assistant.",
        user_message="Hello",
        max_tokens=100,
        timeout_seconds=30,
    )


class TestGroqInit:

    def test_missing_api_key_raises(self):
        with pytest.raises(ValueError, match="API key"):
            GroqClient(ProviderConfig(enabled=True, api_key=""))

    def test_default_model(self, client):
        assert client._default_model == "llama-3.3-70b-versatile"

    def test_custom_endpoint(self):
        c = GroqClient(ProviderConfig(enabled=True, api_key="k", endpoint="https://custom.api"))
        assert c._base_url == "https://custom.api"

    def test_provider_is_groq(self, client):
        from warden.llm.types import LlmProvider
        assert client.provider == LlmProvider.GROQ


class TestParseRetryAfter:

    def test_header_retry_after(self):
        resp = MagicMock(spec=httpx.Response)
        resp.headers = {"retry-after": "30"}
        assert _parse_retry_after(resp) == 30

    def test_body_tpd_retry_after(self):
        resp = MagicMock(spec=httpx.Response)
        resp.headers = {}
        resp.json.return_value = {
            "error": {"message": "Rate limit reached. Please try again in 39m59.99s."}
        }
        result = _parse_retry_after(resp)
        # 39*60 + 59.99 + 1 safety = 2400.99 → 2400
        assert result == 2400

    def test_body_seconds_only(self):
        resp = MagicMock(spec=httpx.Response)
        resp.headers = {}
        resp.json.return_value = {
            "error": {"message": "Please try again in 5.5s."}
        }
        result = _parse_retry_after(resp)
        assert result == 6  # 5.5 + 1 safety margin

    def test_fallback_when_no_info(self):
        resp = MagicMock(spec=httpx.Response)
        resp.headers = {}
        resp.json.side_effect = Exception("parse error")
        assert _parse_retry_after(resp) == 5


class TestGroqModelFiltering:

    @pytest.mark.asyncio
    async def test_rejects_claude_model(self, client):
        """Claude models should be rejected and replaced with default."""
        request = LlmRequest(
            system_prompt="test", user_message="test",
            model="claude-3-sonnet", max_tokens=10,
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "ok"}}],
            "model": "llama-3.3-70b-versatile",
            "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
        }

        with patch("warden.llm.providers.groq.httpx.AsyncClient") as mock_client_cls, \
             patch("warden.llm.global_rate_limiter.GlobalRateLimiter.get_instance", new_callable=AsyncMock) as mock_limiter:
            mock_limiter.return_value = MagicMock()
            mock_limiter.return_value.acquire = AsyncMock()
            mock_http = AsyncMock()
            mock_http.post = AsyncMock(return_value=mock_response)
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_http

            response = await client.send_async(request)

        assert response.success
        # Verify the model sent to API was the default, not claude
        call_payload = mock_http.post.call_args[1]["json"]
        assert call_payload["model"] == "llama-3.3-70b-versatile"

    @pytest.mark.asyncio
    async def test_rejects_ollama_style_model(self, client):
        """Models with ':' (e.g. qwen2.5-coder:3b) should use default."""
        request = LlmRequest(
            system_prompt="test", user_message="test",
            model="qwen2.5-coder:3b", max_tokens=10,
        )

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "ok"}}],
            "model": "llama-3.3-70b-versatile",
            "usage": {},
        }

        with patch("warden.llm.providers.groq.httpx.AsyncClient") as mock_client_cls, \
             patch("warden.llm.global_rate_limiter.GlobalRateLimiter.get_instance", new_callable=AsyncMock) as mock_limiter:
            mock_limiter.return_value = MagicMock()
            mock_limiter.return_value.acquire = AsyncMock()
            mock_http = AsyncMock()
            mock_http.post = AsyncMock(return_value=mock_response)
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_http

            response = await client.send_async(request)

        call_payload = mock_http.post.call_args[1]["json"]
        assert call_payload["model"] == "llama-3.3-70b-versatile"


class TestGroqRateLimit:

    @pytest.mark.asyncio
    async def test_rate_limit_skip_when_exceeds_timeout(self, client):
        """Should return error immediately when rate limit exceeds timeout."""
        GroqClient._rate_limited_until = time.time() + 3600  # 1 hour

        request = LlmRequest(
            system_prompt="test", user_message="test",
            max_tokens=10, timeout_seconds=30,
        )
        response = await client.send_async(request)

        assert not response.success
        assert "exceeds timeout budget" in response.error_message


class TestGroqErrorHandling:

    @pytest.mark.asyncio
    async def test_empty_choices_returns_error(self, client):
        """Empty choices array should return an error response."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"choices": [], "usage": {}}

        with patch("warden.llm.providers.groq.httpx.AsyncClient") as mock_client_cls, \
             patch("warden.llm.global_rate_limiter.GlobalRateLimiter.get_instance", new_callable=AsyncMock) as mock_limiter:
            mock_limiter.return_value = MagicMock()
            mock_limiter.return_value.acquire = AsyncMock()
            mock_http = AsyncMock()
            mock_http.post = AsyncMock(return_value=mock_response)
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_http

            request = LlmRequest(system_prompt="test", user_message="test", max_tokens=10)
            response = await client.send_async(request)

        assert not response.success
        assert "No response" in response.error_message

    @pytest.mark.asyncio
    async def test_generic_exception_returns_error(self, client):
        """Generic exceptions should be caught and return error response."""
        with patch("warden.llm.global_rate_limiter.GlobalRateLimiter.get_instance", new_callable=AsyncMock) as mock_limiter:
            mock_limiter.return_value = MagicMock()
            mock_limiter.return_value.acquire = AsyncMock(side_effect=RuntimeError("boom"))

            request = LlmRequest(system_prompt="test", user_message="test", max_tokens=10)
            response = await client.send_async(request)

        assert not response.success
