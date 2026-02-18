"""
Codex LLM Client (Local CLI)

Wraps the `codex exec` subcommand for non-interactive, read-only analysis.
Mirrors the ClaudeCodeClient pattern: subprocess → parse response → LlmResponse.

Design:
- `--sandbox read-only` prevents any file modification during scan
- `--output-last-message` captures the final agent response cleanly
- Falls back to stdout when output file is unavailable
"""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import time
from pathlib import Path

import structlog

from ..registry import ProviderRegistry
from ..types import LlmProvider, LlmRequest, LlmResponse
from .base import ILlmClient

logger = structlog.get_logger(__name__)

DEFAULT_TIMEOUT_SECONDS = 120
MAX_PROMPT_LENGTH = 100_000


class CodexClient(ILlmClient):
    def __init__(self, endpoint: str | None = None, default_model: str | None = None) -> None:
        self._endpoint = endpoint or "cli"
        # "codex-local" is a placeholder; omit -m flag so codex uses its own config
        self._default_model = default_model or "codex-local"
        self._timeout = DEFAULT_TIMEOUT_SECONDS
        self._cli_path = shutil.which("codex") or "codex"

    @property
    def provider(self) -> LlmProvider:
        return LlmProvider.CODEX

    async def is_available_async(self) -> bool:
        try:
            return shutil.which("codex") is not None
        except Exception:
            return False

    async def send_async(self, request: LlmRequest) -> LlmResponse:
        start_time = time.perf_counter()
        model = request.model or self._default_model

        if not await self.is_available_async():
            return self._error_response("Codex CLI not found on PATH.", model, 0)

        full_prompt = request.user_message or ""
        if request.system_prompt:
            full_prompt = f"{request.system_prompt}\n\n{full_prompt}"

        if not full_prompt:
            return self._error_response("Empty prompt", model, 0)

        if len(full_prompt) > MAX_PROMPT_LENGTH:
            return self._error_response(
                f"Prompt too large: {len(full_prompt)} > {MAX_PROMPT_LENGTH}", model, 0
            )

        # Write response to a temp file to capture cleanly
        fd, output_file = tempfile.mkstemp(suffix=".txt", prefix="warden_codex_")
        os.close(fd)

        try:
            cmd = [
                self._cli_path,
                "exec",
                "--sandbox", "read-only",
                "--color", "never",
                "--skip-git-repo-check",
                "--output-last-message", output_file,
            ]
            # Only pass -m when user has configured a real model (not the placeholder)
            if model and model != "codex-local":
                cmd.extend(["-m", model])
            # "--" terminates option parsing so a prompt starting with "--" is safe
            cmd.extend(["--", full_prompt])

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            timeout = request.timeout_seconds or self._timeout
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=float(timeout))
            except asyncio.TimeoutError:
                proc.kill()
                duration_ms = self._calc_duration_ms(start_time)
                logger.error("codex_timeout", timeout=timeout)
                return self._error_response(f"Timeout after {timeout}s", model, duration_ms)

            duration_ms = self._calc_duration_ms(start_time)

            if proc.returncode != 0:
                error = stderr.decode("utf-8", errors="replace").strip()
                logger.error("codex_exec_failed", returncode=proc.returncode, error=error[:200])
                return self._error_response(
                    f"codex exec failed (exit {proc.returncode}): {error[:200]}", model, duration_ms
                )

            # Prefer the dedicated output file; fall back to stdout
            content = ""
            try:
                content = Path(output_file).read_text(encoding="utf-8").strip()
            except Exception:
                pass
            if not content:
                content = stdout.decode("utf-8", errors="replace").strip()

            if not content:
                return self._error_response("Empty response from codex", model, duration_ms)

            logger.info("codex_success", duration_ms=duration_ms, response_length=len(content))
            return LlmResponse(
                content=content,
                success=True,
                provider=self.provider,
                model=model,
                duration_ms=duration_ms,
            )

        except Exception as e:
            duration_ms = self._calc_duration_ms(start_time)
            logger.warning("codex_error", error=str(e))
            return self._error_response(str(e), model, duration_ms)
        finally:
            try:
                os.unlink(output_file)
            except Exception:
                pass

    def _error_response(self, message: str, model: str, duration_ms: int = 0) -> LlmResponse:
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
        return int((time.perf_counter() - start_time) * 1000)


def _factory(config) -> ILlmClient:
    return CodexClient(endpoint=config.endpoint, default_model=config.default_model)


# Self-register
ProviderRegistry.register(LlmProvider.CODEX, _factory)
