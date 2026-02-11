"""
Resilience Patterns for Warden.

Provides common fault-tolerance patterns:
- Timeout
- Retry
- Circuit Breaker
- Bulkhead
- Resilient Operation
"""

from .bulkhead import Bulkhead, BulkheadConfig, BulkheadFull
from .circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerOpen,
    CircuitState,
    circuit_breaker,
)
from .combined import ResilienceConfig, ResilientOperation, resilient
from .retry import RetryConfig, RetryExhausted, retry, with_retry_async
from .timeout import OperationTimeoutError, TimeoutError, timeout, with_timeout_async

# Backwards compatibility aliases (these are async functions)
# NOTE: Prefer using with_timeout_async/with_retry_async directly for clarity
with_timeout = with_timeout_async
with_retry = with_retry_async

__all__ = [
    "OperationTimeoutError",
    "TimeoutError",  # Deprecated alias for backwards compatibility
    "with_timeout_async",
    "with_timeout",
    "timeout",
    "RetryConfig",
    "RetryExhausted",
    "with_retry_async",
    "with_retry",
    "retry",
    "CircuitState",
    "CircuitBreakerConfig",
    "CircuitBreakerOpen",
    "CircuitBreaker",
    "circuit_breaker",
    "BulkheadConfig",
    "BulkheadFull",
    "Bulkhead",
    "ResilienceConfig",
    "ResilientOperation",
    "resilient",
]
