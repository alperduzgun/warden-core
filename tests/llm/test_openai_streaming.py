"""
Unit tests for OpenAI streaming functionality.

Tests both true SSE streaming and fallback mechanisms.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from warden.llm.providers.openai import OpenAIClient
from warden.llm.config import ProviderConfig
from warden.llm.types import LlmProvider


class MockStreamContext:
    """Mock async context manager for httpx stream response."""

    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self.response

    async def __aexit__(self, *args):
        return None


class MockAsyncClient:
    """Mock httpx AsyncClient with streaming support."""

    def __init__(self, response):
        self.response = response
        self.stream_called = False
        self.stream_args = None
        self.stream_kwargs = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    def stream(self, method, url, **kwargs):
        """Return an async context manager for streaming."""
        self.stream_called = True
        self.stream_args = (method, url)
        self.stream_kwargs = kwargs
        return MockStreamContext(self.response)


def create_mock_httpx_client(mock_lines):
    """
    Create a mock httpx client with SSE streaming support.

    Args:
        mock_lines: List of SSE lines to yield

    Returns:
        MockAsyncClient instance
    """
    async def mock_aiter_lines():
        for line in mock_lines:
            yield line

    mock_response = MagicMock()
    mock_response.aiter_lines = mock_aiter_lines
    mock_response.raise_for_status = MagicMock()

    return MockAsyncClient(mock_response)


@pytest.fixture
def openai_config():
    """OpenAI provider config for testing."""
    return ProviderConfig(
        api_key="test-api-key",
        endpoint="https://api.openai.com/v1",
        default_model="gpt-4o",
        enabled=True
    )


@pytest.fixture
def azure_openai_config():
    """Azure OpenAI provider config for testing."""
    return ProviderConfig(
        api_key="test-api-key",
        endpoint="https://test.openai.azure.com",
        default_model="gpt-4o",
        api_version="2024-02-01",
        enabled=True
    )


@pytest.mark.asyncio
async def test_openai_streaming_success(openai_config):
    """Test successful OpenAI streaming with SSE format."""
    client = OpenAIClient(openai_config, LlmProvider.OPENAI)

    # Mock SSE response chunks
    mock_lines = [
        'data: {"choices": [{"delta": {"content": "Hello"}}]}',
        'data: {"choices": [{"delta": {"content": " world"}}]}',
        'data: {"choices": [{"delta": {"content": "!"}}]}',
        'data: [DONE]'
    ]

    mock_client = create_mock_httpx_client(mock_lines)

    with patch('httpx.AsyncClient', return_value=mock_client):
        chunks = []
        async for chunk in client.stream_completion_async(
            prompt="Test prompt",
            system_prompt="Test system"
        ):
            chunks.append(chunk)

    # Verify we got the expected chunks
    assert chunks == ["Hello", " world", "!"]


@pytest.mark.asyncio
async def test_azure_openai_streaming_success(azure_openai_config):
    """Test successful Azure OpenAI streaming with SSE format."""
    client = OpenAIClient(azure_openai_config, LlmProvider.AZURE_OPENAI)

    # Mock SSE response chunks
    mock_lines = [
        'data: {"choices": [{"delta": {"content": "Azure"}}]}',
        'data: {"choices": [{"delta": {"content": " test"}}]}',
        'data: [DONE]'
    ]

    mock_client = create_mock_httpx_client(mock_lines)

    with patch('httpx.AsyncClient', return_value=mock_client):
        chunks = []
        async for chunk in client.stream_completion_async(
            prompt="Test prompt",
            system_prompt="Test system"
        ):
            chunks.append(chunk)

    # Verify we got the expected chunks
    assert chunks == ["Azure", " test"]


@pytest.mark.asyncio
async def test_openai_streaming_skips_empty_chunks(openai_config):
    """Test that streaming skips empty content chunks."""
    client = OpenAIClient(openai_config, LlmProvider.OPENAI)

    # Mock SSE response with empty content chunks
    mock_lines = [
        'data: {"choices": [{"delta": {"content": ""}}]}',  # Empty
        'data: {"choices": [{"delta": {"content": "Hello"}}]}',
        'data: {"choices": [{"delta": {}}]}',  # No content key
        'data: {"choices": [{"delta": {"content": "world"}}]}',
        'data: [DONE]'
    ]

    mock_client = create_mock_httpx_client(mock_lines)

    with patch('httpx.AsyncClient', return_value=mock_client):
        chunks = []
        async for chunk in client.stream_completion_async(
            prompt="Test",
            system_prompt="Test"
        ):
            chunks.append(chunk)

    # Should only get non-empty chunks
    assert chunks == ["Hello", "world"]


@pytest.mark.asyncio
async def test_openai_streaming_handles_malformed_json(openai_config):
    """Test that streaming gracefully handles malformed JSON chunks."""
    client = OpenAIClient(openai_config, LlmProvider.OPENAI)

    # Mock SSE response with malformed JSON
    mock_lines = [
        'data: {"choices": [{"delta": {"content": "Hello"}}]}',
        'data: {malformed json}',  # Should be skipped
        'data: {"choices": [{"delta": {"content": "world"}}]}',
        'data: [DONE]'
    ]

    mock_client = create_mock_httpx_client(mock_lines)

    with patch('httpx.AsyncClient', return_value=mock_client):
        chunks = []
        async for chunk in client.stream_completion_async(
            prompt="Test",
            system_prompt="Test"
        ):
            chunks.append(chunk)

    # Should skip malformed chunk
    assert chunks == ["Hello", "world"]


@pytest.mark.asyncio
async def test_openai_streaming_skips_comments_and_empty_lines(openai_config):
    """Test that streaming skips SSE comments and empty lines."""
    client = OpenAIClient(openai_config, LlmProvider.OPENAI)

    # Mock SSE response with comments and empty lines
    mock_lines = [
        '',  # Empty line
        ': comment line',  # SSE comment
        'data: {"choices": [{"delta": {"content": "Hello"}}]}',
        '',  # Empty line
        'data: {"choices": [{"delta": {"content": "world"}}]}',
        'data: [DONE]'
    ]

    mock_client = create_mock_httpx_client(mock_lines)

    with patch('httpx.AsyncClient', return_value=mock_client):
        chunks = []
        async for chunk in client.stream_completion_async(
            prompt="Test",
            system_prompt="Test"
        ):
            chunks.append(chunk)

    # Should skip comments and empty lines
    assert chunks == ["Hello", "world"]


@pytest.mark.asyncio
async def test_openai_streaming_fallback_on_error(openai_config):
    """Test that streaming falls back to non-streaming on error."""
    client = OpenAIClient(openai_config, LlmProvider.OPENAI)

    # Mock the complete_async method for fallback
    async def mock_complete_async(prompt, system_prompt, model=None):
        from warden.llm.types import LlmResponse
        return LlmResponse(
            content="Fallback response",
            success=True,
            provider=LlmProvider.OPENAI,
            model="gpt-4o",
            duration_ms=100
        )

    # Make streaming fail
    with patch.object(client, '_stream_with_sse', side_effect=Exception("Network error")):
        with patch.object(client, 'complete_async', side_effect=mock_complete_async):
            chunks = []
            async for chunk in client.stream_completion_async(
                prompt="Test",
                system_prompt="Test"
            ):
                chunks.append(chunk)

    # Should get fallback response in chunks
    assert len(chunks) > 0
    assert ''.join(chunks) == "Fallback response"


@pytest.mark.asyncio
async def test_openai_streaming_with_custom_model(openai_config):
    """Test streaming with custom model parameter."""
    client = OpenAIClient(openai_config, LlmProvider.OPENAI)

    # Mock SSE response
    mock_lines = [
        'data: {"choices": [{"delta": {"content": "Test"}}]}',
        'data: [DONE]'
    ]

    mock_client = create_mock_httpx_client(mock_lines)

    with patch('httpx.AsyncClient', return_value=mock_client):
        chunks = []
        async for chunk in client.stream_completion_async(
            prompt="Test",
            system_prompt="Test",
            model="gpt-3.5-turbo"
        ):
            chunks.append(chunk)

    # Verify streaming worked with custom model
    assert chunks == ["Test"]
    # Verify the correct model was used in the API call
    assert mock_client.stream_called
    payload = mock_client.stream_kwargs['json']
    assert payload['model'] == "gpt-3.5-turbo"
