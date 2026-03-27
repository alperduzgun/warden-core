"""
Qwen Code CLI LLM Client

Integrates with Qwen Code CLI for local AI-powered code analysis.
Same pattern as ClaudeCodeClient — subprocess wrapper.
"""

import asyncio
import json
import shutil
import time

from warden.shared.infrastructure.logging import get_logger

from ..config import ProviderConfig
from ..registry import ProviderRegistry
from ..types import LlmProvider, LlmRequest, LlmResponse
from .base import ILlmClient
from ._cli_subprocess import run_cli_subprocess

logger = get_logger(__name__)

DEFAULT_TIMEOUT_SECONDS = 120
DEFAULT_MODEL = "qwen-code-default"
MAX_PROMPT_LENGTH = 100_000


class QwenCliClient(ILlmClient):
    """Qwen Code CLI wrapper — subprocess-based, same pattern as ClaudeCodeClient."""

    def __init__(self, config: ProviderConfig):
        self._default_model = config.default_model or DEFAULT_MODEL
        self._timeout = DEFAULT_TIMEOUT_SECONDS
        self._cli_path = shutil.which("qwen") or "qwen"

        logger.info(
            "qwen_cli_client_initialized",
            default_model=self._default_model,
            cli_path=self._cli_path,
            timeout=self._timeout,
        )

    @property
    def provider(self) -> LlmProvider:
        return LlmProvider.QWEN_CLI

    async def send_async(self, request: LlmRequest) -> LlmResponse:
        """Send a request to Qwen Code CLI."""
        model = request.model or self._default_model

        if not request.user_message:
            return LlmResponse.error("Empty user message", provider=self.provider, duration_ms=0)

        prompt_length = len(request.system_prompt or "") + len(request.user_message)
        if prompt_length > MAX_PROMPT_LENGTH:
            return LlmResponse.error(
                f"Prompt too large: {prompt_length} > {MAX_PROMPT_LENGTH}",
                provider=self.provider,
                duration_ms=0,
            )

        # Build full prompt — detect JSON mode from prompt content
        _msg_lower = (request.user_message or "").lower()
        _wants_json = "json" in _msg_lower[:200] or "json" in _msg_lower[-400:]
        if _wants_json:
            no_tool_prefix = "IMPORTANT: Do NOT use any tools. Output ONLY valid JSON.\n\n"
        else:
            no_tool_prefix = "IMPORTANT: Do NOT use any tools.\n\n"
        if request.system_prompt:
            full_prompt = f"{request.system_prompt}\n\n{no_tool_prefix}{request.user_message}"
        else:
            full_prompt = f"{no_tool_prefix}{request.user_message}"

        timeout = max(request.timeout_seconds or 0, self._timeout)
        return await self._execute_cli(full_prompt, model, timeout)

    async def _execute_cli(self, prompt: str, model: str, timeout: int) -> LlmResponse:
        """Execute Qwen CLI subprocess."""
        start_time = time.perf_counter()
        try:
            stdout_text, stderr_text, returncode = await run_cli_subprocess(
                [self._cli_path, "--output-format", "json", "--auth-type", "qwen-oauth", "-p", prompt],
                timeout=float(timeout),
            )
            duration_ms = int((time.perf_counter() - start_time) * 1000)

            if returncode != 0:
                error_msg = stderr_text.strip()[:300]
                logger.warning("qwen_cli_failed", returncode=returncode, error=error_msg)
                return LlmResponse.error(
                    f"CLI error (exit {returncode}): {error_msg}",
                    provider=self.provider,
                    duration_ms=duration_ms,
                )

            return self._parse_response(stdout_text.encode("utf-8"), model, duration_ms)

        except (asyncio.TimeoutError, TimeoutError):
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            return LlmResponse.error(f"Timeout after {timeout}s", provider=self.provider, duration_ms=duration_ms)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            return LlmResponse.error(str(e), provider=self.provider, duration_ms=duration_ms)

    def _parse_response(self, stdout: bytes, model: str, duration_ms: int) -> LlmResponse:
        """Parse Qwen CLI JSON output.

        Qwen CLI outputs a JSON array: [{type: "system"}, {type: "assistant", message: {...}}, {type: "result", result: "..."}]
        """
        raw = stdout.decode("utf-8", errors="replace").strip()
        if not raw:
            return LlmResponse.error("Empty output from Qwen CLI", provider=self.provider, duration_ms=duration_ms)

        try:
            data = json.loads(raw)

            # Qwen CLI outputs a JSON array of events
            if isinstance(data, list):
                content = ""
                usage = {}
                for event in data:
                    event_type = event.get("type", "")
                    if event_type == "result":
                        content = event.get("result", "")
                        usage = event.get("usage", {})
                    elif event_type == "assistant" and not content:
                        msg = event.get("message", {})
                        for block in msg.get("content", []):
                            if block.get("type") == "text":
                                content = block.get("text", "")

                if not content:
                    return LlmResponse.error("No text content in Qwen response", provider=self.provider, duration_ms=duration_ms)

                return LlmResponse(
                    content=content,
                    success=True,
                    provider=self.provider,
                    model=model,
                    prompt_tokens=usage.get("input_tokens"),
                    completion_tokens=usage.get("output_tokens"),
                    total_tokens=usage.get("total_tokens"),
                    duration_ms=duration_ms,
                )

            # Single object fallback
            content = data.get("result", data.get("content", ""))
            return LlmResponse(
                content=content or raw,
                success=True,
                provider=self.provider,
                model=model,
                duration_ms=duration_ms,
            )

        except json.JSONDecodeError:
            return LlmResponse(
                content=raw,
                success=True,
                provider=self.provider,
                model=model,
                duration_ms=duration_ms,
            )

    async def is_available_async(self) -> bool:
        """Check if Qwen CLI is available."""
        return bool(shutil.which("qwen"))


# Self-register
ProviderRegistry.register(LlmProvider.QWEN_CLI, QwenCliClient)
