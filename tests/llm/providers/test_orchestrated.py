"""
Tests for warden.llm.providers.orchestrated

Verifies:
1. is_available_async checks both fast and smart tiers
2. Available when only fast tier works
3. Available when only smart tier works
4. Unavailable when no tier works
5. Response attribution fallback (model/provider always populated)
"""

import pytest
from unittest.mock import AsyncMock

from warden.llm.providers.orchestrated import OrchestratedLlmClient
from warden.llm.types import LlmProvider, LlmRequest, LlmResponse
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

        request = LlmRequest(
            system_prompt="test", user_message="test", use_fast_tier=False
        )
        response = await orchestrated.send_async(request)

        assert response.content == "real result"


class TestResponseAttribution:
    """Test that model and provider attribution is always populated on responses.

    Covers issue #146: LlmResponse.model and .provider must never be None
    when the orchestrator returns a successful response.
    """

    @pytest.mark.asyncio
    async def test_smart_tier_response_gets_fallback_model_when_none(self):
        """Smart tier response with model=None gets fallback from smart_model."""
        smart_client = _make_client(provider_val=LlmProvider.OPENAI, available=True)
        smart_client.send_async = AsyncMock(
            return_value=LlmResponse(
                content="analysis result",
                success=True,
                provider=LlmProvider.OPENAI,
                model=None,  # Provider did not set model
            )
        )

        orchestrated = OrchestratedLlmClient(
            smart_client=smart_client,
            fast_clients=[],
            smart_model="gpt-4o",
        )

        request = LlmRequest(
            system_prompt="test", user_message="test", use_fast_tier=False
        )
        response = await orchestrated.send_async(request)

        assert response.success is True
        assert response.model == "gpt-4o"
        assert response.provider == LlmProvider.OPENAI

    @pytest.mark.asyncio
    async def test_smart_tier_response_gets_fallback_provider_when_none(self):
        """Smart tier response with provider=None gets fallback from smart client."""
        smart_client = _make_client(provider_val=LlmProvider.ANTHROPIC, available=True)
        smart_client.send_async = AsyncMock(
            return_value=LlmResponse(
                content="analysis result",
                success=True,
                provider=None,  # Provider not set
                model=None,  # Model not set
            )
        )

        orchestrated = OrchestratedLlmClient(
            smart_client=smart_client,
            fast_clients=[],
            smart_model="claude-3-5-sonnet-20241022",
        )

        request = LlmRequest(
            system_prompt="test", user_message="test", use_fast_tier=False
        )
        response = await orchestrated.send_async(request)

        assert response.success is True
        assert response.provider == LlmProvider.ANTHROPIC
        assert response.model == "claude-3-5-sonnet-20241022"

    @pytest.mark.asyncio
    async def test_smart_tier_preserves_existing_attribution(self):
        """When provider already sets model and provider, orchestrator does not overwrite."""
        smart_client = _make_client(provider_val=LlmProvider.OPENAI, available=True)
        smart_client.send_async = AsyncMock(
            return_value=LlmResponse(
                content="analysis result",
                success=True,
                provider=LlmProvider.OPENAI,
                model="gpt-4o-2024-08-06",  # API returned specific model version
            )
        )

        orchestrated = OrchestratedLlmClient(
            smart_client=smart_client,
            fast_clients=[],
            smart_model="gpt-4o",  # Generic name
        )

        request = LlmRequest(
            system_prompt="test", user_message="test", use_fast_tier=False
        )
        response = await orchestrated.send_async(request)

        assert response.success is True
        assert response.model == "gpt-4o-2024-08-06"  # Original preserved
        assert response.provider == LlmProvider.OPENAI

    @pytest.mark.asyncio
    async def test_smart_tier_fallback_response_gets_attribution(self):
        """When smart fails and fast fallback succeeds, attribution is populated."""
        smart_client = _make_client(provider_val=LlmProvider.OPENAI, available=True)
        smart_client.send_async = AsyncMock(
            return_value=LlmResponse(
                content="", success=False, error_message="Smart failed"
            )
        )

        fast_client = _make_client(provider_val=LlmProvider.OLLAMA, available=True)
        fast_client.send_async = AsyncMock(
            return_value=LlmResponse(
                content="fallback result",
                success=True,
                provider=None,  # Provider forgot to set
                model=None,  # Model forgot to set
            )
        )

        orchestrated = OrchestratedLlmClient(
            smart_client=smart_client,
            fast_clients=[fast_client],
            fast_model="qwen2.5-coder:3b",
        )

        request = LlmRequest(
            system_prompt="test", user_message="test", use_fast_tier=False
        )
        response = await orchestrated.send_async(request)

        assert response.success is True
        assert response.provider == LlmProvider.OLLAMA
        assert response.model == "qwen2.5-coder:3b"

    @pytest.mark.asyncio
    async def test_request_model_takes_precedence_as_fallback(self):
        """When request specifies a model, it is used as fallback over smart_model."""
        smart_client = _make_client(provider_val=LlmProvider.OPENAI, available=True)
        smart_client.send_async = AsyncMock(
            return_value=LlmResponse(
                content="result",
                success=True,
                provider=LlmProvider.OPENAI,
                model=None,  # API did not return model
            )
        )

        orchestrated = OrchestratedLlmClient(
            smart_client=smart_client,
            fast_clients=[],
            smart_model="gpt-4o",
        )

        request = LlmRequest(
            system_prompt="test",
            user_message="test",
            model="gpt-4-turbo",  # Explicit model in request
            use_fast_tier=False,
        )
        response = await orchestrated.send_async(request)

        assert response.success is True
        # target_model = request.model or self.smart_model -> "gpt-4-turbo"
        assert response.model == "gpt-4-turbo"

    def test_ensure_attribution_static_method(self):
        """Unit test for _ensure_attribution helper."""
        response = LlmResponse(
            content="test", success=True, provider=None, model=None
        )

        result = OrchestratedLlmClient._ensure_attribution(
            response,
            fallback_provider=LlmProvider.GROQ,
            fallback_model="llama-3.3-70b-versatile",
        )

        assert result.provider == LlmProvider.GROQ
        assert result.model == "llama-3.3-70b-versatile"
        assert result is response  # Mutated in-place

    def test_ensure_attribution_preserves_existing(self):
        """_ensure_attribution should not overwrite existing values."""
        response = LlmResponse(
            content="test",
            success=True,
            provider=LlmProvider.ANTHROPIC,
            model="claude-3-5-sonnet-20241022",
        )

        result = OrchestratedLlmClient._ensure_attribution(
            response,
            fallback_provider=LlmProvider.OPENAI,
            fallback_model="gpt-4o",
        )

        assert result.provider == LlmProvider.ANTHROPIC  # Not overwritten
        assert result.model == "claude-3-5-sonnet-20241022"  # Not overwritten

    def test_ensure_attribution_handles_none_fallbacks(self):
        """_ensure_attribution with None fallbacks should not crash."""
        response = LlmResponse(
            content="test", success=True, provider=None, model=None
        )

        result = OrchestratedLlmClient._ensure_attribution(
            response,
            fallback_provider=None,
            fallback_model=None,
        )

        assert result.provider is None
        assert result.model is None
