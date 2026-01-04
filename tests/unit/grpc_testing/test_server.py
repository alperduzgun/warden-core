"""
Tests for gRPC server implementation.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from warden.grpc.generated import warden_pb2
from warden.grpc.server import WardenServicer, GrpcServer


class TestWardenServicer:
    """Tests for WardenServicer class."""

    @pytest.fixture
    def mock_bridge(self):
        """Create mock WardenBridge."""
        bridge = MagicMock()
        bridge.project_root = Path("/test/project")
        bridge.orchestrator = MagicMock()
        return bridge

    @pytest.fixture
    def servicer(self, mock_bridge):
        """Create servicer with mock bridge."""
        return WardenServicer(bridge=mock_bridge)

    def test_servicer_initialization(self, servicer, mock_bridge):
        """Test servicer initializes correctly."""
        assert servicer.bridge == mock_bridge
        assert servicer.total_scans == 0
        assert servicer.total_findings == 0
        assert servicer.start_time is not None

    @pytest.mark.asyncio
    async def test_health_check(self, servicer, mock_bridge):
        """Test HealthCheck RPC."""
        mock_bridge.get_available_providers = AsyncMock(return_value={
            "providers": [{"available": True}]
        })

        context = MagicMock()
        response = await servicer.HealthCheck(warden_pb2.Empty(), context)

        assert response.healthy is True
        assert response.version == "1.0.0"
        assert response.uptime_seconds >= 0
        assert "bridge" in response.components

    @pytest.mark.asyncio
    async def test_health_check_unhealthy(self, servicer, mock_bridge):
        """Test HealthCheck when components fail."""
        mock_bridge.get_available_providers = AsyncMock(side_effect=Exception("LLM error"))
        mock_bridge.orchestrator = None

        context = MagicMock()
        response = await servicer.HealthCheck(warden_pb2.Empty(), context)

        assert response.components["llm"] is False

    @pytest.mark.asyncio
    async def test_get_status(self, servicer):
        """Test GetStatus RPC."""
        context = MagicMock()
        response = await servicer.GetStatus(warden_pb2.Empty(), context)

        assert response.running is True
        assert response.active_pipelines == 0
        assert response.total_scans == 0
        assert response.memory_mb > 0

    @pytest.mark.asyncio
    async def test_get_available_frames(self, servicer, mock_bridge):
        """Test GetAvailableFrames RPC."""
        mock_bridge.get_available_frames = AsyncMock(return_value={
            "frames": [
                {"id": "security", "name": "Security", "priority": 1, "is_blocker": True, "enabled": True, "tags": []},
                {"id": "chaos", "name": "Chaos", "priority": 2, "is_blocker": False, "enabled": True, "tags": []}
            ]
        })

        context = MagicMock()
        response = await servicer.GetAvailableFrames(warden_pb2.Empty(), context)

        assert len(response.frames) == 2
        assert response.frames[0].id == "security"
        assert response.frames[0].is_blocker is True
        assert response.frames[1].id == "chaos"

    @pytest.mark.asyncio
    async def test_get_available_providers(self, servicer, mock_bridge):
        """Test GetAvailableProviders RPC."""
        mock_bridge.get_available_providers = AsyncMock(return_value={
            "default": "anthropic",
            "providers": [
                {"id": "anthropic", "name": "Anthropic", "available": True, "is_default": True, "status": "ready"},
                {"id": "openai", "name": "OpenAI", "available": False, "is_default": False, "status": "not_configured"}
            ]
        })

        context = MagicMock()
        response = await servicer.GetAvailableProviders(warden_pb2.Empty(), context)

        assert response.default_provider == "anthropic"
        assert len(response.providers) == 2
        assert response.providers[0].available is True
        assert response.providers[1].status == "not_configured"

    @pytest.mark.asyncio
    async def test_execute_pipeline_success(self, servicer, mock_bridge):
        """Test ExecutePipeline RPC success."""
        mock_bridge.execute_pipeline = AsyncMock(return_value={
            "success": True,
            "run_id": "test-run-123",
            "total_findings": 3,
            "critical_count": 1,
            "high_count": 1,
            "medium_count": 1,
            "low_count": 0,
            "frames_executed": ["security", "chaos"],
            "findings": [
                {
                    "id": "f-001",
                    "title": "SQL Injection",
                    "severity": "critical",
                    "file_path": "src/db.py",
                    "line_number": 42
                }
            ],
            "fortifications": [],
            "cleanings": []
        })

        request = warden_pb2.PipelineRequest(path="./src")
        context = MagicMock()

        response = await servicer.ExecutePipeline(request, context)

        assert response.success is True
        assert response.run_id == "test-run-123"
        assert response.total_findings == 3
        assert response.critical_count == 1
        assert len(response.findings) == 1
        assert response.findings[0].title == "SQL Injection"
        assert servicer.total_scans == 1

    @pytest.mark.asyncio
    async def test_execute_pipeline_with_frames(self, servicer, mock_bridge):
        """Test ExecutePipeline with specific frames."""
        mock_bridge.execute_pipeline = AsyncMock(return_value={
            "success": True,
            "run_id": "test-run-456",
            "total_findings": 0,
            "critical_count": 0,
            "high_count": 0,
            "medium_count": 0,
            "low_count": 0,
            "frames_executed": ["security"],
            "findings": [],
            "fortifications": [],
            "cleanings": []
        })

        request = warden_pb2.PipelineRequest(path="./src")
        request.frames.extend(["security"])
        context = MagicMock()

        response = await servicer.ExecutePipeline(request, context)

        mock_bridge.execute_pipeline.assert_called_once_with(
            path="./src",
            frames=["security"]
        )
        assert response.success is True

    @pytest.mark.asyncio
    async def test_execute_pipeline_error(self, servicer, mock_bridge):
        """Test ExecutePipeline RPC error handling."""
        mock_bridge.execute_pipeline = AsyncMock(side_effect=Exception("Pipeline failed"))

        request = warden_pb2.PipelineRequest(path="./src")
        context = MagicMock()

        response = await servicer.ExecutePipeline(request, context)

        assert response.success is False
        assert "Pipeline failed" in response.error_message

    @pytest.mark.asyncio
    async def test_execute_pipeline_stream(self, servicer, mock_bridge):
        """Test ExecutePipelineStream RPC."""
        async def mock_stream(*args, **kwargs):
            yield {"type": "stage_start", "stage": "security", "progress": 0.0, "message": "Starting security"}
            yield {"type": "progress", "stage": "security", "progress": 0.5, "message": "Analyzing..."}
            yield {"type": "finding", "finding": {"id": "f-001", "title": "Issue", "severity": "high"}}
            yield {"type": "stage_complete", "stage": "security", "progress": 1.0, "message": "Done"}

        mock_bridge.execute_pipeline_stream = mock_stream

        request = warden_pb2.PipelineRequest(path="./src")
        context = MagicMock()

        events = []
        async for event in servicer.ExecutePipelineStream(request, context):
            events.append(event)

        # Should have: start, stage events, complete
        assert len(events) >= 2
        assert events[0].event_type == "pipeline_start"
        assert events[-1].event_type == "pipeline_complete"

    @pytest.mark.asyncio
    async def test_classify_code(self, servicer, mock_bridge):
        """Test ClassifyCode RPC."""
        mock_bridge.classify_code = AsyncMock(return_value={
            "has_async_operations": True,
            "has_user_input": False,
            "has_database_operations": True,
            "has_network_calls": True,
            "has_file_operations": False,
            "has_authentication": False,
            "has_cryptography": False,
            "detected_frameworks": ["fastapi", "sqlalchemy"],
            "recommended_frames": ["security", "async"],
            "confidence": 0.9
        })

        request = warden_pb2.ClassifyRequest(
            code="import asyncio\nfrom fastapi import FastAPI",
            file_path="main.py"
        )
        context = MagicMock()

        response = await servicer.ClassifyCode(request, context)

        assert response.has_async_operations is True
        assert response.has_database_operations is True
        assert "fastapi" in response.detected_frameworks
        assert abs(response.confidence - 0.9) < 0.01  # Float precision

    @pytest.mark.asyncio
    async def test_get_configuration(self, servicer, mock_bridge):
        """Test GetConfiguration RPC."""
        mock_bridge.get_config = AsyncMock(return_value={
            "config_file": ".warden/config.yaml",
            "active_profile": "default"
        })
        mock_bridge.get_available_frames = AsyncMock(return_value={
            "frames": [{"id": "security", "name": "Security", "priority": 1}]
        })
        mock_bridge.get_available_providers = AsyncMock(return_value={
            "providers": [{"id": "anthropic", "name": "Anthropic"}]
        })

        context = MagicMock()
        response = await servicer.GetConfiguration(warden_pb2.Empty(), context)

        assert response.project_root == str(mock_bridge.project_root)
        assert response.config_file == ".warden/config.yaml"
        assert response.active_profile == "default"

    def test_convert_finding(self, servicer):
        """Test finding conversion helper."""
        finding_dict = {
            "id": "f-001",
            "title": "Test",
            "description": "Description",
            "severity": "critical",
            "file_path": "test.py",
            "line_number": 10,
            "column_number": 5,
            "code_snippet": "code",
            "suggestion": "fix it",
            "frame_id": "security",
            "cwe_id": "CWE-89",
            "owasp_category": "A03"
        }

        finding = servicer._convert_finding(finding_dict)

        assert finding.id == "f-001"
        assert finding.severity == warden_pb2.CRITICAL
        assert finding.cwe_id == "CWE-89"

    def test_convert_finding_unknown_severity(self, servicer):
        """Test finding conversion with unknown severity."""
        finding_dict = {
            "id": "f-002",
            "title": "Test",
            "severity": "unknown"
        }

        finding = servicer._convert_finding(finding_dict)
        assert finding.severity == warden_pb2.SEVERITY_UNSPECIFIED


class TestGrpcServer:
    """Tests for GrpcServer class."""

    def test_server_initialization(self):
        """Test server initialization."""
        server = GrpcServer(port=50051)

        assert server.port == 50051
        assert server.project_root == Path.cwd()
        assert server.server is None
        assert server.servicer is None

    def test_server_custom_port(self):
        """Test server with custom port."""
        server = GrpcServer(port=9999)
        assert server.port == 9999

    def test_server_custom_project_root(self):
        """Test server with custom project root."""
        custom_path = Path("/custom/path")
        server = GrpcServer(project_root=custom_path)
        assert server.project_root == custom_path

    def test_server_with_bridge(self):
        """Test server with provided bridge."""
        mock_bridge = MagicMock()
        server = GrpcServer(bridge=mock_bridge)
        assert server.bridge == mock_bridge
