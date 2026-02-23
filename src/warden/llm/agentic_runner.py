"""Shared Agentic Loop Runner — text-based tool calling.

Extracted from LLMPhaseBase so ALL LLM consumers (frames, phases, etc.)
get transparent tool-calling support via ILlmClient.send_with_tools_async().
"""

import json
from pathlib import Path
from typing import Any, Awaitable, Callable

from warden.llm.prompts.tool_instructions import (
    AVAILABLE_TOOLS,
    KNOWN_TOOL_NAMES,
    MAX_TOOL_ITERATIONS,
)
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)


def detect_tool_use(content: str) -> dict[str, Any] | None:
    """Detect a tool_use JSON block in LLM response content.

    Returns parsed tool call dict ``{"name": ..., "arguments": {...}}``
    or ``None`` if the response is a normal (non-tool) answer.

    Tolerates malformed JSON via ``parse_json_from_llm`` repair logic.
    """
    if not content or "tool_use" not in content:
        return None

    from warden.shared.utils.json_parser import parse_json_from_llm

    try:
        data = parse_json_from_llm(content)
        if isinstance(data, dict) and "tool_use" in data:
            tool_call = data["tool_use"]
            if isinstance(tool_call, dict) and "name" in tool_call:
                return tool_call
    except Exception:
        pass
    return None


def validate_tool_arguments(tool_name: str, arguments: dict[str, Any]) -> list[str]:
    """Validate required arguments for a tool call.

    Returns list of missing required argument names (empty = valid).
    """
    for tool_def in AVAILABLE_TOOLS:
        if tool_def["name"] == tool_name:
            required = tool_def.get("required", [])
            return [r for r in required if r not in arguments]
    return []


def is_claude_code_provider(llm_client: Any) -> bool:
    """Check if provider is Claude Code (agentic loop disabled for it)."""
    if llm_client is None:
        return False
    provider = getattr(llm_client, "provider", None)
    if provider is None:
        return False
    provider_str = str(provider).upper()
    return "CLAUDE_CODE" in provider_str or "CLAUDE-CODE" in provider_str


async def execute_tool_async(
    tool_name: str,
    arguments: dict[str, Any],
    project_root: Path,
) -> str:
    """Execute a tool via AuditAdapter and return truncated result.

    Args:
        tool_name: One of KNOWN_TOOL_NAMES.
        arguments: Tool arguments from LLM.
        project_root: Root directory of the project being analyzed.

    Returns:
        Truncated string result (max ~250 tokens / 1000 chars).
    """
    from warden.mcp.infrastructure.adapters.audit_adapter import AuditAdapter

    adapter = AuditAdapter(project_root=project_root)

    try:
        result = await adapter._execute_tool_async(tool_name, arguments)
        text = ""
        if hasattr(result, "content"):
            text = str(result.content)
        elif isinstance(result, dict):
            text = json.dumps(result, default=str)
        else:
            text = str(result)

        max_chars = 1000
        if len(text) > max_chars:
            text = text[:max_chars] + "\n... [truncated]"
        return text

    except Exception as e:
        logger.warning(
            "agent_tool_execution_failed",
            tool=tool_name,
            error=str(e),
        )
        return f"Tool execution failed: {type(e).__name__}: {e}"


async def run_agentic_loop_async(
    initial_response: Any,
    llm_call_fn: Callable[[str, str], Awaitable[Any]],
    original_prompt: str,
    system_prompt: str,
    project_root: Path | None = None,
    caller_name: str = "unknown",
) -> Any:
    """Core agentic loop with MAX_TOOL_ITERATIONS circuit breaker.

    If the LLM returns a ``tool_use`` JSON, execute the tool via
    AuditAdapter, append the result to the conversation, and re-call
    the LLM. Maximum ``MAX_TOOL_ITERATIONS`` rounds.

    Args:
        initial_response: First LLM response that contained a tool call.
        llm_call_fn: Async callable (augmented_prompt, system_prompt) -> LlmResponse.
        original_prompt: Original user prompt.
        system_prompt: Original system prompt.
        project_root: Project root for tool execution context.
        caller_name: Caller identifier for logging.

    Returns:
        Final LLM response (with tool results incorporated).
    """
    effective_root = project_root or Path.cwd()
    current_response = initial_response
    conversation_suffix = ""

    for iteration in range(MAX_TOOL_ITERATIONS):
        content = current_response.content if current_response else ""
        tool_call = detect_tool_use(content)

        if tool_call is None:
            return current_response

        tool_name = tool_call.get("name", "")
        arguments = tool_call.get("arguments", {})

        if tool_name not in KNOWN_TOOL_NAMES:
            tool_result = f"Unknown tool '{tool_name}'. Available: {', '.join(sorted(KNOWN_TOOL_NAMES))}"
        else:
            missing = validate_tool_arguments(tool_name, arguments)
            if missing:
                tool_result = f"Missing required argument(s): {', '.join(missing)}"
            else:
                logger.info(
                    "agent_tool_called",
                    tool=tool_name,
                    arguments=arguments,
                    attempt=iteration + 1,
                    max_attempts=MAX_TOOL_ITERATIONS,
                    caller=caller_name,
                )
                tool_result = await execute_tool_async(tool_name, arguments, effective_root)

        conversation_suffix += (
            f"\n\n[TOOL RESULT for {tool_name}]:\n{tool_result}\n\n"
            "Now continue your analysis using the tool result above. "
        )

        remaining = MAX_TOOL_ITERATIONS - iteration - 1
        if remaining > 0:
            conversation_suffix += (
                f"You have {remaining} tool call(s) remaining. "
                "Return your final analysis JSON, or request another tool."
            )
        else:
            conversation_suffix += "This was your last tool call. You MUST now return your final analysis JSON."

        augmented_prompt = original_prompt + conversation_suffix

        try:
            current_response = await llm_call_fn(augmented_prompt, system_prompt)
        except Exception as e:
            logger.warning(
                "agent_loop_llm_call_failed",
                attempt=iteration + 1,
                error=str(e),
                caller=caller_name,
            )
            return current_response

    logger.info(
        "agent_loop_max_iterations",
        iterations=MAX_TOOL_ITERATIONS,
        caller=caller_name,
    )
    return current_response
