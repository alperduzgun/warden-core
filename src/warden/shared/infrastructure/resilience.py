"""
Resilience patterns for Warden pipeline (Polly-style).

Implements:
- Retry with exponential backoff
- Circuit breaker
- Timeout (already in orchestrator)

Inspired by Polly (C# resilience library):
https://github.com/App-vNext/Polly
"""

import asyncio
import random
import time
from enum import Enum
from dataclasses import dataclass, field
from typing import Callable, TypeVar, Generic, Any
from datetime import datetime, timedelta

from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


# Default timeout constants for different operation types
DEFAULT_TIMEOUT_EXTERNAL_API = 30.0  # External 3rd party APIs
DEFAULT_TIMEOUT_INTERNAL_SERVICE = 10.0  # Internal microservices
DEFAULT_TIMEOUT_DATABASE = 5.0  # Database queries
DEFAULT_TIMEOUT_LLM = 60.0  # LLM operations (can be slow)
DEFAULT_TIMEOUT_FRAME = 120.0  # Validation frame execution


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Too many failures, reject immediately
    HALF_OPEN = "half_open"  # Testing if service recovered


@dataclass
class RetryOptions:
    """Configuration for retry strategy."""

    max_attempts: int = 3  # Total attempts (1 original + 2 retries)
    initial_delay: float = 1.0  # Initial retry delay in seconds
    use_exponential_backoff: bool = True
    use_jitter: bool = True  # Add randomness to prevent thundering herd
    jitter_range: float = 0.2  # Jitter percentage (default: ±20%)
    max_delay: float = 30.0  # Maximum delay between retries


@dataclass
class CircuitBreakerOptions:
    """Configuration for circuit breaker strategy."""

    failure_threshold: float = 0.7  # Open circuit if 70% of requests fail
    sampling_duration: float = 30.0  # Time window for failure ratio calculation (seconds)
    minimum_throughput: int = 3  # Minimum requests before circuit breaker activates
    break_duration: float = 60.0  # How long circuit stays open (seconds)


class CircuitBreaker:
    """
    Circuit breaker implementation.

    Prevents cascading failures by failing fast when error rate is too high.
    """

    def __init__(self, options: CircuitBreakerOptions):
        self.options = options
        self.state = CircuitState.CLOSED
        self.failures: list[datetime] = []
        self.successes: list[datetime] = []
        self.opened_at: datetime | None = None

        # Metrics tracking
        self.metrics = {
            "total_requests": 0,
            "total_failures": 0,
            "total_successes": 0,
            "state_changes": [],
        }

    def _clean_old_records(self):
        """Remove records outside sampling window."""
        cutoff = datetime.utcnow() - timedelta(seconds=self.options.sampling_duration)
        self.failures = [f for f in self.failures if f > cutoff]
        self.successes = [s for s in self.successes if s > cutoff]

    def _get_failure_ratio(self) -> float:
        """Calculate current failure ratio."""
        total = len(self.failures) + len(self.successes)
        if total == 0:
            return 0.0
        return len(self.failures) / total

    def _should_open(self) -> bool:
        """Check if circuit should open."""
        self._clean_old_records()
        total = len(self.failures) + len(self.successes)

        if total < self.options.minimum_throughput:
            return False

        failure_ratio = self._get_failure_ratio()
        return failure_ratio >= self.options.failure_threshold

    def _should_attempt_reset(self) -> bool:
        """Check if circuit should attempt reset (go to half-open)."""
        if self.state != CircuitState.OPEN:
            return False

        if self.opened_at is None:
            return True

        elapsed = (datetime.utcnow() - self.opened_at).total_seconds()
        return elapsed >= self.options.break_duration

    def _change_state(self, new_state: CircuitState):
        """Change circuit state and track metrics."""
        old_state = self.state
        self.state = new_state
        self.metrics["state_changes"].append(
            {
                "from": old_state.value,
                "to": new_state.value,
                "timestamp": datetime.utcnow().isoformat(),
            }
        )

    def get_metrics(self) -> dict:
        """
        Return circuit breaker metrics for monitoring.

        Returns:
            Dictionary containing metrics:
            - total_requests: Total number of requests
            - total_failures: Total number of failures
            - total_successes: Total number of successes
            - state_changes: History of state changes
            - current_state: Current circuit state
            - failure_ratio: Current failure ratio
        """
        return {
            **self.metrics,
            "current_state": self.state.value,
            "failure_ratio": self._get_failure_ratio(),
        }

    async def execute(self, func: Callable[[], Any]) -> Any:
        """
        Execute function with circuit breaker protection.

        Args:
            func: Async function to execute

        Returns:
            Result from function

        Raises:
            Exception: If circuit is OPEN (fail fast)
            Exception: If function raises
        """
        # Update metrics
        self.metrics["total_requests"] += 1

        # Check if should attempt reset
        if self._should_attempt_reset():
            logger.info(
                "circuit_breaker_half_open",
                message="Circuit breaker HALF-OPEN: Testing recovery",
            )
            self._change_state(CircuitState.HALF_OPEN)

        # Fail fast if circuit is open
        if self.state == CircuitState.OPEN:
            logger.error(
                "circuit_breaker_open",
                message="Circuit breaker OPEN: Failing fast",
            )
            raise Exception("Circuit breaker is OPEN - system is unhealthy")

        # Execute function
        try:
            result = await func()

            # Record success
            self.successes.append(datetime.utcnow())
            self.metrics["total_successes"] += 1

            # Close circuit if was half-open
            if self.state == CircuitState.HALF_OPEN:
                logger.info(
                    "circuit_breaker_closed",
                    message="Circuit breaker CLOSED: Normal operation resumed",
                )
                self._change_state(CircuitState.CLOSED)
                self.failures.clear()
                self.successes.clear()

            return result

        except Exception as e:
            # Record failure
            self.failures.append(datetime.utcnow())
            self.metrics["total_failures"] += 1

            # Check if should open circuit
            if self.state == CircuitState.CLOSED and self._should_open():
                self.opened_at = datetime.utcnow()
                failure_ratio = self._get_failure_ratio()

                logger.error(
                    "circuit_breaker_opened",
                    failure_ratio=f"{failure_ratio:.1%}",
                    break_duration=self.options.break_duration,
                    message=f"Circuit breaker OPENED: Too many failures ({failure_ratio:.1%}). Breaking for {self.options.break_duration}s",
                )
                self._change_state(CircuitState.OPEN)

            # If half-open test failed, reopen circuit
            if self.state == CircuitState.HALF_OPEN:
                self.opened_at = datetime.utcnow()
                logger.warning(
                    "circuit_breaker_reopened",
                    message="Circuit breaker REOPENED: Half-open test failed",
                )
                self._change_state(CircuitState.OPEN)

            raise


