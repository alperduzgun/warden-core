"""
Chaos Engineering Tests for gRPC Server.

Tests edge cases, failure modes, and resilience:
- Invalid inputs
- Malformed requests
- Large payloads
- Timeout scenarios
- Resource exhaustion
- Concurrent stress
"""

import pytest
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from warden.grpc.generated import warden_pb2, warden_pb2_grpc
from warden.grpc.server import WardenServicer, GrpcServer


class TestChaosInvalidInputs:
    """Test server resilience to invalid inputs."""

    @pytest.fixture
    def servicer(self):
        """Create servicer with mocked bridge."""
        mock_bridge = MagicMock()
        mock_bridge.project_root = Path.cwd()
        mock_bridge.orchestrator = MagicMock()
        return WardenServicer(bridge=mock_bridge)

    @pytest.mark.asyncio
    async def test_empty_path_pipeline(self, servicer):
        """Pipeline with empty path should handle gracefully."""
        servicer.bridge.execute_pipeline = AsyncMock(return_value={
            "success": False,
            "error": "Path cannot be empty"
        })

        request = warden_pb2.PipelineRequest(path="")
        context = MagicMock()

        response = await servicer.ExecutePipeline(request, context)

        assert response.success is False
        assert "empty" in response.error_message.lower() or response.error_message

    @pytest.mark.asyncio
    async def test_invalid_path_traversal(self, servicer):
        """Path traversal attempt should be rejected."""
        servicer.bridge.execute_pipeline = AsyncMock(return_value={
            "success": False,
            "error": "Invalid path"
        })

        request = warden_pb2.PipelineRequest(path="../../../etc/passwd")
        context = MagicMock()

        response = await servicer.ExecutePipeline(request, context)

        # Should not succeed with path traversal
        assert response.success is False

    @pytest.mark.asyncio
    async def test_nonexistent_frame(self, servicer):
        """Request with nonexistent frame should handle gracefully."""
        servicer.bridge.execute_pipeline = AsyncMock(return_value={
            "success": False,
            "error": "Unknown frame: nonexistent_frame"
        })

        request = warden_pb2.PipelineRequest(
            path="./src",
            frames=["nonexistent_frame"]
        )
        context = MagicMock()

        response = await servicer.ExecutePipeline(request, context)

        assert response.success is False

    @pytest.mark.asyncio
    async def test_null_code_analysis(self, servicer):
        """LLM analysis with empty code should handle gracefully."""
        servicer.bridge.analyze_with_llm = AsyncMock(side_effect=ValueError("Code cannot be empty"))

        request = warden_pb2.LlmAnalyzeRequest(code="", prompt="Review this")
        context = MagicMock()

        response = await servicer.AnalyzeWithLlm(request, context)

        assert response.success is False
        assert response.error.code == "LLM_ERROR"

    @pytest.mark.asyncio
    async def test_empty_prompt_analysis(self, servicer):
        """LLM analysis with empty prompt should handle gracefully."""
        servicer.bridge.analyze_with_llm = AsyncMock(side_effect=ValueError("Prompt cannot be empty"))

        request = warden_pb2.LlmAnalyzeRequest(code="def foo(): pass", prompt="")
        context = MagicMock()

        response = await servicer.AnalyzeWithLlm(request, context)

        assert response.success is False


class TestChaosMalformedRequests:
    """Test server resilience to malformed requests."""

    @pytest.fixture
    def servicer(self):
        mock_bridge = MagicMock()
        mock_bridge.project_root = Path.cwd()
        mock_bridge.orchestrator = MagicMock()
        return WardenServicer(bridge=mock_bridge)

    @pytest.mark.asyncio
    async def test_unicode_in_path(self, servicer):
        """Unicode characters in path should be handled."""
        servicer.bridge.execute_pipeline = AsyncMock(return_value={
            "success": True,
            "run_id": "test-123",
            "total_findings": 0,
            "findings": []
        })

        request = warden_pb2.PipelineRequest(path="./src/日本語/файл.py")
        context = MagicMock()

        response = await servicer.ExecutePipeline(request, context)

        # Should handle unicode gracefully (success or proper error)
        assert response is not None

    @pytest.mark.asyncio
    async def test_special_chars_in_code(self, servicer):
        """Special characters in code should be handled."""
        code_with_specials = """
def foo():
    # 日本語コメント
    x = "αβγδ"
    y = "🔒🔑💣"
    return x + y
"""
        servicer.bridge.classify_code = AsyncMock(return_value={
            "has_async_operations": False,
            "recommended_frames": []
        })

        request = warden_pb2.ClassifyRequest(code=code_with_specials, file_path="test.py")
        context = MagicMock()

        response = await servicer.ClassifyCode(request, context)

        assert response is not None

    @pytest.mark.asyncio
    async def test_very_long_path(self, servicer):
        """Very long path should be handled."""
        long_path = "/a" * 5000  # 5000 char path
        servicer.bridge.execute_pipeline = AsyncMock(return_value={
            "success": False,
            "error": "Path too long"
        })

        request = warden_pb2.PipelineRequest(path=long_path)
        context = MagicMock()

        response = await servicer.ExecutePipeline(request, context)

        # Should not crash
        assert response is not None


