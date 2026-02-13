"""Combined Resilience Operation."""

import functools
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, Optional, TypeVar

from .circuit_breaker import CircuitBreaker, CircuitBreakerConfig, CircuitBreakerOpen, CircuitState
from .retry import RetryConfig, with_retry_async
from .timeout import with_timeout_async

T = TypeVar("T")


@dataclass
class ResilienceConfig:
    """Combined resilience configuration."""

    timeout_seconds: float | None = 30.0
    retry_enabled: bool = True
    retry_max_attempts: int = 3
    retry_initial_delay: float = 1.0
    retry_max_delay: float = 30.0
    retryable_exceptions: tuple = (Exception,)
    circuit_breaker_enabled: bool = True
    circuit_failure_threshold: int = 5
    circuit_timeout_duration: float = 60.0


class ResilientOperation(Generic[T]):
    """Combines multiple resilience patterns."""

    def __init__(self, name: str, config: ResilienceConfig | None = None):
        self.name = name
        self.config = config or ResilienceConfig()
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

    async def execute_async(self, operation: Callable[[], Any]) -> T:
        if self._circuit_breaker:
            state = self._circuit_breaker.state
            if state == CircuitState.OPEN:
                raise CircuitBreakerOpen(self.name, self.config.circuit_timeout_duration)

        async def execute_once_async():
            coro = operation()
            if self.config.timeout_seconds:
                return await with_timeout_async(coro, self.config.timeout_seconds, self.name)
            return await coro

        try:
            if self.config.retry_enabled:
                retry_config = RetryConfig(
                    max_attempts=self.config.retry_max_attempts,
                    initial_delay=self.config.retry_initial_delay,
                    max_delay=self.config.retry_max_delay,
                    retryable_exceptions=self.config.retryable_exceptions,
                )
                result = await with_retry_async(execute_once_async, retry_config, self.name)
            else:
                result = await execute_once_async()
            if self._circuit_breaker:
                self._circuit_breaker._record_success()
            return result
        except Exception as e:
            if self._circuit_breaker:
                self._circuit_breaker._record_failure(e)
            raise


def resilient(
    name: str | None = None,
    timeout_seconds: float = 30.0,
    retry_max_attempts: int = 3,
    circuit_breaker_enabled: bool = True,
):
    """Decorator to add all resilience patterns."""
    config = ResilienceConfig(
        timeout_seconds=timeout_seconds,
        retry_max_attempts=retry_max_attempts,
        circuit_breaker_enabled=circuit_breaker_enabled,
    )

    def decorator(func):
        op_name = name or func.__name__
        resilient_op = ResilientOperation(op_name, config)

        @functools.wraps(func)
        async def wrapper_async(*args, **kwargs):
            return await resilient_op.execute_async(lambda: func(*args, **kwargs))

        return wrapper_async

    return decorator
