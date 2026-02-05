"""
Claude Code LLM Client

Integrates with Claude Code CLI/SDK for local AI-powered code analysis.
This allows users to leverage their existing Claude Code subscription
instead of managing separate API keys.

Supports two modes:
1. CLI - Claude Code CLI via subprocess (default, most compatible)
2. SDK - Claude Agent SDK (requires claude-code-sdk package)

Chaos Engineering Considerations:
- Fail-fast on invalid configuration
- Process cleanup on timeout (prevent zombie processes)
- Structured logging for all failure modes
- Input sanitization (no shell injection)
- Graceful degradation (SDK -> CLI fallback)
- Circuit breaker for repeated failures
- Concurrency limiting (prevent resource exhaustion)
- Health check caching (reduce overhead)
"""

import asyncio
import atexit
import json
import shutil
import time
import uuid
import weakref
from dataclasses import dataclass, field
from enum import Enum
from typing import ClassVar, Optional, Set

from ..config import ProviderConfig
from ..types import LlmProvider, LlmRequest, LlmResponse
from .base import ILlmClient
from warden.shared.infrastructure.logging import get_logger
from warden.shared.infrastructure.resilience import resilient

logger = get_logger(__name__)


class ClaudeCodeMode(str, Enum):
    """Valid modes for Claude Code client."""
    CLI = "cli"
    SDK = "sdk"


# =============================================================================
# CONSTANTS
# =============================================================================

_VALID_MODES = {m.value for m in ClaudeCodeMode}
_DEFAULT_TIMEOUT_SECONDS = 120
_AVAILABILITY_CHECK_TIMEOUT = 5.0
_MAX_PROMPT_LENGTH = 100_000  # Prevent memory issues
_MAX_CONCURRENT_REQUESTS = 3  # Limit parallel Claude Code processes
_CIRCUIT_BREAKER_THRESHOLD = 5  # Consecutive failures before opening circuit
_CIRCUIT_BREAKER_RESET_SECONDS = 60  # Time before attempting to close circuit
_HEALTH_CHECK_CACHE_TTL = 30.0  # Cache availability check for 30 seconds


# =============================================================================
# CIRCUIT BREAKER STATE
# =============================================================================

@dataclass
class CircuitBreakerState:
    """Thread-safe circuit breaker state."""
    consecutive_failures: int = 0
    last_failure_time: float = 0.0
    is_open: bool = False

    def record_success(self) -> None:
        """Reset on success."""
        self.consecutive_failures = 0
        self.is_open = False

    def record_failure(self) -> None:
        """Record failure and potentially open circuit."""
        self.consecutive_failures += 1
        self.last_failure_time = time.monotonic()
        if self.consecutive_failures >= _CIRCUIT_BREAKER_THRESHOLD:
            self.is_open = True
            logger.warning(
                "circuit_breaker_opened",
                consecutive_failures=self.consecutive_failures,
                threshold=_CIRCUIT_BREAKER_THRESHOLD,
            )

    def should_allow_request(self) -> bool:
        """Check if request should be allowed."""
        if not self.is_open:
            return True

        # Check if enough time has passed to try again (half-open state)
        elapsed = time.monotonic() - self.last_failure_time
        if elapsed >= _CIRCUIT_BREAKER_RESET_SECONDS:
            logger.info(
                "circuit_breaker_half_open",
                elapsed_seconds=elapsed,
                reset_threshold=_CIRCUIT_BREAKER_RESET_SECONDS,
            )
            return True

        return False


# =============================================================================
# HEALTH CHECK CACHE
# =============================================================================

@dataclass
class HealthCheckCache:
    """Cached health check result."""
    is_available: bool = False
    checked_at: float = 0.0
    version: str = ""

    def is_valid(self) -> bool:
        """Check if cache is still valid."""
        if self.checked_at == 0.0:
            return False
        elapsed = time.monotonic() - self.checked_at
        return elapsed < _HEALTH_CHECK_CACHE_TTL


# =============================================================================
# PROCESS REGISTRY (for graceful shutdown)
# =============================================================================

class ProcessRegistry:
    """Track active processes for cleanup on shutdown."""

    _instance: ClassVar[Optional["ProcessRegistry"]] = None
    _processes: Set[asyncio.subprocess.Process]
    _lock: asyncio.Lock

    def __new__(cls) -> "ProcessRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._processes = set()
            cls._instance._lock = asyncio.Lock()
            # Register cleanup on interpreter shutdown
            atexit.register(cls._instance._sync_cleanup)
        return cls._instance

    async def register(self, process: asyncio.subprocess.Process) -> None:
        """Register a process for tracking."""
        async with self._lock:
            self._processes.add(process)

    async def unregister(self, process: asyncio.subprocess.Process) -> None:
        """Unregister a completed process."""
        async with self._lock:
            self._processes.discard(process)

    async def cleanup_all(self) -> None:
        """Kill all tracked processes."""
        async with self._lock:
            for process in list(self._processes):
                try:
                    process.kill()
                    await process.wait()
                except ProcessLookupError:
                    pass
            self._processes.clear()
            logger.info("process_registry_cleanup_completed")

    def _sync_cleanup(self) -> None:
        """Synchronous cleanup for atexit."""
        for process in list(self._processes):
            try:
                process.kill()
            except (ProcessLookupError, OSError):
                pass


