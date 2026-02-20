"""
Tests for warden.llm.providers.orchestrated

Verifies:
1. is_available_async checks both fast and smart tiers
2. Available when only fast tier works
3. Available when only smart tier works
4. Unavailable when no tier works
"""

import pytest
from unittest.mock import AsyncMock

from warden.llm.providers.orchestrated import OrchestratedLlmClient
from warden.llm.types import LlmProvider, LlmResponse
from warden.shared.infrastructure.exceptions import ExternalServiceError


# Helper to create mock client
def _make_client(provider_val=LlmProvider.OLLAMA, available=True):
    """Create a mock LLM client for testing."""
    client = AsyncMock()
    client.provider = provider_val
    client.is_available_async = AsyncMock(return_value=available)
    return client


class TestOrchestratedAvailability:
    """Test availability checking with fast/smart tier fallback."""

    @pytest.mark.asyncio
    async def test_available_when_only_fast_tier_works(self):
        """System should be available when fast tier works but smart tier fails."""
        smart_client = _make_client(provider_val=LlmProvider.OPENAI, available=False)
        fast_client = _make_client(provider_val=LlmProvider.OLLAMA, available=True)

        orchestrated = OrchestratedLlmClient(
            smart_client=smart_client,
            fast_clients=[fast_client],
        )

        is_available = await orchestrated.is_available_async()
        assert is_available is True

    @pytest.mark.asyncio
    async def test_unavailable_when_no_tier_works(self):
        """System should be unavailable when both tiers fail."""
        smart_client = _make_client(provider_val=LlmProvider.OPENAI, available=False)
        fast_client = _make_client(provider_val=LlmProvider.OLLAMA, available=False)

        orchestrated = OrchestratedLlmClient(
            smart_client=smart_client,
            fast_clients=[fast_client],
        )

        is_available = await orchestrated.is_available_async()
        assert is_available is False

    @pytest.mark.asyncio
    async def test_available_when_only_smart_tier_works(self):
        """System should be available when smart tier works even if fast tier unavailable."""
        smart_client = _make_client(provider_val=LlmProvider.OPENAI, available=True)
        fast_client = _make_client(provider_val=LlmProvider.OLLAMA, available=False)

        orchestrated = OrchestratedLlmClient(
            smart_client=smart_client,
            fast_clients=[fast_client],
        )

        is_available = await orchestrated.is_available_async()
        assert is_available is True

    @pytest.mark.asyncio
    async def test_available_with_no_fast_tier(self):
        """System should be available when smart tier works and no fast tier configured."""
        smart_client = _make_client(provider_val=LlmProvider.OPENAI, available=True)

        orchestrated = OrchestratedLlmClient(
            smart_client=smart_client,
            fast_clients=[],
        )

        is_available = await orchestrated.is_available_async()
        assert is_available is True

    @pytest.mark.asyncio
    async def test_checks_multiple_fast_providers(self):
        """Should check all fast providers and return True if any available."""
        smart_client = _make_client(provider_val=LlmProvider.OPENAI, available=False)
        fast_client1 = _make_client(provider_val=LlmProvider.OLLAMA, available=False)
        fast_client2 = _make_client(provider_val=LlmProvider.GROQ, available=True)
        fast_client3 = _make_client(provider_val=LlmProvider.DEEPSEEK, available=False)

        orchestrated = OrchestratedLlmClient(
            smart_client=smart_client,
            fast_clients=[fast_client1, fast_client2, fast_client3],
        )

        is_available = await orchestrated.is_available_async()
        assert is_available is True

    @pytest.mark.asyncio
    async def test_handles_exception_in_fast_tier_check(self):
        """Should continue checking other providers if one raises exception."""
        smart_client = _make_client(provider_val=LlmProvider.OPENAI, available=True)

        # Create a client that raises an exception
        broken_client = AsyncMock()
        broken_client.provider = LlmProvider.OLLAMA
        broken_client.is_available_async = AsyncMock(side_effect=Exception("Network error"))

        orchestrated = OrchestratedLlmClient(
            smart_client=smart_client,
            fast_clients=[broken_client],
        )

        # Should fall back to smart tier and be available
        is_available = await orchestrated.is_available_async()
        assert is_available is True

    @pytest.mark.asyncio
    async def test_provider_property_returns_smart_provider(self):
        """Verify provider property returns smart client's provider."""
        smart_client = _make_client(provider_val=LlmProvider.OPENAI, available=True)
        fast_client = _make_client(provider_val=LlmProvider.OLLAMA, available=True)

        orchestrated = OrchestratedLlmClient(
            smart_client=smart_client,
            fast_clients=[fast_client],
        )

        assert orchestrated.provider == LlmProvider.OPENAI


