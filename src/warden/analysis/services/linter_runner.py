"""
Linter Runner Engine.

A shared utility for executing external linter tools safely.
Handles subprocess management, timeouts, and output parsing.
Designed to be used by specific Language Linter Frames (Hub Items).
"""

import asyncio
import contextlib
import json
import subprocess
import time
from pathlib import Path
from typing import Any

from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)


class LinterRunner:
    """
    Generic execution engine for CLI-based linters.

    Responsibilities:
    - Safe subprocess execution (asyncio)
    - Timeout management
    - Zombie process prevention
    - Output capture and JSON parsing
    - Error handling (does NOT map to Findings, just returns raw data)
    """

    def __init__(self, timeout_seconds: float = 30.0, max_output_size: int = 10 * 1024 * 1024):
        self.timeout = timeout_seconds
        self.max_output_size = max_output_size  # 10MB default

    async def execute_json_command_async(
        self, command: list[str], cwd: Path | None = None, env: dict[str, str] | None = None
    ) -> tuple[bool, Any, str | None]:
        """
        Execute a command and parse its output as JSON.

        Args:
            command: Command list (e.g. ['ruff', 'check', ...])
            cwd: Working directory
            env: Environment variables

        Returns:
            Tuple(success, parsed_data_or_none, error_message)
        """
        tool_name = Path(command[0]).name
        start_time = time.perf_counter()

        try:
            process = await asyncio.create_subprocess_exec(  # warden-ignore
                *command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd, env=env, limit=self.max_output_size
            )

            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self.timeout)
            except asyncio.TimeoutError:
                self._kill_process(process)
                logger.error("linter_timeout", tool=tool_name, timeout=self.timeout)
                return False, None, f"Timeout exceeded ({self.timeout}s)"

            time.perf_counter() - start_time

            # Check exit code
            # Note: Many linters return non-zero on findings.
            # We rely on stdout presence for success usually, but let's check basic execution failures.
            stderr_decoded = stderr.decode().strip()

            # Logic: If we got valid JSON on stdout, we consider it a 'successful run' even if exit code is 1 (findings found)
            stdout_decoded = stdout.decode().strip()

            if not stdout_decoded:
                if process.returncode != 0:
                    logger.warning("linter_exec_failed_no_output", tool=tool_name, error=stderr_decoded)
                    return False, None, stderr_decoded or "Execution failed with no output"
                return True, [], None  # Empty success

            try:
                data = json.loads(stdout_decoded)
                return True, data, None
            except json.JSONDecodeError as e:
                logger.error(
                    "linter_output_invalid_json", tool=tool_name, error=str(e), partial_output=stdout_decoded[:100]
                )
                return False, None, f"Invalid JSON output: {e!s}"

        except Exception as e:
            logger.error("linter_runner_execution_error", tool=tool_name, error=str(e))
            return False, None, str(e)

    def _kill_process(self, process: asyncio.subprocess.Process) -> None:
        """Safely kill a process."""
        with contextlib.suppress(ProcessLookupError):
            process.kill()

    # Alias for backwards compatibility
    execute_json_command = execute_json_command_async
