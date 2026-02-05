"""
Claude Code LLM Client

Integrates with Claude Code CLI/SDK for local AI-powered code analysis.
This allows users to leverage their existing Claude Code subscription
instead of managing separate API keys.

Supports three modes:
1. Claude Agent SDK (preferred) - Programmatic access
2. Claude Code CLI - subprocess execution
3. claude-code-mcp - MCP server integration
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


class ClaudeCodeClient(ILlmClient):
    """
    Claude Code client for local LLM execution via Claude Code CLI/SDK.

    This provider wraps the user's local Claude Code installation,
    allowing Warden to use Claude's capabilities without requiring
    a separate API key.

    Prerequisites:
    - Claude Code CLI installed (`claude` command available)
    - User authenticated with Claude Code

    Modes:
    - sdk: Use Claude Agent SDK (requires claude-agent-sdk package)
    - cli: Use Claude Code CLI via subprocess
    - mcp: Use claude-code-mcp server
    """

    def __init__(self, config: ProviderConfig):
        self._mode = config.endpoint or "cli"  # cli, sdk, or mcp
        self._default_model = config.default_model or "claude-sonnet-4-20250514"
        self._cli_path = shutil.which("claude") or "claude"
        self._timeout = 120  # Claude Code can be slow for complex tasks

        logger.debug(
            "claude_code_client_initialized",
            mode=self._mode,
            default_model=self._default_model,
            cli_path=self._cli_path
        )

    @property
    def provider(self) -> LlmProvider:
        return LlmProvider.CLAUDE_CODE

    async def send_async(self, request: LlmRequest) -> LlmResponse:
        """
        Send a request to Claude Code.

        Routes to appropriate implementation based on configured mode.
        """
        if self._mode == "sdk":
            return await self._send_via_sdk(request)
        elif self._mode == "mcp":
            return await self._send_via_mcp(request)
        else:
            return await self._send_via_cli(request)

    async def _send_via_cli(self, request: LlmRequest) -> LlmResponse:
        """
        Execute request via Claude Code CLI.

        Uses `claude --print` for non-interactive execution.
        """
        start_time = time.time()
        model = request.model or self._default_model

        try:
            # Build the prompt combining system and user messages
            full_prompt = f"{request.system_prompt}\n\n{request.user_message}"

            # Use claude CLI with --print flag for non-interactive mode
            # --output-format json gives structured output
            process = await asyncio.create_subprocess_exec(
                self._cli_path,
                "--print",
                "--output-format", "json",
                "--max-turns", "1",  # Single turn for simple requests
                "-p", full_prompt,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=request.timeout_seconds or self._timeout
            )

            duration_ms = int((time.time() - start_time) * 1000)

            if process.returncode != 0:
                error_msg = stderr.decode().strip() if stderr else "Unknown error"
                logger.error(
                    "claude_code_cli_failed",
                    returncode=process.returncode,
                    error=error_msg,
                    duration_ms=duration_ms
                )
                return LlmResponse(
                    content="",
                    success=False,
                    error_message=f"Claude Code CLI error: {error_msg}",
                    provider=self.provider,
                    duration_ms=duration_ms
                )

            # Parse JSON output
            output = stdout.decode().strip()

            try:
                result = json.loads(output)
                # Claude Code JSON output has 'result' field with the response
                content = result.get("result", output)

                # Extract token usage if available
                usage = result.get("usage", {})
                prompt_tokens = usage.get("input_tokens", 0)
                completion_tokens = usage.get("output_tokens", 0)
            except json.JSONDecodeError:
                # If not JSON, use raw output
                content = output
                prompt_tokens = 0
                completion_tokens = 0

            return LlmResponse(
                content=content,
                success=True,
                provider=self.provider,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                duration_ms=duration_ms
            )

        except asyncio.TimeoutError:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(
                "claude_code_cli_timeout",
                timeout=request.timeout_seconds,
                duration_ms=duration_ms
            )
            return LlmResponse(
                content="",
                success=False,
                error_message=f"Claude Code CLI timeout after {request.timeout_seconds}s",
                provider=self.provider,
                duration_ms=duration_ms
            )

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(
                "claude_code_cli_error",
                error=str(e),
                duration_ms=duration_ms
            )
            return LlmResponse(
                content="",
                success=False,
                error_message=str(e),
                provider=self.provider,
                duration_ms=duration_ms
            )

    async def _send_via_sdk(self, request: LlmRequest) -> LlmResponse:
        """
        Execute request via Claude Agent SDK.

        This is the preferred method when claude-agent-sdk is installed.
        """
        start_time = time.time()
        model = request.model or self._default_model

        try:
            # Try to import Claude Agent SDK
            from claude_code_sdk import query, ClaudeCodeOptions

            full_prompt = f"{request.system_prompt}\n\n{request.user_message}"

            # Collect response from async generator
            response_text = ""
            async for message in query(
                prompt=full_prompt,
                options=ClaudeCodeOptions(
                    max_turns=1,
                    model=model,
                )
            ):
                if hasattr(message, "content"):
                    response_text += str(message.content)

            duration_ms = int((time.time() - start_time) * 1000)

            return LlmResponse(
                content=response_text,
                success=True,
                provider=self.provider,
                model=model,
                prompt_tokens=0,  # SDK doesn't expose token counts easily
                completion_tokens=0,
                total_tokens=0,
                duration_ms=duration_ms
            )

        except ImportError:
            logger.warning("claude_agent_sdk_not_installed")
            # Fallback to CLI
            return await self._send_via_cli(request)

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(
                "claude_code_sdk_error",
                error=str(e),
                duration_ms=duration_ms
            )
            return LlmResponse(
                content="",
                success=False,
                error_message=str(e),
                provider=self.provider,
                duration_ms=duration_ms
            )

    async def _send_via_mcp(self, request: LlmRequest) -> LlmResponse:
        """
        Execute request via claude-code-mcp server.

        This allows using Claude Code as an MCP tool from other agents.
        """
        # For MCP mode, we'd need to connect to the MCP server
        # This is more complex and would require MCP client implementation
        # For now, fallback to CLI
        logger.debug("claude_code_mcp_mode_fallback_to_cli")
        return await self._send_via_cli(request)

    async def is_available_async(self) -> bool:
        """
        Check if Claude Code CLI is installed and authenticated.
        """
        try:
            # Check if claude command exists
            if not shutil.which("claude"):
                logger.debug("claude_code_cli_not_found")
                return False

            # Check if claude is authenticated by running a simple command
            process = await asyncio.create_subprocess_exec(
                self._cli_path,
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, _ = await asyncio.wait_for(
                process.communicate(),
                timeout=5.0
            )

            if process.returncode == 0:
                version = stdout.decode().strip()
                logger.debug("claude_code_available", version=version)
                return True

            return False

        except (asyncio.TimeoutError, Exception) as e:
            logger.debug("claude_code_availability_check_failed", error=str(e))
            return False


async def detect_claude_code() -> bool:
    """
    Utility function to detect if Claude Code is available.
    Used by config auto-detection.
    """
    client = ClaudeCodeClient(ProviderConfig(enabled=True))
    return await client.is_available_async()
