"""
Resilience Patterns for Warden.

Provides common fault-tolerance patterns:
- Timeout
- Retry
- Circuit Breaker
- Bulkhead
- Resilient Operation
"""

from .timeout import TimeoutError, with_timeout_async, timeout

# Alias for backwards compatibility
with_timeout = with_timeout_async

from .retry import RetryConfig, RetryExhausted, with_retry_async, retry

# Alias for backwards compatibility
with_retry = with_retry_async
from .circuit_breaker import (
    CircuitState,
    CircuitBreakerConfig,
    CircuitBreakerOpen,
    CircuitBreaker,
    circuit_breaker,
)
from .bulkhead import BulkheadConfig, BulkheadFull, Bulkhead
from .combined import ResilienceConfig, ResilientOperation, resilient

__all__ = [
    "TimeoutError",
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
