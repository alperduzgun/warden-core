"""
Tests for centralized async error handler decorator.

Validates error handling, logging, transformation, and recovery behavior.
"""

import pytest
import asyncio
from typing import List
from warden.shared.infrastructure.error_handler import (
    async_error_handler,
    OperationTimeoutError,
    ProviderUnavailableError,
    ValidationError,
)


class TestAsyncErrorHandler:
    """Test suite for async_error_handler decorator."""

    @pytest.mark.asyncio
    async def test_successful_execution_passes_through(self):
        """Test that successful execution is not affected by decorator."""

        @async_error_handler()
        async def successful_function(value: int) -> int:
            return value * 2

        result = await successful_function(5)
        assert result == 10

    @pytest.mark.asyncio
    async def test_error_logs_and_reraises_by_default(self):
        """Test that errors are logged and re-raised by default."""

        @async_error_handler()
        async def failing_function():
            raise ValueError("Test error")

        with pytest.raises(ValueError, match="Test error"):
            await failing_function()

    @pytest.mark.asyncio
    async def test_fallback_value_returned_on_error(self):
        """Test that fallback value is returned when specified."""

        @async_error_handler(fallback_value=[])
        async def failing_function() -> List[str]:
            raise ValueError("Test error")

        result = await failing_function()
        assert result == []

    @pytest.mark.asyncio
    async def test_callable_fallback_value(self):
        """Test that callable fallback values are executed."""

        def get_fallback():
            return {"status": "error", "message": "fallback"}

        @async_error_handler(fallback_value=get_fallback)
        async def failing_function():
            raise ValueError("Test error")

        result = await failing_function()
        assert result == {"status": "error", "message": "fallback"}

    @pytest.mark.asyncio
    async def test_error_transformation(self):
        """Test that errors can be transformed via error_map."""

        @async_error_handler(
            error_map={ConnectionError: ProviderUnavailableError}
        )
        async def failing_function():
            raise ConnectionError("Network unreachable")

        with pytest.raises(ProviderUnavailableError, match="Network unreachable"):
            await failing_function()

    @pytest.mark.asyncio
    async def test_context_keys_extraction(self, caplog):
        """Test that context keys are extracted and logged."""

        @async_error_handler(
            context_keys=["provider", "model"],
            fallback_value=None,
            reraise=False
        )
        async def failing_function(provider: str, model: str):
            raise ValueError("Test error")

        result = await failing_function(provider="ollama", model="llama3")
        assert result is None
        # Note: Actual log verification would require structlog test setup

    @pytest.mark.asyncio
    async def test_log_level_warning(self, caplog):
        """Test that log level can be configured."""

        @async_error_handler(
            log_level="warning",
            fallback_value=None,
            reraise=False
        )
        async def failing_function():
            raise ValueError("Non-critical error")

        result = await failing_function()
        assert result is None

    @pytest.mark.asyncio
    async def test_reraise_false_returns_none(self):
        """Test that reraise=False returns None when no fallback."""

        @async_error_handler(reraise=False)
        async def failing_function():
            raise ValueError("Test error")

        result = await failing_function()
        assert result is None

    @pytest.mark.asyncio
    async def test_multiple_error_types_mapped(self):
        """Test that multiple error types can be mapped."""

        @async_error_handler(
            error_map={
                ConnectionError: ProviderUnavailableError,
                TimeoutError: OperationTimeoutError,
                ValueError: ValidationError,
            }
        )
        async def failing_with_timeout():
            raise TimeoutError("Operation took too long")

        with pytest.raises(OperationTimeoutError, match="Operation took too long"):
            await failing_with_timeout()

    @pytest.mark.asyncio
    async def test_preserves_function_metadata(self):
        """Test that decorator preserves function name and docstring."""

        @async_error_handler()
        async def documented_function():
            """This is a test function."""
            pass

        assert documented_function.__name__ == "documented_function"
        assert documented_function.__doc__ == "This is a test function."

    @pytest.mark.asyncio
    async def test_works_with_async_generators(self):
        """Test that decorator works with various async patterns."""

        @async_error_handler(fallback_value={"result": "fallback"})
        async def async_operation():
            await asyncio.sleep(0.01)
            raise ValueError("Async error")

        result = await async_operation()
        assert result == {"result": "fallback"}

    @pytest.mark.asyncio
    async def test_nested_decorators(self):
        """Test that multiple decorators can be stacked."""

        @async_error_handler(
            fallback_value="outer",
            reraise=False,
            log_level="debug"
        )
        @async_error_handler(
            fallback_value="inner",
            reraise=True  # Inner will try to re-raise
        )
        async def nested_function():
            raise ValueError("Test")

        # Inner decorator catches first and returns "inner" (since it has fallback_value)
        # Even though reraise=True, the fallback_value takes precedence
        result = await nested_function()
        assert result == "inner"

    @pytest.mark.asyncio
    async def test_custom_exception_types(self):
        """Test that custom exception types work correctly."""

        @async_error_handler()
        async def raise_provider_error():
            raise ProviderUnavailableError("Provider offline")

        with pytest.raises(ProviderUnavailableError, match="Provider offline"):
            await raise_provider_error()

        @async_error_handler()
        async def raise_validation_error():
            raise ValidationError("Invalid input")

        with pytest.raises(ValidationError, match="Invalid input"):
            await raise_validation_error()

    @pytest.mark.asyncio
    async def test_real_world_factory_pattern(self):
        """Test decorator in a real-world factory method pattern."""

        @async_error_handler(
            fallback_value=lambda: {"provider": "offline", "status": "fallback"},
            log_level="warning",
            error_map={ConnectionError: ProviderUnavailableError},
            context_keys=["provider_name"],
            reraise=False
        )
        async def create_provider_client(provider_name: str):
            # Simulate provider connection failure
            if provider_name == "unreachable":
                raise ConnectionError("Cannot reach provider")
            return {"provider": provider_name, "status": "connected"}

        # Success case
        result = await create_provider_client("openai")
        assert result == {"provider": "openai", "status": "connected"}

        # Failure case with fallback
        result = await create_provider_client("unreachable")
        assert result == {"provider": "offline", "status": "fallback"}

    @pytest.mark.asyncio
    async def test_real_world_frame_execution_pattern(self):
        """Test decorator in frame execution pattern."""

        @async_error_handler(
            fallback_value=None,
            log_level="error",
            context_keys=["frame_id", "file_path"],
            reraise=False
        )
        async def execute_frame(frame_id: str, file_path: str):
            if frame_id == "broken_frame":
                raise RuntimeError("Frame execution failed")
            return {"frame_id": frame_id, "status": "passed"}

        # Success case
        result = await execute_frame("security_frame", "/path/to/file.py")
        assert result == {"frame_id": "security_frame", "status": "passed"}

        # Failure case returns None (doesn't crash pipeline)
        result = await execute_frame("broken_frame", "/path/to/file.py")
        assert result is None