class TestChaosLargePayloads:
    """Test server resilience to large payloads."""

    @pytest.fixture
    def servicer(self):
        mock_bridge = MagicMock()
        mock_bridge.project_root = Path.cwd()
        mock_bridge.orchestrator = MagicMock()
        return WardenServicer(bridge=mock_bridge)

    @pytest.mark.asyncio
    async def test_large_code_analysis(self, servicer):
        """Large code payload should be handled."""
        large_code = "x = 1\n" * 100000  # 100k lines

        async def mock_analyze(*args, **kwargs):
            yield {"type": "chunk", "content": "Analysis: "}
            yield {"type": "complete", "provider": "mock"}

        servicer.bridge.analyze_with_llm = mock_analyze

        request = warden_pb2.LlmAnalyzeRequest(
            code=large_code,
            prompt="Review this"
        )
        context = MagicMock()

        response = await servicer.AnalyzeWithLlm(request, context)

        assert response is not None

    @pytest.mark.asyncio
    async def test_many_findings_response(self, servicer):
        """Response with many findings should be handled."""
        findings = [
            {
                "id": f"finding-{i}",
                "title": f"Finding {i}",
                "description": "Description " * 10,
                "severity": "medium",
                "file_path": f"/path/file_{i}.py",
                "line_number": i
            }
            for i in range(10000)  # 10k findings
        ]

        servicer.bridge.execute_pipeline = AsyncMock(return_value={
            "success": True,
            "run_id": "test-large",
            "total_findings": len(findings),
            "findings": findings
        })

        request = warden_pb2.PipelineRequest(path="./src")
        context = MagicMock()

        response = await servicer.ExecutePipeline(request, context)

        assert response.total_findings == 10000
        assert len(response.findings) == 10000

    @pytest.mark.asyncio
    async def test_many_frames_request(self, servicer):
        """Request with many frames should be handled."""
        servicer.bridge.execute_pipeline = AsyncMock(return_value={
            "success": True,
            "run_id": "test",
            "findings": []
        })

        many_frames = [f"frame_{i}" for i in range(100)]
        request = warden_pb2.PipelineRequest(path="./src")
        request.frames.extend(many_frames)
        context = MagicMock()

        response = await servicer.ExecutePipeline(request, context)

        assert response is not None


class TestChaosTimeouts:
    """Test server timeout handling."""

    @pytest.fixture
    def servicer(self):
        mock_bridge = MagicMock()
        mock_bridge.project_root = Path.cwd()
        mock_bridge.orchestrator = MagicMock()
        return WardenServicer(bridge=mock_bridge)

    @pytest.mark.asyncio
    async def test_slow_pipeline_execution(self, servicer):
        """Slow pipeline should not block indefinitely."""
        async def slow_execute(*args, **kwargs):
            await asyncio.sleep(0.1)  # Simulated delay
            return {
                "success": True,
                "run_id": "slow",
                "findings": []
            }

        servicer.bridge.execute_pipeline = slow_execute

        request = warden_pb2.PipelineRequest(path="./src")
        context = MagicMock()

        response = await asyncio.wait_for(
            servicer.ExecutePipeline(request, context),
            timeout=5.0
        )

        assert response.success is True

    @pytest.mark.asyncio
    async def test_streaming_timeout(self, servicer):
        """Streaming should handle slow events."""
        async def slow_stream(*args, **kwargs):
            yield {"type": "start", "message": "Starting"}
            await asyncio.sleep(0.05)
            yield {"type": "progress", "progress": 0.5}
            await asyncio.sleep(0.05)
            yield {"type": "complete", "progress": 1.0}

        servicer.bridge.execute_pipeline_stream = slow_stream

        request = warden_pb2.PipelineRequest(path="./src")
        context = MagicMock()

        events = []
        async for event in servicer.ExecutePipelineStream(request, context):
            events.append(event)

        assert len(events) >= 2


class TestChaosResourceExhaustion:
    """Test server behavior under resource pressure."""

    @pytest.fixture
    def servicer(self):
        mock_bridge = MagicMock()
        mock_bridge.project_root = Path.cwd()
        mock_bridge.orchestrator = MagicMock()
        return WardenServicer(bridge=mock_bridge)

    @pytest.mark.asyncio
    async def test_memory_error_handling(self, servicer):
        """Memory error should be handled gracefully."""
        servicer.bridge.execute_pipeline = AsyncMock(side_effect=MemoryError("Out of memory"))

        request = warden_pb2.PipelineRequest(path="./src")
        context = MagicMock()

        response = await servicer.ExecutePipeline(request, context)

        assert response.success is False
        assert "memory" in response.error_message.lower() or response.error_message

    @pytest.mark.asyncio
    async def test_os_error_handling(self, servicer):
        """OS error should be handled gracefully."""
        servicer.bridge.execute_pipeline = AsyncMock(side_effect=OSError("Too many open files"))

        request = warden_pb2.PipelineRequest(path="./src")
        context = MagicMock()

        response = await servicer.ExecutePipeline(request, context)

        assert response.success is False


