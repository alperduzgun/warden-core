"""
Resilience Patterns for Warden.

Provides common fault-tolerance patterns:
- Timeout: Prevent indefinite hangs
- Retry: Handle transient failures with exponential backoff
- Circuit Breaker: Prevent cascading failures
- Bulkhead: Isolate failure domains

Author: Warden Chaos Team
Version: 1.0.0
"""

import asyncio
import functools
import random
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Generic, Optional, TypeVar

from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


# ============================================================================
# Timeout Pattern
# ============================================================================


class TimeoutError(Exception):
    """Raised when an operation times out."""

    def __init__(self, operation: str, timeout_seconds: float):
        self.operation = operation
        self.timeout_seconds = timeout_seconds
        super().__init__(
            f"Operation '{operation}' timed out after {timeout_seconds}s"
        )


async def with_timeout(
    coro,
    timeout_seconds: float,
    operation_name: str = "operation",
) -> Any:
    """
    Execute a coroutine with a timeout.

    Args:
        coro: Async coroutine to execute
        timeout_seconds: Maximum time to wait
        operation_name: Name for logging/error messages

    Returns:
        Result of the coroutine

    Raises:
        TimeoutError: If the operation times out
    """
    try:
        return await asyncio.wait_for(coro, timeout=timeout_seconds)
    except asyncio.TimeoutError:
        logger.warning(
            "operation_timeout",
            operation=operation_name,
            timeout=timeout_seconds,
        )
        raise TimeoutError(operation_name, timeout_seconds)


def timeout(seconds: float, operation_name: Optional[str] = None):
    """
    Decorator to add timeout to async functions.

    Usage:
        @timeout(30.0, "api_call")
        async def call_api():
            ...
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            name = operation_name or func.__name__
            return await with_timeout(
                func(*args, **kwargs),
                seconds,
                name,
            )
        return wrapper
    return decorator


# ============================================================================
# Retry Pattern with Exponential Backoff
# ============================================================================


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""

    max_attempts: int = 3
    initial_delay: float = 1.0  # seconds
    max_delay: float = 30.0  # seconds
    exponential_base: float = 2.0
    jitter: bool = True  # Add randomness to prevent thundering herd
    retryable_exceptions: tuple = (Exception,)


class RetryExhausted(Exception):
    """Raised when all retry attempts are exhausted."""

    def __init__(
        self,
        operation: str,
        attempts: int,
        last_error: Exception,
    ):
        self.operation = operation
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(
            f"Operation '{operation}' failed after {attempts} attempts: {last_error}"
        )


async def with_retry(
    coro_factory: Callable[[], Any],
    config: Optional[RetryConfig] = None,
    operation_name: str = "operation",
) -> Any:
    """
    Execute an async operation with retry logic.

    Args:
        coro_factory: Function that returns a new coroutine for each attempt
        config: Retry configuration
        operation_name: Name for logging

    Returns:
        Result of the operation

    Raises:
        RetryExhausted: If all attempts fail
    """
    config = config or RetryConfig()
    last_error: Optional[Exception] = None

    for attempt in range(1, config.max_attempts + 1):
        try:
            return await coro_factory()

        except config.retryable_exceptions as e:
            last_error = e

            if attempt >= config.max_attempts:
                logger.error(
                    "retry_exhausted",
                    operation=operation_name,
                    attempt=attempt,
                    error=str(e),
                )
                raise RetryExhausted(operation_name, attempt, e)

            # Calculate delay with exponential backoff
            delay = min(
                config.initial_delay * (config.exponential_base ** (attempt - 1)),
                config.max_delay,
            )

            # Add jitter (0.5 to 1.5 of calculated delay)
            if config.jitter:
                delay = delay * (0.5 + random.random())

            logger.warning(
                "retry_attempt",
                operation=operation_name,
                attempt=attempt,
                max_attempts=config.max_attempts,
                delay=f"{delay:.2f}s",
                error=str(e),
            )

            await asyncio.sleep(delay)

    # Should not reach here, but safety net
    raise RetryExhausted(operation_name, config.max_attempts, last_error)


def retry(
    max_attempts: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 30.0,
    retryable_exceptions: tuple = (Exception,),
    operation_name: Optional[str] = None,
):
    """
    Decorator to add retry logic to async functions.

    Usage:
        @retry(max_attempts=3, initial_delay=1.0)
        async def call_api():
            ...
    """
    config = RetryConfig(
        max_attempts=max_attempts,
        initial_delay=initial_delay,
        max_delay=max_delay,
        retryable_exceptions=retryable_exceptions,
    )

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            name = operation_name or func.__name__
            return await with_retry(
                lambda: func(*args, **kwargs),
                config,
                name,
            )
        return wrapper
    return decorator


# ============================================================================
# Circuit Breaker Pattern
# ============================================================================


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing fast
    HALF_OPEN = "half_open"  # Testing recovery


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker."""

    failure_threshold: int = 5  # Failures before opening
    success_threshold: int = 2  # Successes in half-open to close
    timeout_duration: float = 60.0  # Seconds before trying half-open
    excluded_exceptions: tuple = ()  # Exceptions that don't count as failures


