"""Circuit Breaker Resilience Pattern."""

import functools
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)

class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker."""
    failure_threshold: int = 5
    success_threshold: int = 2
    timeout_duration: float = 60.0
    excluded_exceptions: tuple = ()

class CircuitBreakerOpen(Exception):
    """Raised when circuit is open."""
    def __init__(self, name: str, retry_after: float):
        self.name = name
        self.retry_after = retry_after
        super().__init__(
            f"Circuit '{name}' is open. Retry after {retry_after:.1f}s"
        )

class CircuitBreaker:
    """Circuit breaker implementation."""
    def __init__(self, name: str, config: Optional[CircuitBreakerConfig] = None):
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: Optional[float] = None

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            if self._last_failure_time:
                elapsed = time.time() - self._last_failure_time
                if elapsed >= self.config.timeout_duration:
                    self._transition_to(CircuitState.HALF_OPEN)
        return self._state

    def _transition_to(self, new_state: CircuitState) -> None:
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
        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self.config.success_threshold:
                self._transition_to(CircuitState.CLOSED)

    def _record_failure(self, error: Exception) -> None:
        if isinstance(error, self.config.excluded_exceptions):
            return
        self._failure_count += 1
        self._last_failure_time = time.time()
        if self._state == CircuitState.CLOSED:
            if self._failure_count >= self.config.failure_threshold:
                self._transition_to(CircuitState.OPEN)
        elif self._state == CircuitState.HALF_OPEN:
            self._transition_to(CircuitState.OPEN)

    async def __aenter__(self):
        state = self.state
        if state == CircuitState.OPEN:
            retry_after = self.config.timeout_duration
            if self._last_failure_time:
                elapsed = time.time() - self._last_failure_time
                retry_after = max(0, self.config.timeout_duration - elapsed)
            raise CircuitBreakerOpen(self.name, retry_after)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self._record_success()
        elif exc_val is not None:
            self._record_failure(exc_val)
        return False

def circuit_breaker(
    name: str,
    failure_threshold: int = 5,
    timeout_duration: float = 60.0,
):
    """Decorator to add circuit breaker to async functions."""
    config = CircuitBreakerConfig(
        failure_threshold=failure_threshold,
        timeout_duration=timeout_duration,
    )
    breaker = CircuitBreaker(name, config)
    def decorator(func):
        @functools.wraps(func)
        async def wrapper_async(*args, **kwargs):
            async with breaker:
                return await func(*args, **kwargs)
        return wrapper_async
    return decorator
