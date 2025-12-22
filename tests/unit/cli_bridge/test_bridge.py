"""
Unit tests for Warden Bridge
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch, MagicMock

from warden.cli_bridge.bridge import WardenBridge
from warden.cli_bridge.protocol import IPCError, ErrorCode


@pytest.fixture
def bridge():
    """Create a Warden Bridge instance for testing"""
    with patch("warden.cli_bridge.bridge.load_llm_config"):
        with patch("warden.cli_bridge.bridge.LlmFactory"):
            bridge = WardenBridge()
            return bridge


@pytest.fixture
def temp_test_file(tmp_path):
    """Create a temporary test file"""
    test_file = tmp_path / "test.py"
    test_file.write_text("def hello():\n    print('Hello, World!')\n")
    return test_file


class TestWardenBridge:
    """Test WardenBridge class"""

    @pytest.mark.asyncio
    async def test_ping(self, bridge):
        """Test ping method (health check)"""
        result = await bridge.ping()

        assert result["status"] == "ok"
        assert result["message"] == "pong"
        assert "timestamp" in result

    @pytest.mark.asyncio
    async def test_execute_pipeline_file_not_found(self, bridge):
        """Test execute_pipeline with non-existent file"""
        with pytest.raises(IPCError) as exc_info:
            await bridge.execute_pipeline("/nonexistent/file.py")

        error = exc_info.value
        assert error.code == ErrorCode.FILE_NOT_FOUND
        assert "not found" in error.message.lower()

    @pytest.mark.asyncio
    async def test_execute_pipeline_success(self, bridge, temp_test_file):
        """Test execute_pipeline with valid file"""
        # Mock frame factory and orchestrator
        mock_frame = Mock()
        mock_frame.frame_id = "test-frame"
        mock_frame.name = "Test Frame"
        mock_frame.description = "Test frame"
        mock_frame.priority = Mock(name="HIGH")
        mock_frame.is_blocker = False

        mock_result = Mock()
        mock_result.pipeline_id = "test-pipeline"
        mock_result.pipeline_name = "Test Pipeline"
        mock_result.status = Mock(value="completed")
        mock_result.duration = 1.5
        mock_result.total_frames = 1
        mock_result.frames_passed = 1
        mock_result.frames_failed = 0
        mock_result.frames_skipped = 0
        mock_result.total_findings = 0
        mock_result.critical_findings = 0
        mock_result.high_findings = 0
        mock_result.medium_findings = 0
        mock_result.low_findings = 0
        mock_result.frame_results = []
        mock_result.metadata = {}

        with patch("warden.cli_bridge.bridge.FrameFactory") as MockFrameFactory:
            with patch("warden.cli_bridge.bridge.PipelineOrchestrator") as MockOrchestrator:
                mock_factory = MockFrameFactory.return_value
                mock_factory.load_all_frames = AsyncMock(return_value=[mock_frame])

                mock_orchestrator = MockOrchestrator.return_value
                mock_orchestrator.execute = AsyncMock(return_value=mock_result)

                result = await bridge.execute_pipeline(str(temp_test_file))

                assert result["pipeline_id"] == "test-pipeline"
                assert result["status"] == "completed"
                assert result["total_frames"] == 1
                assert result["frames_passed"] == 1

    @pytest.mark.asyncio
    async def test_execute_pipeline_no_frames(self, bridge, temp_test_file):
        """Test execute_pipeline when no frames are loaded"""
        with patch("warden.cli_bridge.bridge.FrameFactory") as MockFrameFactory:
            mock_factory = MockFrameFactory.return_value
            mock_factory.load_all_frames = AsyncMock(return_value=[])

            result = await bridge.execute_pipeline(str(temp_test_file))

            assert result["status"] == "completed"
            assert result["total_frames"] == 0
            assert "no validation frames" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_get_config(self, bridge):
        """Test get_config method"""
        # Mock LLM config
        mock_provider = Mock()
        mock_provider.value = "azure_openai"
        mock_provider_config = Mock()
        mock_provider_config.enabled = True
        mock_provider_config.default_model = "gpt-4"
        mock_provider_config.endpoint = "https://api.openai.com"

        bridge.llm_config.get_all_providers_chain = Mock(return_value=[mock_provider])
        bridge.llm_config.get_provider_config = Mock(return_value=mock_provider_config)
        bridge.llm_config.default_provider = mock_provider

        # Mock frame factory
        mock_frame = Mock()
        mock_frame.frame_id = "frame-1"
        mock_frame.name = "Frame 1"
        mock_frame.description = "Test frame"
        mock_frame.priority = Mock(name="HIGH")
        mock_frame.is_blocker = True

        with patch("warden.cli_bridge.bridge.FrameFactory") as MockFrameFactory:
            mock_factory = MockFrameFactory.return_value
            mock_factory.load_all_frames = AsyncMock(return_value=[mock_frame])

            result = await bridge.get_config()

            assert result["version"] == "0.1.0"
            assert result["default_provider"] == "azure_openai"
            assert len(result["llm_providers"]) == 1
            assert result["llm_providers"][0]["name"] == "azure_openai"
            assert result["total_frames"] == 1
            assert len(result["frames"]) == 1

    @pytest.mark.asyncio
    async def test_get_config_error(self, bridge):
        """Test get_config when error occurs"""
        with patch("warden.cli_bridge.bridge.FrameFactory") as MockFrameFactory:
            mock_factory = MockFrameFactory.return_value
            mock_factory.load_all_frames = AsyncMock(side_effect=Exception("Load error"))

            with pytest.raises(IPCError) as exc_info:
                await bridge.get_config()

            error = exc_info.value
            assert error.code == ErrorCode.CONFIGURATION_ERROR

    @pytest.mark.asyncio
    async def test_analyze_with_llm_streaming(self, bridge):
        """Test analyze_with_llm with streaming"""
        mock_llm = Mock()
        mock_llm.stream_completion = AsyncMock(
            return_value=iter(["chunk1", "chunk2", "chunk3"])
        )

        async def async_gen():
            for chunk in ["chunk1", "chunk2", "chunk3"]:
                yield chunk

        mock_llm.stream_completion = AsyncMock(return_value=async_gen())

        bridge.llm_factory.get_provider = AsyncMock(return_value=mock_llm)

        chunks = []
        async for chunk in bridge.analyze_with_llm("Test prompt", stream=True):
            chunks.append(chunk)

        assert len(chunks) == 3
        assert chunks[0] == "chunk1"
        assert chunks[-1] == "chunk3"

    @pytest.mark.asyncio
    async def test_analyze_with_llm_no_streaming(self, bridge):
        """Test analyze_with_llm without streaming"""
        mock_llm = Mock()
        mock_llm.complete = AsyncMock(return_value="Full response")

        bridge.llm_factory.get_provider = AsyncMock(return_value=mock_llm)

        chunks = []
        async for chunk in bridge.analyze_with_llm("Test prompt", stream=False):
            chunks.append(chunk)

        assert len(chunks) == 1
        assert chunks[0] == "Full response"

    @pytest.mark.asyncio
    async def test_analyze_with_llm_invalid_provider(self, bridge):
        """Test analyze_with_llm with invalid provider"""
        with pytest.raises(IPCError) as exc_info:
            async for _ in bridge.analyze_with_llm("Test", provider="invalid"):
                pass

        error = exc_info.value
        assert error.code == ErrorCode.INVALID_PARAMS
        assert "invalid provider" in error.message.lower()

    @pytest.mark.asyncio
    async def test_analyze_with_llm_no_provider_available(self, bridge):
        """Test analyze_with_llm when no provider is available"""
        bridge.llm_factory.get_provider = AsyncMock(return_value=None)

        with pytest.raises(IPCError) as exc_info:
            async for _ in bridge.analyze_with_llm("Test"):
                pass

        error = exc_info.value
        assert error.code == ErrorCode.LLM_ERROR
        assert "no llm provider" in error.message.lower()

    @pytest.mark.asyncio
    async def test_get_available_frames(self, bridge):
        """Test get_available_frames method"""
        mock_frame1 = Mock()
        mock_frame1.frame_id = "frame-1"
        mock_frame1.name = "Frame 1"
        mock_frame1.description = "Test frame 1"
        mock_frame1.priority = Mock(name="CRITICAL")
        mock_frame1.is_blocker = True
        mock_frame1.tags = ["security"]

        mock_frame2 = Mock()
        mock_frame2.frame_id = "frame-2"
        mock_frame2.name = "Frame 2"
        mock_frame2.description = "Test frame 2"
        mock_frame2.priority = Mock(name="MEDIUM")
        mock_frame2.is_blocker = False

        with patch("warden.cli_bridge.bridge.FrameFactory") as MockFrameFactory:
            mock_factory = MockFrameFactory.return_value
            mock_factory.load_all_frames = AsyncMock(return_value=[mock_frame1, mock_frame2])

            result = await bridge.get_available_frames()

            assert len(result) == 2
            assert result[0]["id"] == "frame-1"
            assert result[0]["priority"] == "CRITICAL"
            assert result[0]["is_blocker"] is True
            assert result[1]["id"] == "frame-2"

    def test_detect_language(self, bridge):
        """Test _detect_language method"""
        assert bridge._detect_language(Path("test.py")) == "python"
        assert bridge._detect_language(Path("test.js")) == "javascript"
        assert bridge._detect_language(Path("test.ts")) == "typescript"
        assert bridge._detect_language(Path("test.java")) == "java"
        assert bridge._detect_language(Path("test.go")) == "go"
        assert bridge._detect_language(Path("test.rs")) == "rust"
        assert bridge._detect_language(Path("test.unknown")) == "unknown"

    def test_serialize_pipeline_result(self, bridge):
        """Test _serialize_pipeline_result method"""
        mock_finding = Mock()
        mock_finding.severity = "high"
        mock_finding.message = "Test issue"
        mock_finding.line = 10
        mock_finding.column = 5
        mock_finding.code = "E001"

        mock_frame_result = Mock()
        mock_frame_result.frame_id = "frame-1"
        mock_frame_result.frame_name = "Test Frame"
        mock_frame_result.status = "failed"
        mock_frame_result.duration = 1.2
        mock_frame_result.issues_found = 1
        mock_frame_result.is_blocker = True
        mock_frame_result.findings = [mock_finding]

        mock_result = Mock()
        mock_result.pipeline_id = "pipeline-1"
        mock_result.pipeline_name = "Test Pipeline"
        mock_result.status = Mock(value="failed")
        mock_result.duration = 2.5
        mock_result.total_frames = 1
        mock_result.frames_passed = 0
        mock_result.frames_failed = 1
        mock_result.frames_skipped = 0
        mock_result.total_findings = 1
        mock_result.critical_findings = 0
        mock_result.high_findings = 1
        mock_result.medium_findings = 0
        mock_result.low_findings = 0
        mock_result.frame_results = [mock_frame_result]
        mock_result.metadata = {"test": "data"}

        result = bridge._serialize_pipeline_result(mock_result)

        assert result["pipeline_id"] == "pipeline-1"
        assert result["status"] == "failed"
        assert result["total_findings"] == 1
        assert len(result["frame_results"]) == 1
        assert result["frame_results"][0]["findings"][0]["severity"] == "high"
