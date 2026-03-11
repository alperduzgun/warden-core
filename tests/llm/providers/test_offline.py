"""
Tests for warden.llm.providers.offline

Verifies:
1. OfflineClient returns LlmProvider.UNKNOWN
2. Complete async returns successful offline response
"""

import pytest

from warden.llm.providers.offline import OfflineClient
from warden.llm.types import LlmProvider


class TestOfflineClient:
    """Test offline fallback LLM client."""

    def test_offline_client_provider_returns_unknown(self):
        """Verify OfflineClient provider is UNKNOWN."""
        client = OfflineClient()
        assert client.provider == LlmProvider.UNKNOWN

    @pytest.mark.asyncio
    async def test_offline_client_complete_async_returns_response(self):
        """Verify complete_async returns successful offline response."""
        client = OfflineClient()
        response = await client.complete_async("test prompt")

        assert response.success is True
        assert response.provider == LlmProvider.UNKNOWN
        assert response.model == "offline-fallback"
        assert "[Offline Mode]" in response.content
        # Verify token counts are zero in offline mode
        assert response.prompt_tokens == 0
        assert response.completion_tokens == 0
        assert response.total_tokens == 0

    @pytest.mark.asyncio
    async def test_offline_client_is_always_available(self):
        """Verify offline client is always available as fallback."""
        client = OfflineClient()
        is_available = await client.is_available_async()
        assert is_available is True

    @pytest.mark.asyncio
    async def test_offline_client_send_async_returns_response(self):
        """Verify send_async returns successful offline response."""
        from warden.llm.types import LlmRequest

        client = OfflineClient()
        request = LlmRequest(
            system_prompt="test system",
            user_message="test message",
        )
        response = await client.send_async(request)

        assert response.success is True
        assert response.provider == LlmProvider.UNKNOWN
        assert response.model == "offline-fallback"

    @pytest.mark.asyncio
    async def test_offline_client_analyze_security_returns_empty(self):
        """Verify analyze_security_async returns empty findings in offline mode."""
        client = OfflineClient()
        result = await client.analyze_security_async("code_content", "python")

        assert result == {"findings": []}

    @pytest.mark.asyncio
    async def test_complete_async_accepts_max_tokens(self):
        """Regression: complete_async must accept max_tokens kwarg (Issue #356).

        This test MUST FAIL if someone removes the max_tokens parameter from
        OfflineClient.complete_async.
        """
        client = OfflineClient()
        try:
            response = await client.complete_async("test", max_tokens=500)
        except TypeError as exc:
            pytest.fail(
                f"complete_async raised TypeError with max_tokens=500: {exc}"
            )
        assert response.success is True

    @pytest.mark.asyncio
    async def test_complete_async_max_tokens_default_still_works(self):
        """Verify complete_async works without explicitly passing max_tokens."""
        client = OfflineClient()
        response = await client.complete_async("test prompt")
        assert response.success is True