class CircuitBreakerOpen(Exception):
    """Raised when circuit is open."""

    def __init__(self, name: str, retry_after: float):
        self.name = name
        self.retry_after = retry_after
        super().__init__(
            f"Circuit '{name}' is open. Retry after {retry_after:.1f}s"
        )


class CircuitBreaker:
    """
    Circuit breaker implementation.

    States:
    - CLOSED: Normal operation, requests pass through
    - OPEN: Failing fast, requests immediately rejected
    - HALF_OPEN: Testing if service recovered

    Usage:
        breaker = CircuitBreaker("api_service")

        async def call_with_breaker():
            async with breaker:
                return await call_api()
    """

    def __init__(
        self,
        name: str,
        config: Optional[CircuitBreakerConfig] = None,
    ):
        """Initialize circuit breaker."""
        self.name = name
        self.config = config or CircuitBreakerConfig()

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: Optional[float] = None

    @property
    def state(self) -> CircuitState:
        """Get current state, auto-transitioning if needed."""
        if self._state == CircuitState.OPEN:
            # Check if we should transition to half-open
            if self._last_failure_time:
                elapsed = time.time() - self._last_failure_time
                if elapsed >= self.config.timeout_duration:
                    self._transition_to(CircuitState.HALF_OPEN)

        return self._state

    def _transition_to(self, new_state: CircuitState) -> None:
        """Transition to a new state."""
        old_state = self._state
        self._state = new_state

        if new_state == CircuitState.CLOSED:
            self._failure_count = 0
            self._success_count = 0
        elif new_state == CircuitState.HALF_OPEN:
            self._success_count = 0

        logger.info(
            "circuit_state_change",
            circuit=self.name,
            from_state=old_state.value,
            to_state=new_state.value,
        )

    def _record_success(self) -> None:
        """Record a successful operation."""
        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self.config.success_threshold:
                self._transition_to(CircuitState.CLOSED)

    def _record_failure(self, error: Exception) -> None:
        """Record a failed operation."""
        # Check if this exception should be excluded
        if isinstance(error, self.config.excluded_exceptions):
            return

        self._failure_count += 1
        self._last_failure_time = time.time()

        if self._state == CircuitState.CLOSED:
            if self._failure_count >= self.config.failure_threshold:
                self._transition_to(CircuitState.OPEN)

        elif self._state == CircuitState.HALF_OPEN:
            # Any failure in half-open goes back to open
            self._transition_to(CircuitState.OPEN)

    async def __aenter__(self):
        """Context manager entry."""
        state = self.state

        if state == CircuitState.OPEN:
            retry_after = self.config.timeout_duration
            if self._last_failure_time:
                elapsed = time.time() - self._last_failure_time
                retry_after = max(0, self.config.timeout_duration - elapsed)

            raise CircuitBreakerOpen(self.name, retry_after)

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        if exc_type is None:
            self._record_success()
        elif exc_val is not None:
            self._record_failure(exc_val)

        return False  # Don't suppress exceptions


def circuit_breaker(
    name: str,
    failure_threshold: int = 5,
    timeout_duration: float = 60.0,
):
    """
    Decorator to add circuit breaker to async functions.

    Usage:
        @circuit_breaker("api_service", failure_threshold=3)
        async def call_api():
            ...
    """
    config = CircuitBreakerConfig(
        failure_threshold=failure_threshold,
        timeout_duration=timeout_duration,
    )
    breaker = CircuitBreaker(name, config)

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            async with breaker:
                return await func(*args, **kwargs)
        return wrapper
    return decorator


# ============================================================================
# Bulkhead Pattern
# ============================================================================


@dataclass
class BulkheadConfig:
    """Configuration for bulkhead pattern."""

    max_concurrent: int = 10  # Max concurrent executions
    max_waiting: int = 100  # Max waiting in queue
    timeout: float = 30.0  # Max wait time for semaphore


class BulkheadFull(Exception):
    """Raised when bulkhead is at capacity."""

    def __init__(self, name: str, max_concurrent: int):
        self.name = name
        self.max_concurrent = max_concurrent
        super().__init__(
            f"Bulkhead '{name}' at capacity ({max_concurrent} concurrent)"
        )


