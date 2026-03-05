"""Tests for provider-level StructuredPrompt / cache_control support."""

from warden.llm.types import StructuredPrompt
from warden.llm.providers.anthropic import AnthropicClient
from warden.llm.providers.openai import OpenAIClient


class TestAnthropicCachePayload:
    """Tests for AnthropicClient.build_system_payload."""

    def test_plain_string_fallback(self):
        """Without structured prompt, returns plain string."""
        result = AnthropicClient.build_system_payload("You are Warden.")
        assert result == "You are Warden."

    def test_structured_prompt_produces_blocks(self):
        """With StructuredPrompt, returns list of content blocks."""
        sp = StructuredPrompt(
            system_context="Severity guide + rules",
            file_context="File: test.py\nCode: x=1",
        )
        result = AnthropicClient.build_system_payload("ignored", sp)
        assert isinstance(result, list)
        assert len(result) == 2

    def test_first_block_has_cache_control(self):
        """First block (system_context) should have cache_control hint."""
        sp = StructuredPrompt(
            system_context="Stable context",
            file_context="Variable content",
        )
        result = AnthropicClient.build_system_payload("ignored", sp)
        first_block = result[0]
        assert first_block["type"] == "text"
        assert first_block["text"] == "Stable context"
        assert first_block["cache_control"] == {"type": "ephemeral"}

    def test_second_block_no_cache_control(self):
        """Second block (file_context) should NOT have cache_control."""
        sp = StructuredPrompt(
            system_context="Stable",
            file_context="Variable",
        )
        result = AnthropicClient.build_system_payload("ignored", sp)
        second_block = result[1]
        assert second_block["type"] == "text"
        assert second_block["text"] == "Variable"
        assert "cache_control" not in second_block


class TestOpenAICacheMessages:
    """Tests for OpenAIClient.build_messages."""

    def test_plain_fallback(self):
        """Without structured prompt, returns standard 2-message layout."""
        result = OpenAIClient.build_messages("sys", "user")
        assert len(result) == 2
        assert result[0] == {"role": "system", "content": "sys"}
        assert result[1] == {"role": "user", "content": "user"}

    def test_structured_prompt_produces_three_messages(self):
        """With StructuredPrompt, returns 3 messages for cache-friendly prefix."""
        sp = StructuredPrompt(
            system_context="Stable system context",
            file_context="Variable file context",
        )
        result = OpenAIClient.build_messages("ignored", "user msg", sp)
        assert len(result) == 3

    def test_first_message_is_system_context(self):
        """First message should be system role with system_context."""
        sp = StructuredPrompt(
            system_context="Cacheable rules",
            file_context="Per-file data",
        )
        result = OpenAIClient.build_messages("ignored", "user", sp)
        assert result[0]["role"] == "system"
        assert result[0]["content"] == "Cacheable rules"

    def test_second_message_is_file_context(self):
        """Second message should be system role with file_context."""
        sp = StructuredPrompt(
            system_context="Rules",
            file_context="File data",
        )
        result = OpenAIClient.build_messages("ignored", "user", sp)
        assert result[1]["role"] == "system"
        assert result[1]["content"] == "File data"

    def test_third_message_is_user(self):
        """Third message should be user role with user_message."""
        sp = StructuredPrompt(
            system_context="Rules",
            file_context="File",
        )
        result = OpenAIClient.build_messages("ignored", "Analyze this", sp)
        assert result[2]["role"] == "user"
        assert result[2]["content"] == "Analyze this"
