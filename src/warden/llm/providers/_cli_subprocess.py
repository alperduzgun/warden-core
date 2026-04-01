"""Shared subprocess execution utility for CLI-based LLM providers.

Guarantees process cleanup on timeout, cancellation, or exception.
Usable by claude_code, qwen_cli, codex, and any future CLI tool provider.
"""

from __future__ import annotations

import asyncio
import errno
import os
from typing import Sequence

import structlog

logger = structlog.get_logger(__name__)

# Maximum retries when the OS refuses to spawn a process (EAGAIN / resource
# temporarily unavailable — common inside Docker containers with tight PID or
# file-descriptor limits).  Delays follow exponential backoff: 0.5 s, 1.0 s.
_EAGAIN_MAX_RETRIES: int = 3
_EAGAIN_BASE_DELAY: float = 0.5


def _is_eagain(exc: BaseException) -> bool:
    """Return True if *exc* represents a resource-exhaustion spawn failure."""
    if isinstance(exc, BlockingIOError):
        return True
    if isinstance(exc, OSError) and exc.errno == errno.EAGAIN:
        return True
    return False


async def run_cli_subprocess(
    args: Sequence[str],
    stdin_input: str | None = None,
    timeout: float = 120.0,
    env: dict[str, str] | None = None,
) -> tuple[str, str, int]:
    """Run a CLI subprocess and return (stdout, stderr, returncode).

    Guarantees the child process is killed and reaped on timeout,
    asyncio cancellation, or any other exception. No zombie processes.

    Args:
        args: Command and arguments, e.g. ["claude", "--version"].
        stdin_input: Optional string to pass on stdin. When None, stdin
            is closed immediately (DEVNULL).
        timeout: Maximum wall-clock seconds to wait for the process.
            Raises asyncio.TimeoutError on expiry after killing the child.
        env: Optional environment mapping. When None the current process
            environment is inherited.

    Returns:
        Tuple of (stdout_text, stderr_text, returncode).

    Raises:
        asyncio.TimeoutError: Process did not finish within *timeout* seconds.
            The child is guaranteed to have been killed before this propagates.
        asyncio.CancelledError: Caller's task was cancelled.
            The child is guaranteed to have been killed before this propagates.
    """
    merged_env: dict[str, str] | None = None
    if env is not None:
        merged_env = {**os.environ, **env}

    stdin_mode = asyncio.subprocess.PIPE if stdin_input is not None else asyncio.subprocess.DEVNULL

    # Retry process creation on EAGAIN (resource temporarily unavailable).
    # This is common in Docker/CI environments with tight PID or fd limits.
    # Only EAGAIN / BlockingIOError triggers a retry — all other errors propagate.
    process: asyncio.subprocess.Process | None = None
    for _attempt in range(_EAGAIN_MAX_RETRIES):
        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                stdin=stdin_mode,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=merged_env,
            )
            break
        except BaseException as exc:
            if _is_eagain(exc) and _attempt < _EAGAIN_MAX_RETRIES - 1:
                delay = _EAGAIN_BASE_DELAY * (2 ** _attempt)
                logger.warning(
                    "cli_subprocess_spawn_eagain_retry",
                    cmd=args[0] if args else "unknown",
                    attempt=_attempt + 1,
                    delay=delay,
                )
                await asyncio.sleep(delay)
            else:
                raise

    assert process is not None  # loop always breaks or raises

    stdin_bytes = stdin_input.encode("utf-8") if stdin_input is not None else None

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            process.communicate(input=stdin_bytes),
            timeout=timeout,
        )
        return (
            stdout_bytes.decode("utf-8", errors="replace"),
            stderr_bytes.decode("utf-8", errors="replace"),
            process.returncode if process.returncode is not None else -1,
        )

    except asyncio.TimeoutError:
        logger.error(
            "cli_subprocess_timeout",
            cmd=args[0] if args else "unknown",
            timeout=timeout,
            pid=process.pid,
        )
        await _kill_and_reap(process)
        raise

    except asyncio.CancelledError:
        logger.warning(
            "cli_subprocess_cancelled",
            cmd=args[0] if args else "unknown",
            pid=process.pid,
        )
        await _kill_and_reap(process)
        raise

    except Exception:
        logger.exception(
            "cli_subprocess_error",
            cmd=args[0] if args else "unknown",
            pid=process.pid,
        )
        await _kill_and_reap(process)
        raise


async def _kill_and_reap(process: asyncio.subprocess.Process) -> None:
    """Kill a subprocess and wait for it to exit, preventing zombies.

    Tries SIGTERM first (graceful), then SIGKILL after 2 seconds if the
    process is still alive. Errors during cleanup are swallowed so that
    the *original* exception always propagates to the caller.
    """
    pid = process.pid

    # Step 1: Attempt graceful termination first.
    try:
        process.terminate()
    except (ProcessLookupError, OSError):
        # Already exited — nothing left to do.
        logger.debug("cli_subprocess_already_exited_on_terminate", pid=pid)
        return

    # Step 2: Give it 2 s to exit gracefully, then force-kill.
    try:
        await asyncio.wait_for(process.wait(), timeout=2.0)
        logger.debug("cli_subprocess_terminated_gracefully", pid=pid)
        return
    except asyncio.TimeoutError:
        pass  # Still running — escalate to SIGKILL.

    try:
        process.kill()
        logger.warning("cli_subprocess_killed", pid=pid)
    except (ProcessLookupError, OSError):
        logger.debug("cli_subprocess_already_exited_on_kill", pid=pid)
        return

    # Step 3: Wait for the OS to reap the process entry (prevents zombie).
    try:
        await asyncio.wait_for(process.wait(), timeout=2.0)
        logger.debug("cli_subprocess_reaped", pid=pid)
    except asyncio.TimeoutError:
        logger.error("cli_subprocess_reap_timeout", pid=pid)
    except Exception:
        pass  # Best-effort — never mask the original exception.
