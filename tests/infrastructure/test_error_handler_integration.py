"""
Integration tests for error handler decorator with real Warden components.

Validates that the decorator works correctly in production scenarios.
"""

import pytest
from pathlib import Path
from warden.llm.factory import create_client_with_fallback_async
from warden.llm.config import LlmConfiguration
from warden.llm.types import LlmProvider
from warden.shared.infrastructure.error_handler import (
    async_error_handler,
    ProviderUnavailableError,
)


class TestErrorHandlerIntegration:
    """Integration tests with real Warden components."""

    @pytest.mark.asyncio
    async def test_llm_factory_fallback_on_no_providers(self):
        """Test that LLM factory falls back to OfflineClient gracefully."""
        # Create a config with no valid providers
        config = LlmConfiguration(
            default_provider=LlmProvider.ANTHROPIC,
            fallback_providers=[]
        )
        # Disable anthropic provider
        config.anthropic.enabled = False
        config.anthropic.api_key = None

        # Should return OfflineClient instead of crashing
        client = await create_client_with_fallback_async(config)

        assert client is not None
        # OfflineClient is returned as fallback
        assert client.__class__.__name__ == "OfflineClient"

    @pytest.mark.asyncio
    async def test_decorator_with_real_async_operation(self):
        """Test decorator with a real async operation."""

        @async_error_handler(
            fallback_value={"status": "fallback", "result": None},
            log_level="warning",
            reraise=False
        )
        async def risky_operation():
            # Simulate a failing operation
            raise ConnectionError("Service unavailable")

        result = await risky_operation()

        assert result == {"status": "fallback", "result": None}

    @pytest.mark.asyncio
    async def test_decorator_preserves_success_path(self):
        """Test that decorator doesn't interfere with successful operations."""

        @async_error_handler(
            fallback_value={"status": "error"},
            log_level="error"
        )
        async def successful_operation(value: int):
            return {"status": "success", "value": value * 2}

        result = await successful_operation(5)

        assert result == {"status": "success", "value": 10}

    @pytest.mark.asyncio
    async def test_decorator_with_context_logging(self):
        """Test that decorator logs context correctly."""

        @async_error_handler(
            fallback_value=None,
            log_level="warning",
            context_keys=["operation", "file_path"],
            reraise=False
        )
        async def failing_operation(operation: str, file_path: str):
            raise ValueError(f"Failed to {operation} {file_path}")

        result = await failing_operation(
            operation="validate",
            file_path="/path/to/file.py"
        )

        assert result is None  # Fallback value

    @pytest.mark.asyncio
    async def test_decorator_error_transformation(self):
        """Test that decorator transforms errors correctly."""

        @async_error_handler(
            error_map={ConnectionError: ProviderUnavailableError},
            reraise=True
        )
        async def network_operation():
            raise ConnectionError("Cannot reach server")

        with pytest.raises(ProviderUnavailableError, match="Cannot reach server"):
            await network_operation()


class TestRealWorldScenarios:
    """Test real-world usage patterns."""

    @pytest.mark.asyncio
    async def test_frame_executor_pattern(self):
        """Simulate frame executor error handling."""

        @async_error_handler(
            fallback_value=None,
            log_level="error",
            context_keys=["frame_id", "file"],
            reraise=False
        )
        async def execute_frame(frame_id: str, file: str):
            if frame_id == "broken":
                raise RuntimeError("Frame execution failed")
            return {"frame_id": frame_id, "status": "passed"}

        # Success case
        result = await execute_frame("security", "test.py")
        assert result["status"] == "passed"

        # Failure case - returns None, doesn't crash
        result = await execute_frame("broken", "test.py")
        assert result is None

    @pytest.mark.asyncio
    async def test_verification_phase_pattern(self):
        """Simulate verification phase error handling."""

        @async_error_handler(
            fallback_value=None,
            log_level="warning",
            context_keys=["pipeline_id"],
            reraise=False
        )
        async def verify_findings(pipeline_id: str, findings: list):
            if not findings:
                return findings
            # Simulate LLM verification failure
            raise TimeoutError("LLM service timeout")

        # Should return None on failure, not crash
        result = await verify_findings(
            pipeline_id="test-123",
            findings=[{"id": "1", "severity": "high"}]
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_cleanup_on_error(self):
        """Test that cleanup happens even when errors occur."""
        cleanup_called = []

        @async_error_handler(
            fallback_value=None,
            reraise=False
        )
        async def operation_with_cleanup():
            try:
                raise ValueError("Operation failed")
            finally:
                cleanup_called.append(True)

        result = await operation_with_cleanup()

        assert result is None
        assert len(cleanup_called) == 1  # Cleanup was called
