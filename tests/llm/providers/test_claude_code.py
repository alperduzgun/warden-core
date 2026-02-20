"""
Tests for warden.llm.providers.claude_code

Verifies:
1. Empty content triggers retry with truncated prompt
2. Short prompts do NOT trigger retry
3. Non-empty-content errors do NOT trigger retry
4. Truncation preserves start and end of prompt
"""

import pytest
from unittest.mock import AsyncMock, patch

from warden.llm.providers.claude_code import ClaudeCodeClient, _TRUNCATION_RETRY_THRESHOLD
from warden.llm.config import ProviderConfig
from warden.llm.types import LlmRequest, LlmResponse


@pytest.fixture
def client():
    return ClaudeCodeClient(ProviderConfig(enabled=True, default_model="test"))


class TestTruncationRetry:
    """Test empty-content retry with truncated prompt."""

    @pytest.mark.asyncio
    async def test_empty_content_large_prompt_retries(self, client):
        """Empty content + large prompt should retry once with truncation."""
        empty_response = LlmResponse(
            content="", success=False, error_message="Empty content in response",
            provider=client.provider, model="test", duration_ms=100,
        )
        success_response = LlmResponse(
            content="analysis result", success=True,
            provider=client.provider, model="test", duration_ms=200,
        )

        with patch.object(client, "_execute_cli", new_callable=AsyncMock) as mock_cli:
            mock_cli.side_effect = [empty_response, success_response]

            request = LlmRequest(
                system_prompt="system",
                user_message="x" * (_TRUNCATION_RETRY_THRESHOLD + 1000),
                use_fast_tier=False,
            )
            response = await client.send_async(request)

        assert response.success is True
        assert response.content == "analysis result"
        assert mock_cli.call_count == 2
        # Second call should have a shorter prompt
        second_prompt = mock_cli.call_args_list[1][0][0]
        first_prompt = mock_cli.call_args_list[0][0][0]
        assert len(second_prompt) < len(first_prompt)

    @pytest.mark.asyncio
    async def test_empty_content_short_prompt_no_retry(self, client):
        """Empty content + short prompt should NOT retry."""
        empty_response = LlmResponse(
            content="", success=False, error_message="Empty content in response",
            provider=client.provider, model="test", duration_ms=100,
        )

        with patch.object(client, "_execute_cli", new_callable=AsyncMock) as mock_cli:
            mock_cli.return_value = empty_response

            request = LlmRequest(
                system_prompt="s",
                user_message="short prompt",
                use_fast_tier=False,
            )
            response = await client.send_async(request)

        assert response.success is False
        assert mock_cli.call_count == 1  # No retry

    @pytest.mark.asyncio
    async def test_non_empty_error_no_retry(self, client):
        """Non-empty-content errors (timeout, CLI error) should NOT retry."""
        timeout_response = LlmResponse(
            content="", success=False, error_message="Timeout after 120s",
            provider=client.provider, model="test", duration_ms=120000,
        )

        with patch.object(client, "_execute_cli", new_callable=AsyncMock) as mock_cli:
            mock_cli.return_value = timeout_response

            request = LlmRequest(
                system_prompt="system",
                user_message="x" * (_TRUNCATION_RETRY_THRESHOLD + 1000),
                use_fast_tier=False,
            )
            response = await client.send_async(request)

        assert response.success is False
        assert "Timeout" in response.error_message
        assert mock_cli.call_count == 1  # No retry for non-empty-content errors

    @pytest.mark.asyncio
    async def test_retry_also_fails_returns_second_error(self, client):
        """If retry also returns empty, return the retry response (no infinite loop)."""
        empty1 = LlmResponse(
            content="", success=False, error_message="Empty content in response",
            provider=client.provider, model="test", duration_ms=100,
        )
        empty2 = LlmResponse(
            content="", success=False, error_message="Empty content in response",
            provider=client.provider, model="test", duration_ms=150,
        )

        with patch.object(client, "_execute_cli", new_callable=AsyncMock) as mock_cli:
            mock_cli.side_effect = [empty1, empty2]

            request = LlmRequest(
                system_prompt="system",
                user_message="x" * (_TRUNCATION_RETRY_THRESHOLD + 1000),
                use_fast_tier=False,
            )
            response = await client.send_async(request)

        assert response.success is False
        assert mock_cli.call_count == 2  # Retried once, then gave up


class TestTruncatePrompt:
    """Test prompt truncation preserves structure."""

    def test_preserves_start_and_end(self, client):
        """Truncated prompt should keep beginning (system) and end (code)."""
        prompt = "START_MARKER " + "x" * 10000 + " END_MARKER"
        truncated = client._truncate_prompt(prompt)

        assert truncated.startswith("START_MARKER")
        assert truncated.endswith("END_MARKER")
        assert len(truncated) < len(prompt)
        assert "[...truncated for retry...]" in truncated

    def test_ratio_controls_size(self, client):
        """Custom ratio should control output size."""
        prompt = "a" * 10000
        truncated = client._truncate_prompt(prompt, ratio=0.3)
        # 30% of 10000 = 3000, plus the separator text
        assert len(truncated) < 3200
