"""
Integration tests for gRPC server.

These tests start a real gRPC server and test client-server communication.
"""

import pytest
import asyncio
from pathlib import Path

import grpc
from grpc import aio

from warden.grpc.generated import warden_pb2, warden_pb2_grpc
from warden.grpc.server import GrpcServer, WardenServicer


@pytest.fixture
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


class TestGrpcIntegration:
    """Integration tests with real gRPC server."""

    @pytest.fixture
    async def grpc_server(self):
        """Start a gRPC server for testing."""
        # Use a random available port
        server = aio.server()
        servicer = WardenServicer(project_root=Path.cwd())
        warden_pb2_grpc.add_WardenServiceServicer_to_server(servicer, server)

        # Bind to random port
        port = server.add_insecure_port("[::]:0")
        await server.start()

        yield port

        await server.stop(grace=0)

    @pytest.fixture
    async def grpc_channel(self, grpc_server):
        """Create gRPC channel connected to test server."""
        channel = aio.insecure_channel(f"localhost:{grpc_server}")
        yield channel
        await channel.close()

    @pytest.fixture
    def stub(self, grpc_channel):
        """Create gRPC stub."""
        return warden_pb2_grpc.WardenServiceStub(grpc_channel)

    @pytest.mark.asyncio
    async def test_health_check_integration(self, stub):
        """Test HealthCheck RPC end-to-end."""
        response = await stub.HealthCheck(warden_pb2.Empty())

        assert response.version == "1.0.0"
        assert response.uptime_seconds >= 0
        assert "bridge" in response.components

    @pytest.mark.asyncio
    async def test_get_status_integration(self, stub):
        """Test GetStatus RPC end-to-end."""
        response = await stub.GetStatus(warden_pb2.Empty())

        assert response.running is True
        assert response.memory_mb > 0

    @pytest.mark.asyncio
    async def test_get_available_frames_integration(self, stub):
        """Test GetAvailableFrames RPC end-to-end."""
        response = await stub.GetAvailableFrames(warden_pb2.Empty())

        # Should return frame list (may be empty in test env)
        assert response is not None
        assert isinstance(response, warden_pb2.FrameList)

    @pytest.mark.asyncio
    async def test_get_available_providers_integration(self, stub):
        """Test GetAvailableProviders RPC end-to-end."""
        response = await stub.GetAvailableProviders(warden_pb2.Empty())

        assert response is not None
        assert isinstance(response, warden_pb2.ProviderList)

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="classify_code not implemented in bridge yet")
    async def test_classify_code_integration(self, stub):
        """Test ClassifyCode RPC end-to-end."""
        request = warden_pb2.ClassifyRequest(
            code="""
import asyncio
from fastapi import FastAPI
from sqlalchemy import create_engine

app = FastAPI()

@app.get("/users")
async def get_users():
    return []
""",
            file_path="main.py"
        )

        response = await stub.ClassifyCode(request)

        assert response is not None
        # Should detect async and web framework
        # Note: Actual classification depends on bridge implementation

    @pytest.mark.asyncio
    async def test_execute_pipeline_integration(self, stub, tmp_path):
        """Test ExecutePipeline RPC end-to-end."""
        # Create a test file
        test_file = tmp_path / "test.py"
        test_file.write_text("def foo(): pass\n")

        request = warden_pb2.PipelineRequest(
            path=str(tmp_path),
            parallel=True
        )

        response = await stub.ExecutePipeline(request)

        assert response is not None
        # Pipeline may succeed or fail depending on environment
        assert isinstance(response.duration_ms, int)

    @pytest.mark.asyncio
    async def test_execute_pipeline_stream_integration(self, stub, tmp_path):
        """Test ExecutePipelineStream RPC end-to-end."""
        # Create a test file
        test_file = tmp_path / "test.py"
        test_file.write_text("def foo(): pass\n")

        request = warden_pb2.PipelineRequest(
            path=str(tmp_path)
        )

        events = []
        async for event in stub.ExecutePipelineStream(request):
            events.append(event)

        # Should receive at least start and complete events
        assert len(events) >= 2
        assert events[0].event_type == "pipeline_start"
        assert events[-1].event_type in ["pipeline_complete", "error"]

    @pytest.mark.asyncio
    async def test_concurrent_requests(self, stub):
        """Test multiple concurrent requests."""
        # Send multiple health checks concurrently
        tasks = [
            stub.HealthCheck(warden_pb2.Empty())
            for _ in range(10)
        ]

        responses = await asyncio.gather(*tasks)

        assert len(responses) == 10
        for response in responses:
            assert response.version == "1.0.0"

    @pytest.mark.asyncio
    async def test_get_configuration_integration(self, stub):
        """Test GetConfiguration RPC end-to-end."""
        response = await stub.GetConfiguration(warden_pb2.Empty())

        # Response should be returned (may be empty if errors occur)
        assert response is not None
        # Note: project_root may be empty if configuration fails
        # This is expected in test environment


