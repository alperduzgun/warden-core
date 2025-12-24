"""
Tests for Resilience Patterns (Polly-style).

Tests retry policy, circuit breaker, and resilience pipeline.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, Mock
from datetime import datetime, timedelta

from warden.shared.infrastructure.resilience import (
    RetryPolicy,
    RetryOptions,
    CircuitBreaker,
    CircuitBreakerOptions,
    CircuitState,
    ResiliencePipeline,
)


class TestRetryOptions:
    """Test RetryOptions configuration."""

    def test_default_options(self):
        """Test default retry options."""
        options = RetryOptions()

        assert options.max_attempts == 3
        assert options.initial_delay == 1.0
        assert options.use_exponential_backoff is True
        assert options.use_jitter is True
        assert options.max_delay == 30.0

    def test_custom_options(self):
        """Test custom retry options."""
        options = RetryOptions(
            max_attempts=5,
            initial_delay=2.0,
            use_exponential_backoff=False,
            use_jitter=False,
            max_delay=60.0,
        )

        assert options.max_attempts == 5
        assert options.initial_delay == 2.0
        assert options.use_exponential_backoff is False
        assert options.use_jitter is False
        assert options.max_delay == 60.0


class TestRetryPolicy:
    """Test RetryPolicy implementation."""

    @pytest.mark.asyncio
    async def test_successful_execution_no_retry(self):
        """Test successful execution without retries."""
        policy = RetryPolicy(RetryOptions(max_attempts=3))
        call_count = 0

        async def successful_func():
            nonlocal call_count
            call_count += 1
            return "success"

        result = await policy.execute(successful_func)

        assert result == "success"
        assert call_count == 1  # Only called once

    @pytest.mark.asyncio
    async def test_retry_on_failure_then_success(self):
        """Test retry on failure then success."""
        policy = RetryPolicy(
            RetryOptions(max_attempts=3, initial_delay=0.01, use_jitter=False)
        )
        call_count = 0

        async def flaky_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("Transient error")
            return "success"

        result = await policy.execute(flaky_func)

        assert result == "success"
        assert call_count == 3  # Failed 2 times, succeeded on 3rd

    @pytest.mark.asyncio
    async def test_retry_exhaustion(self):
        """Test all retries exhausted."""
        policy = RetryPolicy(
            RetryOptions(max_attempts=3, initial_delay=0.01, use_jitter=False)
        )
        call_count = 0

        async def always_fails():
            nonlocal call_count
            call_count += 1
            raise Exception("Permanent error")

        with pytest.raises(Exception, match="Permanent error"):
            await policy.execute(always_fails)

        assert call_count == 3  # All attempts used

    @pytest.mark.asyncio
    async def test_exponential_backoff_delay(self):
        """Test exponential backoff delay calculation."""
        policy = RetryPolicy(
            RetryOptions(
                max_attempts=4,
                initial_delay=1.0,
                use_exponential_backoff=True,
                use_jitter=False,
            )
        )

        # Calculate delays for attempts 0, 1, 2
        delay0 = policy._calculate_delay(0)  # 1.0 * 2^0 = 1.0
        delay1 = policy._calculate_delay(1)  # 1.0 * 2^1 = 2.0
        delay2 = policy._calculate_delay(2)  # 1.0 * 2^2 = 4.0

        assert delay0 == 1.0
        assert delay1 == 2.0
        assert delay2 == 4.0

    @pytest.mark.asyncio
    async def test_fixed_delay(self):
        """Test fixed delay (no exponential backoff)."""
        policy = RetryPolicy(
            RetryOptions(
                max_attempts=3,
                initial_delay=2.0,
                use_exponential_backoff=False,
                use_jitter=False,
            )
        )

        delay0 = policy._calculate_delay(0)
        delay1 = policy._calculate_delay(1)
        delay2 = policy._calculate_delay(2)

        assert delay0 == 2.0
        assert delay1 == 2.0
        assert delay2 == 2.0

    @pytest.mark.asyncio
    async def test_max_delay_cap(self):
        """Test max delay cap."""
        policy = RetryPolicy(
            RetryOptions(
                max_attempts=10,
                initial_delay=10.0,
                use_exponential_backoff=True,
                use_jitter=False,
                max_delay=30.0,
            )
        )

        # 10.0 * 2^5 = 320.0, should be capped at 30.0
        delay5 = policy._calculate_delay(5)

        assert delay5 == 30.0


class TestCircuitBreakerOptions:
    """Test CircuitBreakerOptions configuration."""

    def test_default_options(self):
        """Test default circuit breaker options."""
        options = CircuitBreakerOptions()

        assert options.failure_threshold == 0.7
        assert options.sampling_duration == 30.0
        assert options.minimum_throughput == 3
        assert options.break_duration == 60.0


class TestCircuitBreaker:
    """Test CircuitBreaker implementation."""

    @pytest.mark.asyncio
    async def test_initial_state_closed(self):
        """Test circuit breaker starts in CLOSED state."""
        cb = CircuitBreaker(CircuitBreakerOptions())

        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_successful_execution_stays_closed(self):
        """Test successful execution keeps circuit CLOSED."""
        cb = CircuitBreaker(CircuitBreakerOptions())

        async def success_func():
            return "success"

        result = await cb.execute(success_func)

        assert result == "success"
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_circuit_opens_on_high_failure_rate(self):
        """Test circuit opens when failure rate exceeds threshold."""
        cb = CircuitBreaker(
            CircuitBreakerOptions(
                failure_threshold=0.7, minimum_throughput=3, sampling_duration=10.0
            )
        )

        async def failing_func():
            raise Exception("Error")

        # Execute 4 failures to reach 100% failure rate (>= minimum throughput)
        for _ in range(4):
            try:
                await cb.execute(failing_func)
            except:
                pass

        # Circuit should now be OPEN (100% > 70%)
        assert cb.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_circuit_fails_fast_when_open(self):
        """Test circuit fails fast when OPEN."""
        cb = CircuitBreaker(CircuitBreakerOptions(minimum_throughput=2))

        # Force circuit to OPEN and set opened_at to prevent auto-reset
        cb.state = CircuitState.OPEN
        from datetime import datetime
        cb.opened_at = datetime.utcnow()  # Recent opening, won't reset yet

        async def func():
            return "should not execute"

        with pytest.raises(Exception, match="Circuit breaker is OPEN"):
            await cb.execute(func)

    @pytest.mark.asyncio
    async def test_circuit_attempts_reset_after_break_duration(self):
        """Test circuit attempts reset (HALF_OPEN) after break duration."""
        cb = CircuitBreaker(
            CircuitBreakerOptions(break_duration=0.1)  # 100ms break
        )

        # Force circuit OPEN and set opened_at to past
        cb.state = CircuitState.OPEN
        cb.opened_at = datetime.utcnow() - timedelta(seconds=1)

        async def success_func():
            return "success"

        # Should transition to HALF_OPEN, then CLOSED
        result = await cb.execute(success_func)

        assert result == "success"
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_half_open_failure_reopens_circuit(self):
        """Test HALF_OPEN failure reopens circuit."""
        cb = CircuitBreaker(CircuitBreakerOptions())

        # Force circuit to HALF_OPEN
        cb.state = CircuitState.HALF_OPEN

        async def failing_func():
            raise Exception("Test failed")

        with pytest.raises(Exception):
            await cb.execute(failing_func)

        # Circuit should reopen
        assert cb.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_failure_ratio_calculation(self):
        """Test failure ratio calculation."""
        cb = CircuitBreaker(CircuitBreakerOptions())

        async def success():
            return "ok"

        async def failure():
            raise Exception("fail")

        # 2 successes, 1 failure = 33% failure rate
        await cb.execute(success)
        await cb.execute(success)
        try:
            await cb.execute(failure)
        except:
            pass

        ratio = cb._get_failure_ratio()
        assert abs(ratio - 0.333) < 0.01  # ~33%

    @pytest.mark.asyncio
    async def test_minimum_throughput_threshold(self):
        """Test circuit doesn't open below minimum throughput."""
        cb = CircuitBreaker(
            CircuitBreakerOptions(failure_threshold=0.5, minimum_throughput=5)
        )

        async def failure():
            raise Exception("fail")

        # Execute 3 failures (below minimum throughput of 5)
        for _ in range(3):
            try:
                await cb.execute(failure)
            except:
                pass

        # Circuit should stay CLOSED (not enough throughput)
        assert cb.state == CircuitState.CLOSED