class TestChaosConcurrency:
    """Test server under concurrent load."""

    @pytest.fixture
    def servicer(self):
        mock_bridge = MagicMock()
        mock_bridge.project_root = Path.cwd()
        mock_bridge.orchestrator = MagicMock()
        mock_bridge.get_available_providers = AsyncMock(return_value=[])
        return WardenServicer(bridge=mock_bridge)

    @pytest.mark.asyncio
    async def test_concurrent_health_checks(self, servicer):
        """Many concurrent health checks should be handled."""
        async def health_check():
            return await servicer.HealthCheck(warden_pb2.Empty(), MagicMock())

        # Run 50 concurrent health checks
        tasks = [health_check() for _ in range(50)]
        responses = await asyncio.gather(*tasks)

        assert len(responses) == 50
        assert all(r.version == "1.0.0" for r in responses)

    @pytest.mark.asyncio
    async def test_concurrent_mixed_requests(self, servicer):
        """Mixed concurrent requests should be handled."""
        servicer.bridge.execute_pipeline = AsyncMock(return_value={
            "success": True,
            "run_id": "test",
            "findings": []
        })
        servicer.bridge.get_available_frames = AsyncMock(return_value=[])

        async def run_health():
            return await servicer.HealthCheck(warden_pb2.Empty(), MagicMock())

        async def run_status():
            return await servicer.GetStatus(warden_pb2.Empty(), MagicMock())

        async def run_frames():
            return await servicer.GetAvailableFrames(warden_pb2.Empty(), MagicMock())

        # Mix of different request types
        tasks = [
            run_health(), run_status(), run_frames(),
            run_health(), run_status(), run_frames(),
            run_health(), run_status(), run_frames(),
            run_health(), run_status(), run_frames(),
        ]

        responses = await asyncio.gather(*tasks)

        assert len(responses) == 12


class TestChaosErrorRecovery:
    """Test server error recovery and resilience."""

    @pytest.fixture
    def servicer(self):
        mock_bridge = MagicMock()
        mock_bridge.project_root = Path.cwd()
        mock_bridge.orchestrator = MagicMock()
        mock_bridge.get_available_providers = AsyncMock(return_value=[])
        return WardenServicer(bridge=mock_bridge)

    @pytest.mark.asyncio
    async def test_recovery_after_error(self, servicer):
        """Server should recover after an error."""
        call_count = 0

        async def sometimes_fails(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("First call fails")
            return {"success": True, "run_id": "test", "findings": []}

        servicer.bridge.execute_pipeline = sometimes_fails

        request = warden_pb2.PipelineRequest(path="./src")
        context = MagicMock()

        # First call should fail
        response1 = await servicer.ExecutePipeline(request, context)
        assert response1.success is False

        # Second call should succeed
        response2 = await servicer.ExecutePipeline(request, context)
        assert response2.success is True

    @pytest.mark.asyncio
    async def test_exception_in_stream(self, servicer):
        """Exception during streaming should be handled."""
        async def failing_stream(*args, **kwargs):
            yield {"type": "start", "message": "Starting"}
            raise Exception("Stream error")

        servicer.bridge.execute_pipeline_stream = failing_stream

        request = warden_pb2.PipelineRequest(path="./src")
        context = MagicMock()

        events = []
        async for event in servicer.ExecutePipelineStream(request, context):
            events.append(event)

        # Should have start event and error event
        assert len(events) >= 1
        assert events[-1].event_type == "error"


class TestChaosIdempotency:
    """Test idempotency of operations."""

    @pytest.fixture
    def servicer(self):
        mock_bridge = MagicMock()
        mock_bridge.project_root = Path.cwd()
        mock_bridge.orchestrator = MagicMock()
        mock_bridge.get_available_providers = AsyncMock(return_value=[])
        return WardenServicer(bridge=mock_bridge)

    @pytest.mark.asyncio
    async def test_health_check_idempotent(self, servicer):
        """Health check should be idempotent."""
        context = MagicMock()

        responses = []
        for _ in range(5):
            response = await servicer.HealthCheck(warden_pb2.Empty(), context)
            responses.append(response)

        # All responses should be consistent
        assert all(r.version == responses[0].version for r in responses)

    @pytest.mark.asyncio
    async def test_get_frames_idempotent(self, servicer):
        """GetAvailableFrames should be idempotent."""
        servicer.bridge.get_available_frames = AsyncMock(return_value=[
            {"id": "security", "name": "Security", "enabled": True}
        ])
        context = MagicMock()

        responses = []
        for _ in range(5):
            response = await servicer.GetAvailableFrames(warden_pb2.Empty(), context)
            responses.append(response)

        # All responses should have same frames
        assert all(len(r.frames) == 1 for r in responses)
        assert all(r.frames[0].id == "security" for r in responses)
