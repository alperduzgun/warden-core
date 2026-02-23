"""
Tests for the Agentic Loop — shared runner and ILlmClient integration.

Covers:
- Standalone functions in agentic_runner.py (detect, validate, execute, loop)
- ILlmClient.send_with_tools_async() integration
- LLMPhaseBase delegation (no longer has its own loop)
- Tool instructions module constants
"""

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from warden.llm.agentic_runner import (
    detect_tool_use,
    execute_tool_async,
    is_claude_code_provider,
    run_agentic_loop_async,
    validate_tool_arguments,
)
from warden.llm.prompts.tool_instructions import (
    AVAILABLE_TOOLS,
    KNOWN_TOOL_NAMES,
    MAX_TOOL_ITERATIONS,
    TOOL_INSTRUCTION_SNIPPET,
    get_tool_enhanced_prompt,
)


# ============================================================
# Fixtures & Helpers
# ============================================================


@dataclass
class FakeLlmResponse:
    """Minimal LLM response stub."""

    content: str = ""
    success: bool = True
    prompt_tokens: int = 10
    completion_tokens: int = 20
    total_tokens: int = 30
    error_message: str | None = None


# ============================================================
# Tool Instructions Module Tests
# ============================================================


class TestToolInstructionsModule:
    """Tests for tool_instructions.py constants and helpers."""

    def test_max_tool_iterations_is_3(self):
        assert MAX_TOOL_ITERATIONS == 3

    def test_available_tools_has_expected_tools(self):
        names = {t["name"] for t in AVAILABLE_TOOLS}
        assert "warden_query_symbol" in names
        assert "warden_graph_search" in names

    def test_known_tool_names_matches_available(self):
        expected = {t["name"] for t in AVAILABLE_TOOLS}
        assert KNOWN_TOOL_NAMES == expected

    def test_tool_instruction_snippet_contains_tools(self):
        assert "warden_query_symbol" in TOOL_INSTRUCTION_SNIPPET
        assert "warden_graph_search" in TOOL_INSTRUCTION_SNIPPET
        assert "tool_use" in TOOL_INSTRUCTION_SNIPPET

    def test_get_tool_enhanced_prompt_appends(self):
        base = "You are a test bot."
        enhanced = get_tool_enhanced_prompt(base)
        assert enhanced.startswith(base)
        assert "warden_query_symbol" in enhanced
        assert len(enhanced) > len(base)

    def test_get_tool_enhanced_prompt_preserves_base(self):
        base = "Original prompt content here."
        enhanced = get_tool_enhanced_prompt(base)
        assert base in enhanced


# ============================================================
# Standalone Tool Use Detection Tests
# ============================================================


class TestDetectToolUse:
    """Tests for detect_tool_use() standalone function."""

    def test_detects_valid_tool_call(self):
        content = '{"tool_use": {"name": "warden_query_symbol", "arguments": {"name": "Foo"}}}'
        result = detect_tool_use(content)
        assert result is not None
        assert result["name"] == "warden_query_symbol"
        assert result["arguments"]["name"] == "Foo"

    def test_detects_tool_call_with_markdown(self):
        content = '```json\n{"tool_use": {"name": "warden_graph_search", "arguments": {"query": "auth"}}}\n```'
        result = detect_tool_use(content)
        assert result is not None
        assert result["name"] == "warden_graph_search"

    def test_returns_none_for_normal_json(self):
        content = '{"findings": [{"severity": "high", "message": "SQL injection"}]}'
        result = detect_tool_use(content)
        assert result is None

    def test_returns_none_for_empty_content(self):
        assert detect_tool_use("") is None
        assert detect_tool_use(None) is None

    def test_returns_none_for_plain_text(self):
        content = "This is a normal text response about tool_use concept."
        result = detect_tool_use(content)
        assert result is None

    def test_returns_none_for_malformed_json(self):
        content = '{"tool_use": {"name": broken}}'
        result = detect_tool_use(content)
        assert result is None or isinstance(result, dict)

    def test_returns_none_for_missing_name(self):
        content = '{"tool_use": {"arguments": {"query": "test"}}}'
        result = detect_tool_use(content)
        assert result is None


# ============================================================
# Standalone Tool Argument Validation Tests
# ============================================================