class TestResiliencePipeline:
    """Test ResiliencePipeline (combined retry + circuit breaker)."""

    @pytest.mark.asyncio
    async def test_successful_execution(self):
        """Test successful execution through pipeline."""
        pipeline = ResiliencePipeline(
            retry_options=RetryOptions(max_attempts=3),
            circuit_breaker_options=CircuitBreakerOptions(),
        )

        async def success_func():
            return "success"

        result = await pipeline.execute(success_func)

        assert result == "success"

    @pytest.mark.asyncio
    async def test_retry_then_success(self):
        """Test retry mechanism in pipeline."""
        pipeline = ResiliencePipeline(
            retry_options=RetryOptions(
                max_attempts=3, initial_delay=0.01, use_jitter=False
            ),
            circuit_breaker_options=None,  # No circuit breaker
        )

        call_count = 0

        async def flaky_func():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise Exception("Transient")
            return "success"

        result = await pipeline.execute(flaky_func)

        assert result == "success"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_circuit_breaker_in_pipeline(self):
        """Test circuit breaker in pipeline."""
        pipeline = ResiliencePipeline(
            retry_options=None,  # No retry
            circuit_breaker_options=CircuitBreakerOptions(minimum_throughput=1),
        )

        # Force circuit breaker open and set opened_at to prevent auto-reset
        from datetime import datetime
        pipeline.circuit_breaker.state = CircuitState.OPEN
        pipeline.circuit_breaker.opened_at = datetime.utcnow()

        async def func():
            return "should not execute"

        with pytest.raises(Exception, match="Circuit breaker is OPEN"):
            await pipeline.execute(func)

    @pytest.mark.asyncio
    async def test_pipeline_without_resilience(self):
        """Test pipeline without retry or circuit breaker."""
        pipeline = ResiliencePipeline(
            retry_options=RetryOptions(max_attempts=1),  # No retries
            circuit_breaker_options=None,  # No circuit breaker
        )

        async def failing_func():
            raise Exception("Error")

        with pytest.raises(Exception, match="Error"):
            await pipeline.execute(failing_func)