# =============================================================================
# CLAUDE CODE CLIENT
# =============================================================================

class ClaudeCodeClient(ILlmClient):
    """
    Claude Code client for local LLM execution via Claude Code CLI/SDK.

    Anti-fragile design:
    - Validates configuration at construction (fail-fast)
    - Kills subprocess on timeout (resource cleanup)
    - Logs all failure modes with context (observability)
    - Handles empty/malformed responses gracefully
    - Idempotent operations (safe to retry)
    - Circuit breaker prevents cascade failures
    - Semaphore limits concurrent requests
    - Health check caching reduces overhead
    """

    __slots__ = (
        "_mode", "_default_model", "_cli_path", "_timeout",
        "_semaphore", "_circuit_breaker", "_health_cache", "_process_registry"
    )

    def __init__(self, config: ProviderConfig):
        """
        Initialize Claude Code client.

        Args:
            config: Provider configuration

        Raises:
            ValueError: If mode is invalid (fail-fast)
        """
        # Validate mode (fail-fast, strict types)
        raw_mode = (config.endpoint or "cli").lower().strip()
        if raw_mode not in _VALID_MODES:
            raise ValueError(
                f"Invalid Claude Code mode: '{raw_mode}'. "
                f"Valid modes: {', '.join(_VALID_MODES)}"
            )

        self._mode = ClaudeCodeMode(raw_mode)
        self._default_model = config.default_model or "claude-sonnet-4-20250514"
        self._cli_path = shutil.which("claude") or "claude"
        self._timeout = _DEFAULT_TIMEOUT_SECONDS

        # Concurrency control
        self._semaphore = asyncio.Semaphore(_MAX_CONCURRENT_REQUESTS)

        # Circuit breaker
        self._circuit_breaker = CircuitBreakerState()

        # Health check cache
        self._health_cache = HealthCheckCache()

        # Process registry for cleanup
        self._process_registry = ProcessRegistry()

        logger.info(
            "claude_code_client_initialized",
            mode=self._mode.value,
            default_model=self._default_model,
            cli_path=self._cli_path,
            timeout=self._timeout,
            max_concurrent=_MAX_CONCURRENT_REQUESTS,
        )

    @property
    def provider(self) -> LlmProvider:
        return LlmProvider.CLAUDE_CODE

    @resilient(name="claude_code_send", timeout_seconds=130.0)
    async def send_async(self, request: LlmRequest) -> LlmResponse:
        """
        Send a request to Claude Code.

        Features:
        - Circuit breaker prevents cascade failures
        - Semaphore limits concurrent requests
        - Request ID tracking for observability
        """
        request_id = str(uuid.uuid4())[:8]
        start_time = time.perf_counter()

        # Circuit breaker check (fail-fast)
        if not self._circuit_breaker.should_allow_request():
            logger.warning(
                "claude_code_circuit_breaker_open",
                request_id=request_id,
                consecutive_failures=self._circuit_breaker.consecutive_failures,
            )
            return LlmResponse(
                content="",
                success=False,
                error_message="Circuit breaker open - too many recent failures",
                provider=self.provider,
                duration_ms=0,
            )

        # Input validation (fail-fast)
        if not request.user_message:
            logger.warning("claude_code_empty_request", request_id=request_id)
            return LlmResponse(
                content="",
                success=False,
                error_message="Empty user message",
                provider=self.provider,
                duration_ms=0,
            )

        # Prompt size check
        total_length = len(request.system_prompt or "") + len(request.user_message)
        if total_length > _MAX_PROMPT_LENGTH:
            logger.warning(
                "claude_code_prompt_too_large",
                request_id=request_id,
                prompt_length=total_length,
                max_length=_MAX_PROMPT_LENGTH,
            )
            return LlmResponse(
                content="",
                success=False,
                error_message=f"Prompt too large: {total_length} > {_MAX_PROMPT_LENGTH}",
                provider=self.provider,
                duration_ms=0,
            )

        # Acquire semaphore (concurrency limit)
        try:
            async with asyncio.timeout(5.0):
                await self._semaphore.acquire()
        except asyncio.TimeoutError:
            logger.warning(
                "claude_code_semaphore_timeout",
                request_id=request_id,
                max_concurrent=_MAX_CONCURRENT_REQUESTS,
            )
            return LlmResponse(
                content="",
                success=False,
                error_message="Too many concurrent requests",
                provider=self.provider,
                duration_ms=self._calc_duration_ms(start_time),
            )

        try:
            logger.debug(
                "claude_code_request_started",
                request_id=request_id,
                mode=self._mode.value,
                prompt_length=total_length,
                model=request.model or self._default_model,
            )

            if self._mode == ClaudeCodeMode.SDK:
                response = await self._send_via_sdk(request, request_id)
            else:
                response = await self._send_via_cli(request, request_id)

            # Update circuit breaker
            if response.success:
                self._circuit_breaker.record_success()
            else:
                self._circuit_breaker.record_failure()

            return response

        finally:
            self._semaphore.release()

    async def _send_via_cli(self, request: LlmRequest, request_id: str) -> LlmResponse:
        """
        Execute request via Claude Code CLI.

        Security: Uses subprocess with explicit arguments (no shell=True).
        Cleanup: Kills process on timeout to prevent zombies.
        """
        start_time = time.perf_counter()
        model = request.model or self._default_model
        process: Optional[asyncio.subprocess.Process] = None

        try:
            full_prompt = f"{request.system_prompt}\n\n{request.user_message}"

            process = await asyncio.create_subprocess_exec(
                self._cli_path,
                "--print",
                "--output-format", "json",
                "--max-turns", "1",
                "-p", full_prompt,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            # Register for cleanup
            await self._process_registry.register(process)

            timeout = request.timeout_seconds or self._timeout
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout
            )

            # Unregister after completion
            await self._process_registry.unregister(process)

            duration_ms = self._calc_duration_ms(start_time)

            if process.returncode != 0:
                error_msg = self._safe_decode(stderr) or "Unknown error"
                logger.error(
                    "claude_code_cli_failed",
                    request_id=request_id,
                    returncode=process.returncode,
                    error=error_msg[:500],
                    duration_ms=duration_ms,
                    model=model,
                )
                return LlmResponse(
                    content="",
                    success=False,
                    error_message=f"CLI error (exit {process.returncode}): {error_msg[:200]}",
                    provider=self.provider,
                    model=model,
                    duration_ms=duration_ms,
                )

            return self._parse_cli_response(stdout, request_id, model, duration_ms)

        except asyncio.TimeoutError:
            duration_ms = self._calc_duration_ms(start_time)
            timeout = request.timeout_seconds or self._timeout

            # Kill process to prevent zombies
            if process is not None:
                try:
                    process.kill()
                    await process.wait()
                    await self._process_registry.unregister(process)
                    logger.debug(
                        "claude_code_process_killed",
                        request_id=request_id,
                        pid=process.pid,
                    )
                except ProcessLookupError:
                    pass

            logger.error(
                "claude_code_cli_timeout",
                request_id=request_id,
                timeout_seconds=timeout,
                duration_ms=duration_ms,
                model=model,
            )
            return LlmResponse(
                content="",
                success=False,
                error_message=f"Timeout after {timeout}s",
                provider=self.provider,
                model=model,
                duration_ms=duration_ms,
            )

        except Exception as e:
            duration_ms = self._calc_duration_ms(start_time)

            if process is not None:
                try:
                    process.kill()
                    await self._process_registry.unregister(process)
                except ProcessLookupError:
                    pass

            logger.exception(
                "claude_code_cli_error",
                request_id=request_id,
                error=str(e),
                error_type=type(e).__name__,
                duration_ms=duration_ms,
                model=model,
            )
            return LlmResponse(
                content="",
                success=False,
                error_message=f"{type(e).__name__}: {str(e)[:200]}",
                provider=self.provider,
                model=model,
                duration_ms=duration_ms,
            )

    def _parse_cli_response(
        self, stdout: bytes, request_id: str, model: str, duration_ms: int
    ) -> LlmResponse:
        """Parse CLI response with graceful error handling."""
        output = self._safe_decode(stdout)

        if not output:
            logger.warning(
                "claude_code_empty_response",
                request_id=request_id,
                duration_ms=duration_ms,
            )
            return LlmResponse(
                content="",
                success=False,
                error_message="Empty response from Claude Code",
                provider=self.provider,
                model=model,
                duration_ms=duration_ms,
            )

        try:
            result = json.loads(output)
            content = result.get("result") or result.get("content") or ""

            if not isinstance(content, str):
                content = str(content) if content else ""

            usage = result.get("usage", {})
            prompt_tokens = usage.get("input_tokens", 0)
            completion_tokens = usage.get("output_tokens", 0)

            logger.info(
                "claude_code_request_completed",
                request_id=request_id,
                duration_ms=duration_ms,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                response_length=len(content),
            )

            return LlmResponse(
                content=content,
                success=True,
                provider=self.provider,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                duration_ms=duration_ms,
            )

        except json.JSONDecodeError as e:
            logger.debug(
                "claude_code_non_json_response",
                request_id=request_id,
                parse_error=str(e),
                output_preview=output[:100],
            )
            return LlmResponse(
                content=output,
                success=True,
                provider=self.provider,
                model=model,
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                duration_ms=duration_ms,
            )

    async def _send_via_sdk(self, request: LlmRequest, request_id: str) -> LlmResponse:
        """Execute request via Claude Agent SDK with graceful degradation."""
        start_time = time.perf_counter()
        model = request.model or self._default_model

        try:
            from claude_code_sdk import query, ClaudeCodeOptions

            full_prompt = f"{request.system_prompt}\n\n{request.user_message}"

            response_parts: list[str] = []
            async for message in query(
                prompt=full_prompt,
                options=ClaudeCodeOptions(max_turns=1, model=model)
            ):
                if hasattr(message, "content") and message.content:
                    response_parts.append(str(message.content))

            duration_ms = self._calc_duration_ms(start_time)
            content = "".join(response_parts)

            logger.info(
                "claude_code_sdk_completed",
                request_id=request_id,
                duration_ms=duration_ms,
                model=model,
                response_length=len(content),
            )

            return LlmResponse(
                content=content,
                success=bool(content),
                error_message=None if content else "Empty response from SDK",
                provider=self.provider,
                model=model,
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                duration_ms=duration_ms,
            )

        except ImportError:
            logger.warning(
                "claude_code_sdk_not_installed",
                request_id=request_id,
                fallback="cli",
            )
            return await self._send_via_cli(request, request_id)

        except Exception as e:
            duration_ms = self._calc_duration_ms(start_time)
            logger.exception(
                "claude_code_sdk_error",
                request_id=request_id,
                error=str(e),
                error_type=type(e).__name__,
                duration_ms=duration_ms,
                model=model,
            )
            return LlmResponse(
                content="",
                success=False,
                error_message=f"{type(e).__name__}: {str(e)[:200]}",
                provider=self.provider,
                model=model,
                duration_ms=duration_ms,
            )

    async def is_available_async(self) -> bool:
        """
        Check if Claude Code CLI is installed and accessible.

        Uses caching to reduce overhead from repeated checks.
        """
        # Return cached result if valid
        if self._health_cache.is_valid():
            logger.debug(
                "claude_code_health_cache_hit",
                is_available=self._health_cache.is_available,
                version=self._health_cache.version,
            )
            return self._health_cache.is_available

        # Perform actual check
        try:
            if not shutil.which("claude"):
                self._health_cache = HealthCheckCache(
                    is_available=False,
                    checked_at=time.monotonic(),
                )
                logger.debug("claude_code_cli_not_in_path")
                return False

            process = await asyncio.create_subprocess_exec(
                self._cli_path,
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, _ = await asyncio.wait_for(
                process.communicate(),
                timeout=_AVAILABILITY_CHECK_TIMEOUT
            )

            if process.returncode == 0:
                version = self._safe_decode(stdout)
                self._health_cache = HealthCheckCache(
                    is_available=True,
                    checked_at=time.monotonic(),
                    version=version,
                )
                logger.debug("claude_code_available", version=version)
                return True

            self._health_cache = HealthCheckCache(
                is_available=False,
                checked_at=time.monotonic(),
            )
            logger.debug(
                "claude_code_version_check_failed",
                returncode=process.returncode,
            )
            return False

        except asyncio.TimeoutError:
            self._health_cache = HealthCheckCache(
                is_available=False,
                checked_at=time.monotonic(),
            )
            logger.debug("claude_code_availability_timeout")
            return False
        except Exception as e:
            self._health_cache = HealthCheckCache(
                is_available=False,
                checked_at=time.monotonic(),
            )
            logger.debug(
                "claude_code_availability_error",
                error=str(e),
                error_type=type(e).__name__,
            )
            return False

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    @staticmethod
    def _calc_duration_ms(start_time: float) -> int:
        """Calculate duration in milliseconds."""
        return int((time.perf_counter() - start_time) * 1000)

    @staticmethod
    def _safe_decode(data: Optional[bytes]) -> str:
        """Safely decode bytes to string."""
        if not data:
            return ""
        try:
            return data.decode("utf-8", errors="replace").strip()
        except Exception:
            return ""


# =============================================================================
# PUBLIC API
# =============================================================================

async def detect_claude_code() -> bool:
    """
    Utility function to detect if Claude Code is available.
    Used by config auto-detection.
    """
    try:
        client = ClaudeCodeClient(ProviderConfig(enabled=True, endpoint="cli"))
        return await client.is_available_async()
    except ValueError:
        return False
