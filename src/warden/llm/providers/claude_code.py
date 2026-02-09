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
import shutil
import time
from typing import Optional

from ..config import ProviderConfig
from ..types import LlmProvider, LlmRequest, LlmResponse
from .base import ILlmClient
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# CONFIGURATION DEFAULTS (can be overridden via config)
# =============================================================================

DEFAULT_TIMEOUT_SECONDS = 120
DEFAULT_MODEL = "claude-code-default"  # Placeholder - actual model set in `claude config`
MAX_PROMPT_LENGTH = 100_000


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
        start_time = time.perf_counter()
        model = request.model or self._default_model

        # Input validation (fail-fast)
        if not request.user_message:
            return self._error_response("Empty user message", model, 0)

        prompt_length = len(request.system_prompt or "") + len(request.user_message)
        if prompt_length > MAX_PROMPT_LENGTH:
            return self._error_response(
                f"Prompt too large: {prompt_length} > {MAX_PROMPT_LENGTH}",
                model, 0
            )

        # Build prompt
        full_prompt = request.user_message
        if request.system_prompt:
            full_prompt = f"{request.system_prompt}\n\n{request.user_message}"

        # Execute CLI
        try:
            process = await asyncio.create_subprocess_exec(  # warden: ignore
                self._cli_path,
                "--print",
                "--output-format", "json",
                "--max-turns", "1",
                "-p", full_prompt,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            timeout = request.timeout_seconds or self._timeout
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout
            )

            duration_ms = self._calc_duration_ms(start_time)

            if process.returncode != 0:
                error_msg = stderr.decode("utf-8", errors="replace").strip()
                logger.error(
                    "claude_code_cli_failed",
                    returncode=process.returncode,
                    error=error_msg[:200],
                )
                return self._error_response(
                    f"CLI error (exit {process.returncode}): {error_msg[:200]}",
                    model, duration_ms
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
            content = result.get("result") or result.get("content") or ""

            if not isinstance(content, str):
                content = str(content) if content else ""

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
    def _calc_duration_ms(start_time: float) -> int:
        """Calculate duration in milliseconds."""
        return int((time.perf_counter() - start_time) * 1000)

    async def is_available_async(self) -> bool:
        """Check if Claude Code CLI is installed."""
        if not shutil.which("claude"):
            return False

        try:
            process = await asyncio.create_subprocess_exec(  # warden: ignore
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