class Bulkhead:
    """
    Bulkhead pattern for resource isolation.

    Limits concurrent executions to prevent resource exhaustion.

    Usage:
        bulkhead = Bulkhead("file_operations", max_concurrent=5)

        async def read_with_bulkhead():
            async with bulkhead:
                return await read_file()
    """

    def __init__(
        self,
        name: str,
        config: Optional[BulkheadConfig] = None,
    ):
        """Initialize bulkhead."""
        self.name = name
        self.config = config or BulkheadConfig()

        self._semaphore = asyncio.Semaphore(self.config.max_concurrent)
        self._waiting = 0

    @property
    def available(self) -> int:
        """Get number of available slots."""
        return self._semaphore._value

    async def __aenter__(self):
        """Context manager entry."""
        if self._waiting >= self.config.max_waiting:
            raise BulkheadFull(self.name, self.config.max_concurrent)

        self._waiting += 1
        try:
            await asyncio.wait_for(
                self._semaphore.acquire(),
                timeout=self.config.timeout,
            )
        except asyncio.TimeoutError:
            self._waiting -= 1
            raise BulkheadFull(self.name, self.config.max_concurrent)

        self._waiting -= 1
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self._semaphore.release()
        return False


# ============================================================================
# Combined Resilience Decorator
# ============================================================================


@dataclass
class ResilienceConfig:
    """Combined resilience configuration."""

    # Timeout
    timeout_seconds: Optional[float] = 30.0

    # Retry
    retry_enabled: bool = True
    retry_max_attempts: int = 3
    retry_initial_delay: float = 1.0
    retry_max_delay: float = 30.0
    retryable_exceptions: tuple = (Exception,)

    # Circuit Breaker
    circuit_breaker_enabled: bool = True
    circuit_failure_threshold: int = 5
    circuit_timeout_duration: float = 60.0


class ResilientOperation(Generic[T]):
    """
    Combines multiple resilience patterns for an operation.

    Applies patterns in this order:
    1. Circuit Breaker (fast-fail if open)
    2. Timeout (prevent hangs)
    3. Retry (handle transient failures)

    Usage:
        resilient = ResilientOperation[Response](
            "api_call",
            config=ResilienceConfig(timeout_seconds=10.0),
        )

        result = await resilient.execute(call_api)
    """

    def __init__(
        self,
        name: str,
        config: Optional[ResilienceConfig] = None,
    ):
        """Initialize resilient operation."""
        self.name = name
        self.config = config or ResilienceConfig()

        # Initialize circuit breaker if enabled
        if self.config.circuit_breaker_enabled:
            self._circuit_breaker = CircuitBreaker(
                name,
                CircuitBreakerConfig(
                    failure_threshold=self.config.circuit_failure_threshold,
                    timeout_duration=self.config.circuit_timeout_duration,
                ),
            )
        else:
            self._circuit_breaker = None

    async def execute(
        self,
        operation: Callable[[], Any],
    ) -> T:
        """
        Execute operation with all resilience patterns.

        Args:
            operation: Async function to execute

        Returns:
            Result of the operation

        Raises:
            CircuitBreakerOpen: If circuit is open
            TimeoutError: If operation times out
            RetryExhausted: If all retries fail
        """
        # 1. Check circuit breaker
        if self._circuit_breaker:
            state = self._circuit_breaker.state
            if state == CircuitState.OPEN:
                retry_after = self.config.circuit_timeout_duration
                raise CircuitBreakerOpen(self.name, retry_after)

        async def execute_once():
            """Execute operation once with timeout."""
            coro = operation()

            if self.config.timeout_seconds:
                return await with_timeout(
                    coro,
                    self.config.timeout_seconds,
                    self.name,
                )
            else:
                return await coro

        try:
            # 2. With retry if enabled
            if self.config.retry_enabled:
                retry_config = RetryConfig(
                    max_attempts=self.config.retry_max_attempts,
                    initial_delay=self.config.retry_initial_delay,
                    max_delay=self.config.retry_max_delay,
                    retryable_exceptions=self.config.retryable_exceptions,
                )
                result = await with_retry(
                    execute_once,
                    retry_config,
                    self.name,
                )
            else:
                result = await execute_once()

            # Record success
            if self._circuit_breaker:
                self._circuit_breaker._record_success()

            return result

        except Exception as e:
            # Record failure
            if self._circuit_breaker:
                self._circuit_breaker._record_failure(e)
            raise


def resilient(
    name: Optional[str] = None,
    timeout_seconds: float = 30.0,
    retry_max_attempts: int = 3,
    circuit_breaker_enabled: bool = True,
):
    """
    Decorator to add all resilience patterns to async functions.

    Usage:
        @resilient("api_call", timeout_seconds=10.0, retry_max_attempts=3)
        async def call_api():
            ...
    """
    config = ResilienceConfig(
        timeout_seconds=timeout_seconds,
        retry_max_attempts=retry_max_attempts,
        circuit_breaker_enabled=circuit_breaker_enabled,
    )

    def decorator(func):
        operation_name = name or func.__name__
        resilient_op = ResilientOperation(operation_name, config)

        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            return await resilient_op.execute(
                lambda: func(*args, **kwargs)
            )
        return wrapper
    return decorator