class TestValidateToolArguments:
    """Tests for validate_tool_arguments() standalone function."""

    def test_valid_query_symbol_args(self):
        missing = validate_tool_arguments("warden_query_symbol", {"name": "Foo"})
        assert missing == []

    def test_missing_required_arg(self):
        missing = validate_tool_arguments("warden_query_symbol", {})
        assert "name" in missing

    def test_valid_graph_search_args(self):
        missing = validate_tool_arguments("warden_graph_search", {"query": "auth"})
        assert missing == []

    def test_unknown_tool_returns_empty(self):
        missing = validate_tool_arguments("unknown_tool", {"arg": "val"})
        assert missing == []


# ============================================================
# Claude Code Provider Bypass Tests
# ============================================================


class TestClaudeCodeBypass:
    """Tests for is_claude_code_provider() standalone function."""

    def test_none_client_returns_false(self):
        assert is_claude_code_provider(None) is False

    def test_openai_provider_returns_false(self):
        mock = MagicMock()
        mock.provider = MagicMock()
        mock.provider.__str__ = lambda self: "OPENAI"
        assert is_claude_code_provider(mock) is False

    def test_ollama_provider_returns_false(self):
        mock = MagicMock()
        mock.provider = MagicMock()
        mock.provider.__str__ = lambda self: "OLLAMA"
        assert is_claude_code_provider(mock) is False

    def test_claude_code_provider_returns_true(self):
        mock = MagicMock()
        mock.provider = MagicMock()
        mock.provider.__str__ = lambda self: "CLAUDE_CODE"
        assert is_claude_code_provider(mock) is True

    def test_claude_code_variant_returns_true(self):
        mock = MagicMock()
        mock.provider = MagicMock()
        mock.provider.__str__ = lambda self: "LlmProvider.CLAUDE_CODE"
        assert is_claude_code_provider(mock) is True


# ============================================================
# Standalone Agentic Loop Tests
# ============================================================