class RetryPolicy:
    """
    Retry policy with exponential backoff and jitter.

    Automatically retries failed operations with increasing delays.
    """

    def __init__(self, options: RetryOptions):
        self.options = options

    def _calculate_delay(self, attempt: int) -> float:
        """Calculate retry delay with exponential backoff and jitter."""
        if self.options.use_exponential_backoff:
            # Exponential backoff: delay * (2 ^ attempt)
            delay = self.options.initial_delay * (2**attempt)
        else:
            # Fixed delay
            delay = self.options.initial_delay

        # Cap at max delay
        delay = min(delay, self.options.max_delay)

        # Add jitter (randomness) to prevent thundering herd
        if self.options.use_jitter:
            # Jitter: configurable percentage (default: ±20%)
            jitter_range = delay * self.options.jitter_range
            delay += random.uniform(-jitter_range, jitter_range)
            delay = max(0.1, delay)  # Ensure positive delay

        return delay

    async def execute(self, func: Callable[[], Any]) -> Any:
        """
        Execute function with retry logic.

        Args:
            func: Async function to execute

        Returns:
            Result from function

        Raises:
            Exception: If all retry attempts fail
        """
        last_exception = None

        for attempt in range(self.options.max_attempts):
            try:
                # Execute function
                result = await func()
                return result

            except Exception as e:
                last_exception = e

                # If this was the last attempt, raise
                if attempt >= self.options.max_attempts - 1:
                    logger.error(
                        "retry_exhausted",
                        attempt=attempt + 1,
                        max_attempts=self.options.max_attempts,
                        error=str(e),
                        message=f"All retry attempts exhausted ({self.options.max_attempts})",
                    )
                    raise

                # Calculate delay for next retry
                delay = self._calculate_delay(attempt)

                logger.warning(
                    "retry_attempt",
                    attempt=attempt + 1,
                    delay_seconds=f"{delay:.2f}",
                    error=str(e),
                    message=f"Retry attempt {attempt + 1} after {delay:.2f}s. Reason: {str(e)[:100]}",
                )

                # Wait before retrying
                await asyncio.sleep(delay)

        # This should never be reached, but just in case
        raise last_exception or Exception("Retry policy failed unexpectedly")


class ResiliencePipeline:
    """
    Resilience pipeline combining retry and circuit breaker (Polly-style).

    Usage:
    ```python
    pipeline = ResiliencePipeline(
        retry_options=RetryOptions(max_attempts=3),
        circuit_breaker_options=CircuitBreakerOptions(failure_threshold=0.7)
    )

    result = await pipeline.execute(my_async_function)
    ```
    """

    def __init__(
        self,
        retry_options: RetryOptions | None = None,
        circuit_breaker_options: CircuitBreakerOptions | None = None,
    ):
        self.retry_policy = RetryPolicy(retry_options or RetryOptions())
        self.circuit_breaker = (
            CircuitBreaker(circuit_breaker_options)
            if circuit_breaker_options
            else None
        )

    async def execute(self, func: Callable[[], Any]) -> Any:
        """
        Execute function through resilience pipeline.

        Order of execution:
        1. Circuit Breaker (fail fast if system unhealthy)
        2. Retry (with exponential backoff)
        3. Function execution

        Args:
            func: Async function to execute

        Returns:
            Result from function

        Raises:
            Exception: If circuit breaker is open or all retries fail
        """

        async def execute_with_circuit_breaker():
            if self.circuit_breaker:
                return await self.circuit_breaker.execute(func)
            else:
                return await func()

        # Execute with retry (which includes circuit breaker)
        return await self.retry_policy.execute(execute_with_circuit_breaker)
