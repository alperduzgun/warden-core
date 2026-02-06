"""
Unit tests for Claude Code LLM Client

Tests cover:
- Initialization
- Input validation (fail-fast)
- Response parsing
- Error handling
- Availability check
"""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from warden.llm.providers.claude_code import (
    ClaudeCodeClient,
    detect_claude_code,
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_MODEL,
    MAX_PROMPT_LENGTH,
)
from warden.llm.config import ProviderConfig
from warden.llm.types import LlmRequest, LlmProvider


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def config():
    """Default provider config."""
    return ProviderConfig(enabled=True)


@pytest.fixture
def client(config):
    """Claude Code client instance."""
    return ClaudeCodeClient(config)


@pytest.fixture
def basic_request():
    """Basic LLM request."""
    return LlmRequest(
        system_prompt="You are a helpful assistant.",
        user_message="Hello, world!",
    )


# =============================================================================
# INITIALIZATION TESTS
# =============================================================================

class TestInitialization:
    """Test client initialization."""

    def test_default_model(self, config):
        """Uses default model when not specified."""
        client = ClaudeCodeClient(config)
        assert client._default_model == DEFAULT_MODEL

    def test_custom_model(self):
        """Uses custom model when specified."""
        config = ProviderConfig(enabled=True, default_model="claude-opus-4")
        client = ClaudeCodeClient(config)
        assert client._default_model == "claude-opus-4"

    def test_default_timeout(self, client):
        """Uses default timeout."""
        assert client._timeout == DEFAULT_TIMEOUT_SECONDS

    def test_provider_property(self, client):
        """Provider property returns CLAUDE_CODE."""
        assert client.provider == LlmProvider.CLAUDE_CODE


# =============================================================================
# INPUT VALIDATION TESTS
# =============================================================================

class TestInputValidation:
    """Test input validation (fail-fast)."""

    @pytest.mark.asyncio
    async def test_empty_message_rejected(self, client):
        """Empty user message returns error."""
        request = LlmRequest(system_prompt="test", user_message="")
        response = await client.send_async(request)

        assert response.success is False
        assert "Empty user message" in response.error_message

    @pytest.mark.asyncio
    async def test_prompt_too_large(self, client):
        """Oversized prompt returns error."""
        request = LlmRequest(
            system_prompt="x" * (MAX_PROMPT_LENGTH + 1),
            user_message="test",
        )
        response = await client.send_async(request)

        assert response.success is False
        assert "too large" in response.error_message.lower()


# =============================================================================
# RESPONSE PARSING TESTS
# =============================================================================

class TestResponseParsing:
    """Test CLI response parsing."""

    def test_parse_json_response(self, client):
        """Parses JSON response correctly."""
        json_response = json.dumps({
            "result": "Hello! How can I help?",
            "usage": {"input_tokens": 10, "output_tokens": 20}
        }).encode()

        response = client._parse_response(json_response, "test-model", 100)

        assert response.success is True
        assert response.content == "Hello! How can I help?"
        assert response.prompt_tokens == 10
        assert response.completion_tokens == 20
        assert response.total_tokens == 30

    def test_parse_content_field(self, client):
        """Parses 'content' field if 'result' missing."""
        json_response = json.dumps({
            "content": "Alternative content field"
        }).encode()

        response = client._parse_response(json_response, "test-model", 100)

        assert response.success is True
        assert response.content == "Alternative content field"

    def test_parse_plain_text(self, client):
        """Handles non-JSON (plain text) response."""
        plain_response = b"Just plain text response"

        response = client._parse_response(plain_response, "test-model", 100)

        assert response.success is True
        assert response.content == "Just plain text response"

    def test_parse_empty_response(self, client):
        """Empty response returns error."""
        response = client._parse_response(b"", "test-model", 100)

        assert response.success is False
        assert "Empty response" in response.error_message


# =============================================================================
# CLI EXECUTION TESTS
# =============================================================================

class TestCliExecution:
    """Test CLI subprocess execution."""

    @pytest.mark.asyncio
    async def test_successful_execution(self, client, basic_request):
        """Successful CLI execution returns content."""
        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(return_value=(
            json.dumps({"result": "Success!"}).encode(),
            b""
        ))

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            response = await client.send_async(basic_request)

        assert response.success is True
        assert response.content == "Success!"

    @pytest.mark.asyncio
    async def test_cli_error_returncode(self, client, basic_request):
        """Non-zero return code returns error."""
        mock_process = AsyncMock()
        mock_process.returncode = 1
        mock_process.communicate = AsyncMock(return_value=(
            b"",
            b"Command failed"
        ))

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            response = await client.send_async(basic_request)

        assert response.success is False
        assert "CLI error" in response.error_message

    @pytest.mark.asyncio
    async def test_timeout_handling(self, client, basic_request):
        """Timeout returns error response."""
        mock_process = AsyncMock()
        mock_process.communicate = AsyncMock(side_effect=asyncio.TimeoutError())

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            response = await client.send_async(basic_request)

        assert response.success is False
        assert "Timeout" in response.error_message

    @pytest.mark.asyncio
    async def test_exception_handling(self, client, basic_request):
        """Exception returns error response."""
        with patch("asyncio.create_subprocess_exec", side_effect=OSError("CLI not found")):
            response = await client.send_async(basic_request)

        assert response.success is False
        assert "CLI not found" in response.error_message


# =============================================================================
# AVAILABILITY CHECK TESTS
# =============================================================================

class TestAvailability:
    """Test availability check."""

    @pytest.mark.asyncio
    async def test_available_when_cli_works(self, client):
        """Returns True when CLI works."""
        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(return_value=(b"1.0.0", b""))

        with patch("shutil.which", return_value="/usr/bin/claude"):
            with patch("asyncio.create_subprocess_exec", return_value=mock_process):
                result = await client.is_available_async()

        assert result is True

    @pytest.mark.asyncio
    async def test_unavailable_when_not_in_path(self, client):
        """Returns False when CLI not in PATH."""
        with patch("shutil.which", return_value=None):
            result = await client.is_available_async()

        assert result is False

    @pytest.mark.asyncio
    async def test_unavailable_on_error(self, client):
        """Returns False on subprocess error."""
        with patch("shutil.which", return_value="/usr/bin/claude"):
            with patch("asyncio.create_subprocess_exec", side_effect=OSError()):
                result = await client.is_available_async()

        assert result is False


# =============================================================================
# DETECT FUNCTION TESTS
# =============================================================================

class TestDetectClaudeCode:
    """Test detect_claude_code utility function."""

    @pytest.mark.asyncio
    async def test_detect_returns_bool(self):
        """detect_claude_code returns boolean."""
        with patch("shutil.which", return_value=None):
            result = await detect_claude_code()

        assert isinstance(result, bool)
        assert result is False


# =============================================================================
# HELPER METHOD TESTS
# =============================================================================

class TestHelperMethods:
    """Test helper methods."""

    def test_calc_duration_ms(self, client):
        """Duration calculation returns positive integer."""
        import time
        start = time.perf_counter()
        time.sleep(0.01)  # 10ms
        duration = client._calc_duration_ms(start)

        assert isinstance(duration, int)
        assert duration >= 10  # At least 10ms

    def test_error_response_format(self, client):
        """Error response has correct format."""
        response = client._error_response("Test error", "test-model", 100)

        assert response.success is False
        assert response.content == ""
        assert response.error_message == "Test error"
        assert response.model == "test-model"
        assert response.duration_ms == 100
        assert response.provider == LlmProvider.CLAUDE_CODE
