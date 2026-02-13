"""
Command Executor Service.

Provides a secure and robust way to execute system commands asynchronously.
Handles timeouts, output capturing, and logging.
"""

import asyncio
import contextlib
import os
import signal
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)


@dataclass
class CommandResult:
    """Result of a command execution."""
    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration: float
    is_timeout: bool = False

    @property
    def is_success(self) -> bool:
        """Check if command succeeded."""
        return self.exit_code == 0 and not self.is_timeout


class CommandExecutor:
    """
    Secure command executor wrapper.
    """

    def __init__(self, default_timeout: float = 300.0):
        self.default_timeout = default_timeout

    async def run_async(
        self,
        command: str | list[str],
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
        timeout: float | None = None,
        shell: bool = False
    ) -> CommandResult:
        """
        Execute a command asynchronously.

        Args:
            command: Command string or list of arguments
            cwd: Working directory
            env: Environment variables (merges with os.environ)
            timeout: Execution timeout in seconds
            shell: Run in shell (Use with caution!)

        Returns:
            CommandResult object
        """
        import time
        start_time = time.perf_counter()
        timeout_val = timeout if timeout is not None else self.default_timeout

        # Prepare command
        if isinstance(command, str) and not shell:
            # Split string if not using shell
            import shlex
            cmd_args = shlex.split(command)
        else:
            cmd_args = command

        # Prepare environment
        run_env = os.environ.copy()
        if env:
            run_env.update(env)

        # Log execution
        cmd_str = command if isinstance(command, str) else " ".join(command)
        cwd_str = str(cwd) if cwd else "cwd"
        logger.debug("executing_command", command=cmd_str, cwd=cwd_str, timeout=timeout_val)

        process = None
        try:
            if shell:
                process = await asyncio.create_subprocess_shell(
                    cmd_str,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd,
                    env=run_env,
                    preexec_fn=os.setsid  # Create process group for easier cleanup
                )
            else:
                process = await asyncio.create_subprocess_exec(
                    *cmd_args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd,
                    env=run_env,
                    preexec_fn=os.setsid
                )

            try:
                stdout_data, stderr_data = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout_val
                )
            except asyncio.TimeoutError:
                logger.warning("command_timeout", command=cmd_str, timeout=timeout_val)

                # Kill process group to ensure children die too
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(os.getpgid(process.pid), signal.SIGTERM)

                return CommandResult(
                    command=cmd_str,
                    exit_code=-1,
                    stdout="",
                    stderr="Command timed out",
                    duration=time.perf_counter() - start_time,
                    is_timeout=True
                )

            duration = time.perf_counter() - start_time
            exit_code = process.returncode
            stdout_str = stdout_data.decode('utf-8', errors='replace')
            stderr_str = stderr_data.decode('utf-8', errors='replace')

            if exit_code != 0:
                logger.warning(
                    "command_failed",
                    command=cmd_str,
                    exit_code=exit_code,
                    stderr_snippet=stderr_str[:200]
                )
            else:
                logger.debug("command_success", command=cmd_str, duration=duration)

            return CommandResult(
                command=cmd_str,
                exit_code=exit_code,
                stdout=stdout_str,
                stderr=stderr_str,
                duration=duration
            )

        except Exception as e:
            logger.error("command_execution_error", command=cmd_str, error=str(e))
            return CommandResult(
                command=cmd_str,
                exit_code=-2,
                stdout="",
                stderr=f"Execution error: {e!s}",
                duration=time.perf_counter() - start_time
            )