class TestSmartTierFallback:
    """Test smart tier failure triggers fallback to fast clients."""

    @pytest.mark.asyncio
    async def test_smart_failure_falls_back_to_fast_client(self):
        """When smart tier returns empty content, should try fast clients."""
        smart_client = _make_client(provider_val=LlmProvider.OPENAI, available=True)
        smart_client.send_async = AsyncMock(
            return_value=LlmResponse(
                content="", success=False, error_message="Empty content in response"
            )
        )

        fast_client = _make_client(provider_val=LlmProvider.OLLAMA, available=True)
        fast_client.send_async = AsyncMock(
            return_value=LlmResponse(content="fallback result", success=True)
        )

        orchestrated = OrchestratedLlmClient(
            smart_client=smart_client,
            fast_clients=[fast_client],
        )

        from warden.llm.types import LlmRequest

        request = LlmRequest(
            system_prompt="test", user_message="test", use_fast_tier=False
        )
        response = await orchestrated.send_async(request)

        assert response.success is True
        assert response.content == "fallback result"
        fast_client.send_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_smart_failure_no_fast_clients_raises(self):
        """When smart tier fails and no fast clients, should raise."""
        smart_client = _make_client(provider_val=LlmProvider.OPENAI, available=True)
        smart_client.send_async = AsyncMock(
            return_value=LlmResponse(
                content="", success=False, error_message="Empty content in response"
            )
        )

        orchestrated = OrchestratedLlmClient(
            smart_client=smart_client,
            fast_clients=[],
        )

        from warden.llm.types import LlmRequest

        request = LlmRequest(
            system_prompt="test", user_message="test", use_fast_tier=False
        )
        with pytest.raises(ExternalServiceError, match="Smart tier failed"):
            await orchestrated.send_async(request)

    @pytest.mark.asyncio
    async def test_smart_failure_skips_unavailable_fast_clients(self):
        """Should skip fast clients that report unavailable."""
        smart_client = _make_client(provider_val=LlmProvider.OPENAI, available=True)
        smart_client.send_async = AsyncMock(
            return_value=LlmResponse(
                content="", success=False, error_message="Empty content"
            )
        )

        unavailable_fast = _make_client(provider_val=LlmProvider.OLLAMA, available=False)
        available_fast = _make_client(provider_val=LlmProvider.GROQ, available=True)
        available_fast.send_async = AsyncMock(
            return_value=LlmResponse(content="groq result", success=True)
        )

        orchestrated = OrchestratedLlmClient(
            smart_client=smart_client,
            fast_clients=[unavailable_fast, available_fast],
        )

        from warden.llm.types import LlmRequest

        request = LlmRequest(
            system_prompt="test", user_message="test", use_fast_tier=False
        )
        response = await orchestrated.send_async(request)

        assert response.success is True
        assert response.content == "groq result"
        unavailable_fast.send_async.assert_not_called()

    @pytest.mark.asyncio
    async def test_smart_failure_all_fast_fail_raises_original(self):
        """When smart and all fast clients fail, raises original smart error."""
        smart_client = _make_client(provider_val=LlmProvider.OPENAI, available=True)
        smart_client.send_async = AsyncMock(
            return_value=LlmResponse(
                content="", success=False, error_message="Empty content in response"
            )
        )

        fast_client = _make_client(provider_val=LlmProvider.OLLAMA, available=True)
        fast_client.send_async = AsyncMock(side_effect=Exception("Ollama down"))

        orchestrated = OrchestratedLlmClient(
            smart_client=smart_client,
            fast_clients=[fast_client],
        )

        from warden.llm.types import LlmRequest

        request = LlmRequest(
            system_prompt="test", user_message="test", use_fast_tier=False
        )
        with pytest.raises(ExternalServiceError, match="Empty content in response"):
            await orchestrated.send_async(request)

    @pytest.mark.asyncio
    async def test_smart_failure_fast_returns_empty_continues(self):
        """Fast client returning empty content should be skipped."""
        smart_client = _make_client(provider_val=LlmProvider.OPENAI, available=True)
        smart_client.send_async = AsyncMock(
            return_value=LlmResponse(
                content="", success=False, error_message="Empty content"
            )
        )

        # First fast client returns success but empty content
        fast1 = _make_client(provider_val=LlmProvider.OLLAMA, available=True)
        fast1.send_async = AsyncMock(
            return_value=LlmResponse(content="", success=True)
        )

        # Second fast client returns actual content
        fast2 = _make_client(provider_val=LlmProvider.GROQ, available=True)
        fast2.send_async = AsyncMock(
            return_value=LlmResponse(content="real result", success=True)
        )

        orchestrated = OrchestratedLlmClient(
            smart_client=smart_client,
            fast_clients=[fast1, fast2],
        )

        from warden.llm.types import LlmRequest

        request = LlmRequest(
            system_prompt="test", user_message="test", use_fast_tier=False
        )
        response = await orchestrated.send_async(request)

        assert response.content == "real result"