class TestIntegrationScenarios:
    """Test realistic integration scenarios."""

    @pytest.mark.asyncio
    async def test_flaky_llm_service_scenario(self):
        """Test handling flaky LLM service with retry."""
        pipeline = ResiliencePipeline(
            retry_options=RetryOptions(
                max_attempts=3, initial_delay=0.01, use_jitter=False
            ),
            circuit_breaker_options=CircuitBreakerOptions(minimum_throughput=5),
        )

        call_count = 0
        success_threshold = 2

        async def llm_service_call():
            nonlocal call_count
            call_count += 1

            # Simulate transient failures (rate limiting, network issues)
            if call_count < success_threshold:
                raise Exception("LLM service unavailable")

            return {"result": "SQL injection detected"}

        result = await pipeline.execute(llm_service_call)

        assert result["result"] == "SQL injection detected"
        assert call_count == success_threshold

    @pytest.mark.asyncio
    async def test_cascading_failure_prevention(self):
        """Test circuit breaker prevents cascading failures."""
        pipeline = ResiliencePipeline(
            retry_options=RetryOptions(max_attempts=2, initial_delay=0.01),
            circuit_breaker_options=CircuitBreakerOptions(
                failure_threshold=0.7, minimum_throughput=3, sampling_duration=10.0
            ),
        )

        async def degraded_service():
            raise Exception("Service degraded")

        # Execute multiple failing requests to open circuit
        fail_count = 0
        for _ in range(5):
            try:
                await pipeline.execute(degraded_service)
            except:
                fail_count += 1

        # Circuit should open, preventing more calls
        assert pipeline.circuit_breaker.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_recovery_after_circuit_breaker_opens(self):
        """Test service recovery after circuit breaker opens."""
        pipeline = ResiliencePipeline(
            retry_options=RetryOptions(max_attempts=1),
            circuit_breaker_options=CircuitBreakerOptions(break_duration=0.1),
        )

        # Force circuit OPEN and set it to recover
        pipeline.circuit_breaker.state = CircuitState.OPEN
        pipeline.circuit_breaker.opened_at = datetime.utcnow() - timedelta(seconds=1)

        async def recovered_service():
            return "Service recovered"

        # Should allow test (HALF_OPEN), then close circuit
        result = await pipeline.execute(recovered_service)

        assert result == "Service recovered"
        assert pipeline.circuit_breaker.state == CircuitState.CLOSED


