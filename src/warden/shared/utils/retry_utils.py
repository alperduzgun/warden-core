import asyncio
import functools
import logging
import random
from collections.abc import Callable
from typing import Any, Tuple, Type

logger = logging.getLogger(__name__)


def async_retry(
    retries: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    backoff_factor: float = 2.0,
    jitter: bool = True,
    exceptions: tuple[type[Exception], ...] = (Exception,),
):
    # Fuzzing Guard: Ensure exceptions is a non-empty tuple
    if not exceptions:
        exceptions = (Exception,)
    """
    Decorator for async functions to implement exponential backoff with jitter.

    Args:
        retries: Maximum number of retries (default: 3)
        initial_delay: Initial delay in seconds (default: 1.0)
        max_delay: Maximum delay in seconds (default: 60.0)
        backoff_factor: Multiplier for delay (default: 2.0)
        jitter: Whether to add random jitter to delay (default: True)
        exceptions: Tuple of exceptions to catch and retry (default: Exception)
    """

    def decorator(func: Callable[..., Any]):
        @functools.wraps(func)
        async def wrapper_async(*args, **kwargs):
            delay = initial_delay
            last_exception = None

            for attempt in range(retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt == retries:
                        logger.error(f"Function {func.__name__} failed after {retries} retries. Error: {e}")
                        raise

                    # Calculate delay with backoff
                    current_delay = min(delay * (backoff_factor**attempt), max_delay)

                    if jitter:
                        # Add random jitter (±10% of current delay)
                        current_delay = current_delay * (1 + random.uniform(-0.1, 0.1))

                    logger.warning(
                        f"Retry attempt {attempt + 1}/{retries} for {func.__name__} "
                        f"failed with {type(e).__name__}: {e}. Retrying in {current_delay:.2f}s..."
                    )

                    await asyncio.sleep(current_delay)

            # This should technically not be reached due to re-raise above
            if last_exception:
                raise last_exception

        return wrapper_async

    return decorator
