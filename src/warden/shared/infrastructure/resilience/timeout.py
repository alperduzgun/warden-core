"""Timeout Resilience Pattern."""

import asyncio
import functools
from typing import Any, Optional
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)

class TimeoutError(Exception):
    """Raised when an operation times out."""
    def __init__(self, operation: str, timeout_seconds: float):
        self.operation = operation
        self.timeout_seconds = timeout_seconds
        super().__init__(
            f"Operation '{operation}' timed out after {timeout_seconds}s"
        )

async def with_timeout_async(
    coro,
    timeout_seconds: float,
    operation_name: str = "operation",
) -> Any:
    """Execute a coroutine with a timeout."""
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
    """Decorator to add timeout to async functions."""
    def decorator(func):
        @functools.wraps(func)
        async def wrapper_async(*args, **kwargs):
            name = operation_name or func.__name__
            return await with_timeout_async(
                func(*args, **kwargs),
                seconds,
                name,
            )
        return wrapper_async
    return decorator