class TestCustomExceptions:
    """Test suite for custom exception types."""

    def test_operation_timeout_error(self):
        """Test OperationTimeoutError can be raised and caught."""
        with pytest.raises(OperationTimeoutError):
            raise OperationTimeoutError("Operation timed out after 30s")

    def test_provider_unavailable_error(self):
        """Test ProviderUnavailableError can be raised and caught."""
        with pytest.raises(ProviderUnavailableError):
            raise ProviderUnavailableError("Ollama is not running")

    def test_validation_error(self):
        """Test ValidationError can be raised and caught."""
        with pytest.raises(ValidationError):
            raise ValidationError("Frame validation failed")

    def test_exception_inheritance(self):
        """Test that custom exceptions inherit from Exception."""
        assert issubclass(OperationTimeoutError, Exception)
        assert issubclass(ProviderUnavailableError, Exception)
        assert issubclass(ValidationError, Exception)


class TestEdgeCases:
    """Test edge cases and corner scenarios."""

    @pytest.mark.asyncio
    async def test_none_error_map(self):
        """Test that None error_map doesn't cause issues."""

        @async_error_handler(error_map=None, fallback_value="fallback")
        async def failing_function():
            raise ValueError("Test")

        result = await failing_function()
        assert result == "fallback"

    @pytest.mark.asyncio
    async def test_empty_context_keys(self):
        """Test that empty context_keys list doesn't cause issues."""

        @async_error_handler(context_keys=[], fallback_value="fallback")
        async def failing_function():
            raise ValueError("Test")

        result = await failing_function()
        assert result == "fallback"

    @pytest.mark.asyncio
    async def test_missing_context_keys(self):
        """Test that missing context keys don't cause errors."""

        @async_error_handler(
            context_keys=["missing_key"],
            fallback_value="fallback",
            reraise=False
        )
        async def failing_function(existing_key: str):
            raise ValueError("Test")

        # Should not crash even though 'missing_key' is not in kwargs
        result = await failing_function(existing_key="value")
        assert result == "fallback"

    @pytest.mark.asyncio
    async def test_invalid_log_level_fallback(self):
        """Test that invalid log level falls back gracefully."""

        @async_error_handler(
            log_level="invalid_level",  # Invalid level
            fallback_value="fallback",
            reraise=False
        )
        async def failing_function():
            raise ValueError("Test")

        # Should use fallback logger.error and not crash
        result = await failing_function()
        assert result == "fallback"
