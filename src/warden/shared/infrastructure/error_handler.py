"""Centralized async error handling decorator."""

import functools
from collections.abc import Callable
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class OperationTimeoutError(Exception):
    """An operation timed out."""

    pass


class ProviderUnavailableError(Exception):
    """LLM provider is unavailable."""

    pass


class ValidationError(Exception):
    """Validation frame execution failed."""

    pass


def async_error_handler(
    fallback_value: Any = None,
    log_level: str = "error",
    error_map: dict[type[Exception], type[Exception]] | None = None,
    context_keys: list[str] | None = None,
    reraise: bool = True,
):
    """
    Standardized async error handling decorator.

    Eliminates repetitive try/except patterns across async methods by providing
    consistent error logging, transformation, and recovery behavior.

    Args:
        fallback_value: Return this on error. If None and reraise=True, re-raises.
            Can be a callable that returns the fallback value.
        log_level: structlog level for error logging ("error", "warning", "info", "debug")
        error_map: Transform exceptions {SourceType: TargetType}
        context_keys: Extract these from kwargs for log context
        reraise: If True and no fallback_value, re-raise the exception

    Example:
        ```python
        @async_error_handler(
            fallback_value=[],
            log_level="warning",
            error_map={ConnectionError: ProviderUnavailableError},
            context_keys=["provider", "model"]
        )
        async def create_fast_clients(provider, model):
            # Implementation...
            pass
        ```

    Returns:
        Decorated async function with centralized error handling
    """

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            try:
                return await fn(*args, **kwargs)
            except Exception as e:
                # Map exception types if configured
                mapped = e
                if error_map and type(e) in error_map:
                    target_exception = error_map[type(e)]
                    mapped = target_exception(str(e))

                # Build log context from kwargs
                log_ctx = {}
                if context_keys:
                    for key in context_keys:
                        if key in kwargs:
                            log_ctx[key] = kwargs[key]

                # Log with context
                log_method = getattr(logger, log_level, logger.error)
                log_method(
                    f"{fn.__qualname__}_failed",
                    error=str(mapped),
                    error_type=type(mapped).__name__,
                    **log_ctx,
                )

                # Return fallback value or re-raise
                if fallback_value is not None:
                    if callable(fallback_value):
                        try:
                            return fallback_value()
                        except Exception as fallback_err:
                            logger.error(
                                f"{fn.__qualname__}_fallback_failed",
                                original_error=str(mapped),
                                fallback_error=str(fallback_err),
                            )
                            if reraise:
                                raise mapped from e
                            return None
                    return fallback_value
                if reraise:
                    raise mapped from e
                return None

        return wrapper

    return decorator