class TestTimeoutInteractions:
    """Test timeout interaction with retry and circuit breaker."""

    @pytest.mark.asyncio
    async def test_retry_policy_with_timeout(self):
        """Test retry policy respects timeout."""
        policy = RetryPolicy(
            RetryOptions(max_attempts=3, initial_delay=0.1, use_jitter=False)
        )

        async def slow_function():
            await asyncio.sleep(5)  # Exceeds timeout
            return "success"

        # Should timeout before all retries complete
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(policy.execute(slow_function), timeout=1.0)

    @pytest.mark.asyncio
    async def test_circuit_breaker_with_timeout(self):
        """Test circuit breaker handles timeout correctly when timeout happens inside function."""
        cb = CircuitBreaker(CircuitBreakerOptions(minimum_throughput=1))

        async def timeout_func():
            # Timeout exception raised inside function
            raise asyncio.TimeoutError("Operation timed out")

        # Execute - TimeoutError should count as failure
        try:
            await cb.execute(timeout_func)
        except asyncio.TimeoutError:
            pass

        # Circuit breaker should track timeout as failure
        assert len(cb.failures) > 0
        assert cb.metrics["total_failures"] == 1

    @pytest.mark.asyncio
    async def test_resilience_pipeline_with_timeout(self):
        """Test full resilience pipeline with timeout exception inside function."""
        pipeline = ResiliencePipeline(
            retry_options=RetryOptions(max_attempts=2, initial_delay=0.05),
            circuit_breaker_options=CircuitBreakerOptions(minimum_throughput=5),  # Higher to avoid circuit opening on first failure
        )

        async def slow_service():
            # Raise timeout error from inside function
            raise asyncio.TimeoutError("Service timeout")

        # Pipeline should handle timeout as failure
        with pytest.raises(asyncio.TimeoutError):
            await pipeline.execute(slow_service)

        # Failures should be recorded (2 attempts due to retry)
        assert pipeline.circuit_breaker.metrics["total_failures"] == 2
        assert pipeline.circuit_breaker.metrics["total_requests"] == 2
        # Circuit should stay CLOSED (not enough throughput to trigger opening)
        assert pipeline.circuit_breaker.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_timeout_does_not_trigger_circuit_breaker_prematurely(self):
        """Test timeout doesn't incorrectly open circuit breaker."""
        cb = CircuitBreaker(
            CircuitBreakerOptions(
                failure_threshold=0.7,
                minimum_throughput=3,
                sampling_duration=10.0,
            )
        )

        async def fast_success():
            return "success"

        async def slow_timeout():
            await asyncio.sleep(5)
            return "timeout"

        # Execute 2 successful calls
        await cb.execute(fast_success)
        await cb.execute(fast_success)

        # Execute 1 timeout (should count as failure)
        try:
            await asyncio.wait_for(cb.execute(slow_timeout), timeout=0.1)
        except asyncio.TimeoutError:
            pass

        # Circuit should stay CLOSED (2 success, 1 failure = 33% failure rate < 70%)
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_circuit_breaker_metrics_with_timeouts(self):
        """Test circuit breaker metrics track timeouts correctly."""
        cb = CircuitBreaker(CircuitBreakerOptions())

        async def timeout_func():
            # Raise timeout from inside function
            raise asyncio.TimeoutError("Operation timed out")

        # Execute 3 timeouts
        timeout_count = 0
        for _ in range(3):
            try:
                await cb.execute(timeout_func)
            except asyncio.TimeoutError:
                timeout_count += 1

        # Metrics should show 3 requests and 3 failures
        metrics = cb.get_metrics()
        assert metrics["total_requests"] == 3
        assert metrics["total_failures"] == 3
        assert timeout_count == 3