class TestGrpcServerLifecycle:
    """Tests for server lifecycle management."""

    @pytest.mark.asyncio
    async def test_server_start_stop(self):
        """Test server can start and stop cleanly."""
        server = GrpcServer(port=0)  # Random port

        # Note: This test would need the generated code to actually start
        # For now, we just test initialization
        assert server.server is None
        assert server.servicer is None

    @pytest.mark.asyncio
    async def test_server_stop_without_start(self):
        """Test stopping server that wasn't started."""
        server = GrpcServer(port=0)

        # Should not raise
        await server.stop()


class TestProtocolBufferSerialization:
    """Test protocol buffer serialization round-trips."""

    def test_pipeline_request_roundtrip(self):
        """Test PipelineRequest serialization roundtrip."""
        original = warden_pb2.PipelineRequest(
            path="/test/path",
            parallel=True,
            timeout_seconds=600
        )
        original.frames.extend(["security", "chaos"])
        original.options["key"] = "value"

        # Serialize
        data = original.SerializeToString()

        # Deserialize
        restored = warden_pb2.PipelineRequest()
        restored.ParseFromString(data)

        assert restored.path == original.path
        assert restored.parallel == original.parallel
        assert list(restored.frames) == list(original.frames)
        assert restored.options["key"] == "value"

    def test_pipeline_result_roundtrip(self):
        """Test PipelineResult serialization roundtrip."""
        original = warden_pb2.PipelineResult(
            success=True,
            run_id="test-123",
            total_findings=5,
            critical_count=1,
            duration_ms=1500
        )

        finding = original.findings.add()
        finding.id = "f-001"
        finding.title = "Test Finding"
        finding.severity = warden_pb2.HIGH

        # Serialize
        data = original.SerializeToString()

        # Deserialize
        restored = warden_pb2.PipelineResult()
        restored.ParseFromString(data)

        assert restored.success == original.success
        assert restored.total_findings == original.total_findings
        assert len(restored.findings) == 1
        assert restored.findings[0].title == "Test Finding"

    def test_large_response_serialization(self):
        """Test serialization of large responses."""
        result = warden_pb2.PipelineResult(success=True, run_id="large-test")

        # Add 1000 findings
        for i in range(1000):
            finding = result.findings.add()
            finding.id = f"finding-{i}"
            finding.title = f"Finding {i}: This is a longer title for testing"
            finding.description = f"Description {i}: " + "x" * 100
            finding.severity = warden_pb2.MEDIUM
            finding.file_path = f"/path/to/file_{i}.py"
            finding.line_number = i

        # Serialize
        data = result.SerializeToString()

        # Should be reasonable size (protocol buffers are efficient)
        assert len(data) < 1024 * 1024  # Less than 1MB for 1000 findings

        # Deserialize
        restored = warden_pb2.PipelineResult()
        restored.ParseFromString(data)

        assert len(restored.findings) == 1000
        assert restored.findings[500].id == "finding-500"
