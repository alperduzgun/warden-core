"""
Tests for generated protobuf messages.
"""

import pytest
from warden.grpc.generated import warden_pb2


class TestProtoMessages:
    """Test protobuf message creation and serialization."""

    def test_empty_message(self):
        """Test Empty message creation."""
        msg = warden_pb2.Empty()
        assert msg is not None
        # Empty should serialize to empty bytes
        assert len(msg.SerializeToString()) == 0

    def test_severity_enum(self):
        """Test Severity enum values."""
        assert warden_pb2.SEVERITY_UNSPECIFIED == 0
        assert warden_pb2.CRITICAL == 1
        assert warden_pb2.HIGH == 2
        assert warden_pb2.MEDIUM == 3
        assert warden_pb2.LOW == 4
        assert warden_pb2.INFO == 5

    def test_finding_message(self):
        """Test Finding message creation."""
        finding = warden_pb2.Finding(
            id="test-001",
            title="SQL Injection",
            description="Potential SQL injection vulnerability",
            severity=warden_pb2.CRITICAL,
            file_path="src/db.py",
            line_number=42,
            column_number=10,
            code_snippet="query = f\"SELECT * FROM users WHERE id={user_id}\"",
            suggestion="Use parameterized queries",
            frame_id="security",
            cwe_id="CWE-89",
            owasp_category="A03:2021"
        )

        assert finding.id == "test-001"
        assert finding.title == "SQL Injection"
        assert finding.severity == warden_pb2.CRITICAL
        assert finding.file_path == "src/db.py"
        assert finding.line_number == 42
        assert finding.cwe_id == "CWE-89"

    def test_finding_serialization(self):
        """Test Finding message serialization/deserialization."""
        original = warden_pb2.Finding(
            id="test-002",
            title="XSS Vulnerability",
            severity=warden_pb2.HIGH,
            file_path="src/web.py",
            line_number=100
        )

        # Serialize
        data = original.SerializeToString()
        assert len(data) > 0

        # Deserialize
        restored = warden_pb2.Finding()
        restored.ParseFromString(data)

        assert restored.id == original.id
        assert restored.title == original.title
        assert restored.severity == original.severity
        assert restored.file_path == original.file_path
        assert restored.line_number == original.line_number

    def test_pipeline_request(self):
        """Test PipelineRequest message."""
        request = warden_pb2.PipelineRequest(
            path="./src",
            parallel=True,
            timeout_seconds=300
        )
        request.frames.extend(["security", "chaos", "fuzz"])

        assert request.path == "./src"
        assert request.parallel is True
        assert request.timeout_seconds == 300
        assert list(request.frames) == ["security", "chaos", "fuzz"]

    def test_pipeline_result(self):
        """Test PipelineResult message."""
        result = warden_pb2.PipelineResult(
            success=True,
            run_id="run-123",
            total_findings=5,
            critical_count=1,
            high_count=2,
            medium_count=2,
            low_count=0,
            duration_ms=1500
        )
        result.frames_executed.extend(["security", "chaos"])

        # Add a finding
        finding = result.findings.add()
        finding.id = "f-001"
        finding.title = "Test Finding"
        finding.severity = warden_pb2.MEDIUM

        assert result.success is True
        assert result.total_findings == 5
        assert result.critical_count == 1
        assert len(result.findings) == 1
        assert result.findings[0].title == "Test Finding"

    def test_pipeline_event(self):
        """Test PipelineEvent message."""
        event = warden_pb2.PipelineEvent(
            event_type="progress",
            stage="security",
            progress=0.5,
            message="Analyzing files...",
            timestamp_ms=1234567890
        )

        assert event.event_type == "progress"
        assert event.stage == "security"
        assert event.progress == 0.5
        assert event.message == "Analyzing files..."

    def test_pipeline_event_with_finding(self):
        """Test PipelineEvent with embedded Finding."""
        event = warden_pb2.PipelineEvent(
            event_type="finding",
            stage="security"
        )
        event.finding.CopyFrom(warden_pb2.Finding(
            id="f-002",
            title="Hardcoded Secret",
            severity=warden_pb2.CRITICAL
        ))

        assert event.event_type == "finding"
        assert event.finding.id == "f-002"
        assert event.finding.severity == warden_pb2.CRITICAL

    def test_llm_analyze_request(self):
        """Test LlmAnalyzeRequest message."""
        request = warden_pb2.LlmAnalyzeRequest(
            code="def foo(): pass",
            prompt="Review this code",
            provider="anthropic",
            temperature=0.7,
            max_tokens=1000
        )

        assert request.code == "def foo(): pass"
        assert request.prompt == "Review this code"
        assert request.provider == "anthropic"
        assert abs(request.temperature - 0.7) < 0.01  # Float precision

    def test_llm_analyze_result(self):
        """Test LlmAnalyzeResult message."""
        result = warden_pb2.LlmAnalyzeResult(
            success=True,
            response="This code is fine.",
            provider_used="anthropic",
            model_used="claude-3-sonnet",
            tokens_used=150,
            duration_ms=2000
        )

        assert result.success is True
        assert result.response == "This code is fine."
        assert result.provider_used == "anthropic"

    def test_llm_analyze_result_with_error(self):
        """Test LlmAnalyzeResult with error."""
        result = warden_pb2.LlmAnalyzeResult(
            success=False
        )
        result.error.CopyFrom(warden_pb2.LlmError(
            code="RATE_LIMIT",
            message="Rate limit exceeded",
            provider="openai"
        ))

        assert result.success is False
        assert result.error.code == "RATE_LIMIT"
        assert result.error.provider == "openai"

    def test_classify_request(self):
        """Test ClassifyRequest message."""
        request = warden_pb2.ClassifyRequest(
            code="import asyncio\nasync def main(): pass",
            file_path="src/main.py"
        )

        assert "asyncio" in request.code
        assert request.file_path == "src/main.py"

    def test_classify_result(self):
        """Test ClassifyResult message."""
        result = warden_pb2.ClassifyResult(
            has_async_operations=True,
            has_user_input=False,
            has_database_operations=True,
            has_network_calls=True,
            has_file_operations=False,
            has_authentication=True,
            has_cryptography=False,
            confidence=0.95
        )
        result.detected_frameworks.extend(["fastapi", "sqlalchemy"])
        result.recommended_frames.extend(["security", "async", "sql"])

        assert result.has_async_operations is True
        assert result.has_database_operations is True
        assert abs(result.confidence - 0.95) < 0.01  # Float precision
        assert "fastapi" in result.detected_frameworks
        assert "security" in result.recommended_frames

    def test_frame_message(self):
        """Test Frame message."""
        frame = warden_pb2.Frame(
            id="security",
            name="Security Frame",
            description="Detects security vulnerabilities",
            priority=1,
            is_blocker=True,
            enabled=True
        )
        frame.tags.extend(["owasp", "cwe", "security"])

        assert frame.id == "security"
        assert frame.is_blocker is True
        assert "owasp" in frame.tags

    def test_frame_list(self):
        """Test FrameList message."""
        frame_list = warden_pb2.FrameList()

        frame1 = frame_list.frames.add()
        frame1.id = "security"
        frame1.name = "Security"
        frame1.priority = 1

        frame2 = frame_list.frames.add()
        frame2.id = "chaos"
        frame2.name = "Chaos"
        frame2.priority = 2

        assert len(frame_list.frames) == 2
        assert frame_list.frames[0].id == "security"
        assert frame_list.frames[1].id == "chaos"

    def test_provider_message(self):
        """Test Provider message."""
        provider = warden_pb2.Provider(
            id="anthropic",
            name="Anthropic Claude",
            available=True,
            is_default=True,
            status="ready"
        )

        assert provider.id == "anthropic"
        assert provider.available is True
        assert provider.status == "ready"

    def test_health_response(self):
        """Test HealthResponse message."""
        health = warden_pb2.HealthResponse(
            healthy=True,
            version="1.0.0",
            uptime_seconds=3600
        )
        health.components["llm"] = True
        health.components["qdrant"] = False

        assert health.healthy is True
        assert health.version == "1.0.0"
        assert health.uptime_seconds == 3600
        assert health.components["llm"] is True
        assert health.components["qdrant"] is False

    def test_status_response(self):
        """Test StatusResponse message."""
        status = warden_pb2.StatusResponse(
            running=True,
            active_pipelines=2,
            total_scans=100,
            total_findings=500,
            memory_mb=256,
            cpu_percent=15.5
        )

        assert status.running is True
        assert status.active_pipelines == 2
        assert status.total_scans == 100
        assert status.memory_mb == 256

    def test_configuration_response(self):
        """Test ConfigurationResponse message."""
        config = warden_pb2.ConfigurationResponse(
            project_root="/path/to/project",
            config_file=".warden/config.yaml",
            active_profile="default"
        )
        config.settings["timeout"] = "300"
        config.settings["parallel"] = "true"

        # Add frames
        frame = config.available_frames.frames.add()
        frame.id = "security"

        # Add providers
        provider = config.available_providers.providers.add()
        provider.id = "anthropic"

        assert config.project_root == "/path/to/project"
        assert config.settings["timeout"] == "300"
        assert len(config.available_frames.frames) == 1

    def test_fortification_message(self):
        """Test Fortification message."""
        fort = warden_pb2.Fortification(
            id="fort-001",
            title="Add input validation",
            description="User input should be validated",
            file_path="src/api.py",
            line_number=50,
            original_code="user_input = request.get('data')",
            suggested_code="user_input = validate(request.get('data'))",
            rationale="Prevents injection attacks",
            priority=warden_pb2.HIGH
        )

        assert fort.id == "fort-001"
        assert fort.priority == warden_pb2.HIGH
        assert "validate" in fort.suggested_code

    def test_cleaning_message(self):
        """Test Cleaning message."""
        cleaning = warden_pb2.Cleaning(
            id="clean-001",
            title="Remove unused import",
            description="Import 'os' is not used",
            file_path="src/utils.py",
            line_number=3,
            detail="<code>import os</code>"
        )

        assert cleaning.id == "clean-001"
        assert "unused import" in cleaning.title
