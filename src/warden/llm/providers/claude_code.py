"""
Claude Code LLM Client

Integrates with Claude Code CLI for local AI-powered code analysis.
Users can leverage their existing Claude Code subscription instead of
managing separate API keys.

Design Principles:
- KISS: Simple subprocess wrapper, no over-engineering
- Fail-fast: Validate inputs early, clear error messages
- Observable: Structured logging for debugging
"""

import asyncio
import json
import os
import shutil
import time

from warden.shared.infrastructure.logging import get_logger

from ..config import ProviderConfig
from ..registry import ProviderRegistry
from ..types import LlmProvider, LlmRequest, LlmResponse
from .base import ILlmClient

logger = get_logger(__name__)


# =============================================================================
# CONFIGURATION DEFAULTS (can be overridden via config)
# =============================================================================

DEFAULT_TIMEOUT_SECONDS = 120
DEFAULT_MODEL = "claude-code-default"  # Placeholder - actual model set in `claude config`
MAX_PROMPT_LENGTH = 100_000
_TRUNCATION_RETRY_THRESHOLD = 8_000  # Only retry with truncation for prompts > 8K chars


# =============================================================================
# CLAUDE CODE CLIENT
# =============================================================================


class ClaudeCodeClient(ILlmClient):
    """
    Simple Claude Code CLI wrapper.

    Usage:
        client = ClaudeCodeClient(config)
        response = await client.send_async(request)
    """

    def __init__(self, config: ProviderConfig):
        """
        Initialize Claude Code client.

        Args:
            config: Provider configuration

        Note:
            The model field is a placeholder ("claude-code-default").
            Actual model selection (Sonnet 4.5 / Opus 4.1 / Haiku 4.5)
            is controlled via `claude config` command.
        """
        self._default_model = config.default_model or DEFAULT_MODEL
        self._timeout = DEFAULT_TIMEOUT_SECONDS
        self._cli_path = shutil.which("claude") or "claude"

        logger.info(
            "claude_code_client_initialized",
            default_model=self._default_model,
            cli_path=self._cli_path,
            timeout=self._timeout,
        )

    @property
    def provider(self) -> LlmProvider:
        return LlmProvider.CLAUDE_CODE

    async def send_async(self, request: LlmRequest) -> LlmResponse:
        """Send a request to Claude Code CLI."""
        model = request.model or self._default_model

        # Input validation (fail-fast)
        if not request.user_message:
            return self._error_response("Empty user message", model, 0)

        prompt_length = len(request.system_prompt or "") + len(request.user_message)
        if prompt_length > MAX_PROMPT_LENGTH:
            return self._error_response(f"Prompt too large: {prompt_length} > {MAX_PROMPT_LENGTH}", model, 0)

        # Build prompt with explicit no-tool instruction
        # The --disallowedTools flag can be overridden by project config,
        # so we also instruct the model directly to respond with text only.
        no_tool_prefix = (
            "IMPORTANT: Respond with text only. Do NOT use any tools "
            "(no Bash, Read, Write, Edit, Glob, Grep, or any other tool calls). "
            "Provide your analysis as plain text.\n\n"
        )
        full_prompt = request.user_message
        if request.system_prompt:
            full_prompt = f"{request.system_prompt}\n\n{no_tool_prefix}{request.user_message}"
        else:
            full_prompt = f"{no_tool_prefix}{request.user_message}"

        timeout = max(request.timeout_seconds or 0, self._timeout)
        response = await self._execute_cli(full_prompt, model, timeout)

        # Retry once with truncated prompt on empty content (likely context overflow)
        if (
            not response.success
            and "Empty content" in (response.error_message or "")
            and len(full_prompt) > _TRUNCATION_RETRY_THRESHOLD
        ):
            truncated = self._truncate_prompt(full_prompt)
            logger.warning(
                "claude_code_empty_retrying_truncated",
                original_length=len(full_prompt),
                truncated_length=len(truncated),
            )
            response = await self._execute_cli(truncated, model, timeout)

        return response

    @staticmethod
    def _is_nested_session() -> bool:
        """Detect if running inside another Claude Code session."""
        return bool(os.environ.get("CLAUDE_CODE_ENTRYPOINT") or os.environ.get("CLAUDECODE"))

    async def _execute_cli(self, prompt: str, model: str, timeout: int) -> LlmResponse:
        """Execute a single CLI call and return the response."""
        if self._is_nested_session():
            return self._error_response(
                "Nested Claude Code session detected — cannot spawn subprocess. "
                "Use a different provider (ollama/openai) or run outside Claude Code.",
                model,
                0,
            )

        start_time = time.perf_counter()
        try:
            process = await asyncio.create_subprocess_exec(  # warden-ignore
                self._cli_path,
                "--print",
                "--output-format",
                "json",
                "--max-turns",
                "2",
                "--disallowedTools",
                "Bash,Read,Write,Edit,Glob,Grep,WebFetch,WebSearch,NotebookEdit,Task",
                "-p",
                prompt,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)

            duration_ms = self._calc_duration_ms(start_time)

            if process.returncode != 0:
                error_msg = stderr.decode("utf-8", errors="replace").strip()
                # If stderr is empty, check stdout for error hints (CLI may write errors as JSON to stdout)
                if not error_msg:
                    stdout_preview = stdout.decode("utf-8", errors="replace").strip()[:200]
                    error_msg = f"(stderr empty, stdout: {stdout_preview})" if stdout_preview else "(no output)"
                logger.warning(  # warning — pipeline recovers via fallback lane
                    "claude_code_cli_failed",
                    returncode=process.returncode,
                    error=error_msg[:300],
                )
                return self._error_response(
                    f"CLI error (exit {process.returncode}): {error_msg[:300]}", model, duration_ms
                )

            return self._parse_response(stdout, model, duration_ms)

        except asyncio.TimeoutError:
            duration_ms = self._calc_duration_ms(start_time)
            logger.error("claude_code_timeout", timeout=timeout)
            return self._error_response(f"Timeout after {timeout}s", model, duration_ms)

        except Exception as e:
            duration_ms = self._calc_duration_ms(start_time)
            logger.exception("claude_code_error", error=str(e))
            return self._error_response(str(e), model, duration_ms)

    def _parse_response(self, stdout: bytes, model: str, duration_ms: int) -> LlmResponse:
        """Parse CLI JSON response."""
        output = stdout.decode("utf-8", errors="replace").strip()

        if not output:
            return self._error_response("Empty response", model, duration_ms)

        try:
            result = json.loads(output)

            # Check if Claude returned an explicit error object
            is_error = result.get("is_error", False) if isinstance(result, dict) else False
            if is_error or (isinstance(result, dict) and result.get("type") == "error"):
                error_msg = result.get("error") or result.get("message") or "Unknown Claude Code error"
                logger.error("claude_code_explicit_error", error=error_msg, raw_output=output[:500])
                return self._error_response(f"Claude error: {error_msg}", model, duration_ms)

            # Detect max-turns exhaustion (model used tool calls, ran out of turns)
            subtype = result.get("subtype", "") if isinstance(result, dict) else ""
            if subtype == "error_max_turns":
                num_turns = result.get("num_turns", "?")
                logger.error(
                    "claude_code_max_turns_exhausted",
                    num_turns=num_turns,
                    subtype=subtype,
                )
                return self._error_response(
                    f"Max turns exhausted ({num_turns} turns used) - model used tool calls before responding",
                    model,
                    duration_ms,
                )

            content = result.get("result") or result.get("content") or ""

            if not isinstance(content, str):
                content = str(content) if content else ""

            # Empty content after JSON parse = provider returned no useful data
            if not content.strip():
                logger.error(
                    "claude_code_empty_content_json",
                    raw_output=output[:1000],
                    parsed_keys=list(result.keys()) if isinstance(result, dict) else type(result)
                )
                return self._error_response("Empty content in response", model, duration_ms)

            usage = result.get("usage", {})

            logger.info(
                "claude_code_success",
                duration_ms=duration_ms,
                response_length=len(content),
            )

            return LlmResponse(
                content=content,
                success=True,
                provider=self.provider,
                model=model,
                prompt_tokens=usage.get("input_tokens", 0),
                completion_tokens=usage.get("output_tokens", 0),
                total_tokens=usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
                duration_ms=duration_ms,
            )

        except json.JSONDecodeError:
            # Non-JSON response (plain text) - still valid
            return LlmResponse(
                content=output,
                success=True,
                provider=self.provider,
                model=model,
                duration_ms=duration_ms,
            )

    def _error_response(self, message: str, model: str, duration_ms: int) -> LlmResponse:
        """Create error response."""
        return LlmResponse(
            content="",
            success=False,
            error_message=message,
            provider=self.provider,
            model=model,
            duration_ms=duration_ms,
        )

    @staticmethod
    def _truncate_prompt(prompt: str, ratio: float = 0.5) -> str:
        """Truncate prompt preserving start (system prompt) and end (code)."""
        target = int(len(prompt) * ratio)
        head = int(target * 0.7)
        tail = target - head
        return f"{prompt[:head]}\n\n[...truncated for retry...]\n\n{prompt[-tail:]}"

    @staticmethod
    def _calc_duration_ms(start_time: float) -> int:
        """Calculate duration in milliseconds."""
        return int((time.perf_counter() - start_time) * 1000)

    async def is_available_async(self) -> bool:
        """Check if Claude Code CLI is installed and usable."""
        if self._is_nested_session():
            logger.debug("claude_code_unavailable_nested_session")
            return False

        if not shutil.which("claude"):
            return False

        try:
            process = await asyncio.create_subprocess_exec(  # warden-ignore
                self._cli_path,
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(process.communicate(), timeout=5.0)
            return process.returncode == 0
        except Exception:
            return False


# =============================================================================
# PUBLIC API
# =============================================================================


async def detect_claude_code() -> bool:
    """Check if Claude Code CLI is available (used by auto-detection)."""
    try:
        client = ClaudeCodeClient(ProviderConfig(enabled=True))
        return await client.is_available_async()
    except Exception:
        return False


# Self-register with the registry
ProviderRegistry.register(LlmProvider.CLAUDE_CODE, ClaudeCodeClient)