class TestAgenticRunner:
    """Tests for run_agentic_loop_async() standalone function."""

    @pytest.mark.asyncio
    async def test_no_tool_use_returns_immediately(self):
        """If initial response has no tool call, loop returns it as-is."""
        initial = FakeLlmResponse(content='{"findings": []}')
        llm_call_fn = AsyncMock()

        result = await run_agentic_loop_async(
            initial_response=initial,
            llm_call_fn=llm_call_fn,
            original_prompt="test",
            system_prompt="test",
            project_root=Path("/tmp/test-project"),
        )
        assert result is initial
        llm_call_fn.assert_not_called()

    @pytest.mark.asyncio
    async def test_single_tool_call_then_final(self):
        """LLM calls a tool once, then returns final analysis."""
        tool_call_response = FakeLlmResponse(
            content='{"tool_use": {"name": "warden_query_symbol", "arguments": {"name": "Foo"}}}'
        )
        final_response = FakeLlmResponse(content='{"findings": []}')
        llm_call_fn = AsyncMock(return_value=final_response)

        with patch(
            "warden.llm.agentic_runner.execute_tool_async",
            new_callable=AsyncMock,
            return_value="Symbol Foo: class at line 42",
        ):
            result = await run_agentic_loop_async(
                initial_response=tool_call_response,
                llm_call_fn=llm_call_fn,
                original_prompt="test",
                system_prompt="test",
                project_root=Path("/tmp/test-project"),
            )

        assert result is final_response
        llm_call_fn.assert_called_once()

    @pytest.mark.asyncio
    async def test_max_iterations_circuit_breaker(self):
        """Loop terminates after MAX_TOOL_ITERATIONS even if LLM keeps requesting tools."""
        tool_response = FakeLlmResponse(
            content='{"tool_use": {"name": "warden_graph_search", "arguments": {"query": "test"}}}'
        )
        llm_call_fn = AsyncMock(return_value=tool_response)

        with patch(
            "warden.llm.agentic_runner.execute_tool_async",
            new_callable=AsyncMock,
            return_value="Search results: ...",
        ):
            result = await run_agentic_loop_async(
                initial_response=tool_response,
                llm_call_fn=llm_call_fn,
                original_prompt="test",
                system_prompt="test",
                project_root=Path("/tmp/test-project"),
            )

        assert llm_call_fn.call_count == MAX_TOOL_ITERATIONS
        assert result is tool_response

    @pytest.mark.asyncio
    async def test_unknown_tool_generates_error(self):
        """Unknown tool name produces an error message, not an execution."""
        bad_tool_response = FakeLlmResponse(content='{"tool_use": {"name": "fake_tool", "arguments": {}}}')
        final_response = FakeLlmResponse(content='{"findings": []}')
        llm_call_fn = AsyncMock(return_value=final_response)

        result = await run_agentic_loop_async(
            initial_response=bad_tool_response,
            llm_call_fn=llm_call_fn,
            original_prompt="test",
            system_prompt="test",
            project_root=Path("/tmp/test-project"),
        )

        call_args = llm_call_fn.call_args
        prompt_text = call_args.args[0] if call_args.args else ""
        assert "Unknown tool" in prompt_text or "fake_tool" in prompt_text

    @pytest.mark.asyncio
    async def test_missing_required_arg_generates_error(self):
        """Missing required argument produces error message."""
        bad_args_response = FakeLlmResponse(content='{"tool_use": {"name": "warden_query_symbol", "arguments": {}}}')
        final_response = FakeLlmResponse(content='{"findings": []}')
        llm_call_fn = AsyncMock(return_value=final_response)

        result = await run_agentic_loop_async(
            initial_response=bad_args_response,
            llm_call_fn=llm_call_fn,
            original_prompt="test",
            system_prompt="test",
            project_root=Path("/tmp/test-project"),
        )

        call_args = llm_call_fn.call_args
        prompt_text = call_args.args[0] if call_args.args else ""
        assert "Missing required" in prompt_text or "name" in prompt_text

    @pytest.mark.asyncio
    async def test_tool_execution_failure_handled(self):
        """Tool execution error is caught and returned as error text to LLM."""
        tool_response = FakeLlmResponse(
            content='{"tool_use": {"name": "warden_query_symbol", "arguments": {"name": "X"}}}'
        )
        final_response = FakeLlmResponse(content='{"findings": []}')
        llm_call_fn = AsyncMock(return_value=final_response)

        with patch(
            "warden.llm.agentic_runner.execute_tool_async",
            new_callable=AsyncMock,
            return_value="Tool execution failed: RuntimeError: Code graph not available",
        ):
            result = await run_agentic_loop_async(
                initial_response=tool_response,
                llm_call_fn=llm_call_fn,
                original_prompt="test",
                system_prompt="test",
                project_root=Path("/tmp/test-project"),
            )

        assert llm_call_fn.call_count >= 1
        call_args = llm_call_fn.call_args
        prompt_text = call_args.args[0] if call_args.args else ""
        assert "Tool execution failed" in prompt_text

    @pytest.mark.asyncio
    async def test_llm_timeout_in_loop_returns_last(self):
        """If LLM call fails during loop, return the last available response."""
        tool_response = FakeLlmResponse(
            content='{"tool_use": {"name": "warden_query_symbol", "arguments": {"name": "X"}}}'
        )
        llm_call_fn = AsyncMock(side_effect=asyncio.TimeoutError())

        with patch(
            "warden.llm.agentic_runner.execute_tool_async",
            new_callable=AsyncMock,
            return_value="result",
        ):
            result = await run_agentic_loop_async(
                initial_response=tool_response,
                llm_call_fn=llm_call_fn,
                original_prompt="test",
                system_prompt="test",
                project_root=Path("/tmp/test-project"),
            )

        assert result is tool_response


# ============================================================
# Execute Tool Tests
# ============================================================


class TestExecuteTool:
    """Tests for execute_tool_async() standalone function."""

    @pytest.mark.asyncio
    async def test_truncates_long_result(self):
        """Tool results longer than 1000 chars are truncated."""
        long_result = MagicMock()
        long_result.content = "x" * 2000

        with patch("warden.mcp.infrastructure.adapters.audit_adapter.AuditAdapter") as MockAdapter:
            instance = MockAdapter.return_value
            instance._execute_tool_async = AsyncMock(return_value=long_result)

            result = await execute_tool_async("warden_query_symbol", {"name": "Foo"}, Path("/tmp/test"))

        assert len(result) <= 1020  # 1000 + "... [truncated]" suffix
        assert "[truncated]" in result

    @pytest.mark.asyncio
    async def test_handles_adapter_exception(self):
        """Adapter exceptions are caught and returned as error text."""
        with patch("warden.mcp.infrastructure.adapters.audit_adapter.AuditAdapter") as MockAdapter:
            instance = MockAdapter.return_value
            instance._execute_tool_async = AsyncMock(side_effect=FileNotFoundError("code_graph.json not found"))

            result = await execute_tool_async("warden_query_symbol", {"name": "Foo"}, Path("/tmp/test"))

        assert "Tool execution failed" in result
        assert "FileNotFoundError" in result


# ============================================================
# ILlmClient.send_with_tools_async Integration Tests
# ============================================================


