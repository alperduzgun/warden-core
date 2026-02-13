"""Retry Resilience Pattern."""

import asyncio
import functools
import random
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Optional

from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""

    max_attempts: int = 3
    initial_delay: float = 1.0
    max_delay: float = 30.0
    exponential_base: float = 2.0
    jitter: bool = True
    retryable_exceptions: tuple = (Exception,)


class RetryExhausted(Exception):
    """Raised when all retry attempts are exhausted."""

    def __init__(self, operation: str, attempts: int, last_error: Exception):
        self.operation = operation
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(f"Operation '{operation}' failed after {attempts} attempts: {last_error}")


async def with_retry_async(
    coro_factory: Callable[[], Any],
    config: RetryConfig | None = None,
    operation_name: str = "operation",
) -> Any:
    """Execute an async operation with retry logic."""
    config = config or RetryConfig()
    last_error: Exception | None = None

    for attempt in range(1, config.max_attempts + 1):
        try:
            return await coro_factory()
        except config.retryable_exceptions as e:
            # Don't retry permanent failures (marked with non_retryable=True)
            if getattr(e, "non_retryable", False):
                raise
            last_error = e
            if attempt >= config.max_attempts:
                logger.error(
                    "retry_exhausted",
                    operation=operation_name,
                    attempt=attempt,
                    error=str(e),
                )
                raise RetryExhausted(operation_name, attempt, e)

            delay = min(
                config.initial_delay * (config.exponential_base ** (attempt - 1)),
                config.max_delay,
            )
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

    raise RetryExhausted(operation_name, config.max_attempts, last_error)


def retry(
    max_attempts: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 30.0,
    retryable_exceptions: tuple = (Exception,),
    operation_name: str | None = None,
):
    """Decorator to add retry logic to async functions."""
    config = RetryConfig(
        max_attempts=max_attempts,
        initial_delay=initial_delay,
        max_delay=max_delay,
        retryable_exceptions=retryable_exceptions,
    )

    def decorator(func):
        @functools.wraps(func)
        async def wrapper_async(*args, **kwargs):
            name = operation_name or func.__name__
            return await with_retry_async(
                lambda: func(*args, **kwargs),
                config,
                name,
            )

        return wrapper_async

    return decorator