class TestSendWithToolsAsync:
    """Tests for ILlmClient.send_with_tools_async() integration."""

    @pytest.mark.asyncio
    async def test_normal_response_passes_through(self):
        """Normal response (no tool_use) passes through unmodified."""
        from warden.llm.types import LlmRequest

        normal_response = FakeLlmResponse(content='{"findings": []}')

        mock_client = MagicMock()
        mock_client.send_async = AsyncMock(return_value=normal_response)
        mock_client.provider = MagicMock()
        mock_client.provider.__str__ = lambda self: "OPENAI"
        mock_client._project_root = None

        # Call the real method via the class
        from warden.llm.providers.base import ILlmClient

        request = LlmRequest(
            user_message="test",
            system_prompt="test",
        )
        result = await ILlmClient.send_with_tools_async(mock_client, request)

        assert result is normal_response
        mock_client.send_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_failed_response_passes_through(self):
        """Failed response passes through without entering loop."""
        from warden.llm.types import LlmRequest

        failed_response = FakeLlmResponse(content="", success=False, error_message="rate limited")

        mock_client = MagicMock()
        mock_client.send_async = AsyncMock(return_value=failed_response)
        mock_client._project_root = None

        from warden.llm.providers.base import ILlmClient

        request = LlmRequest(user_message="test", system_prompt="test")
        result = await ILlmClient.send_with_tools_async(mock_client, request)

        assert result is failed_response

    @pytest.mark.asyncio
    async def test_claude_code_skips_loop(self):
        """Claude Code provider skips the agentic loop even with tool_use response."""
        from warden.llm.types import LlmRequest

        tool_response = FakeLlmResponse(
            content='{"tool_use": {"name": "warden_query_symbol", "arguments": {"name": "X"}}}'
        )

        mock_client = MagicMock()
        mock_client.send_async = AsyncMock(return_value=tool_response)
        mock_client.provider = MagicMock()
        mock_client.provider.__str__ = lambda self: "CLAUDE_CODE"
        mock_client._project_root = None

        from warden.llm.providers.base import ILlmClient

        request = LlmRequest(user_message="test", system_prompt="test")
        result = await ILlmClient.send_with_tools_async(mock_client, request)

        assert result is tool_response
        mock_client.send_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_tool_response_triggers_loop(self):
        """Tool response from non-Claude-Code provider triggers the agentic loop."""
        from warden.llm.types import LlmRequest

        tool_response = FakeLlmResponse(
            content='{"tool_use": {"name": "warden_query_symbol", "arguments": {"name": "X"}}}'
        )
        final_response = FakeLlmResponse(content='{"findings": []}')

        mock_client = MagicMock()
        mock_client.send_async = AsyncMock(side_effect=[tool_response, final_response])
        mock_client.provider = MagicMock()
        mock_client.provider.__str__ = lambda self: "OPENAI"
        mock_client._project_root = Path("/tmp/test-project")

        from warden.llm.providers.base import ILlmClient

        request = LlmRequest(user_message="test", system_prompt="test")

        with patch(
            "warden.llm.agentic_runner.execute_tool_async",
            new_callable=AsyncMock,
            return_value="Symbol X: function at line 10",
        ):
            result = await ILlmClient.send_with_tools_async(mock_client, request)

        assert result is final_response
        # Initial call + 1 loop re-call = 2 total
        assert mock_client.send_async.call_count == 2


# ============================================================
# LLMPhaseBase Delegation Tests (no longer has its own loop)
# ============================================================


class TestLLMPhaseBaseDelegation:
    """Verify LLMPhaseBase no longer has agentic loop methods."""

    def test_no_detect_tool_use_method(self):
        from warden.analysis.application.llm_phase_base import LLMPhaseBase

        assert not hasattr(LLMPhaseBase, "_detect_tool_use")

    def test_no_execute_tool_method(self):
        from warden.analysis.application.llm_phase_base import LLMPhaseBase

        assert not hasattr(LLMPhaseBase, "_execute_tool_async")

    def test_no_agentic_loop_method(self):
        from warden.analysis.application.llm_phase_base import LLMPhaseBase

        assert not hasattr(LLMPhaseBase, "_agentic_loop_async")

    def test_no_validate_tool_arguments_method(self):
        from warden.analysis.application.llm_phase_base import LLMPhaseBase

        assert not hasattr(LLMPhaseBase, "_validate_tool_arguments")

    def test_no_is_claude_code_provider_method(self):
        from warden.analysis.application.llm_phase_base import LLMPhaseBase

        assert not hasattr(LLMPhaseBase, "_is_claude_code_provider")
