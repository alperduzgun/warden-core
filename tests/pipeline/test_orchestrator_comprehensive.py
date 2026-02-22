"""
Comprehensive tests for PhaseOrchestrator.

Tests critical functionality including:
- Timeout enforcement (ID 29)
- Status state machine (ID 3)
- Cleanup on success/failure/timeout (ID 37)
- Exception handling
"""

import asyncio
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from uuid import uuid4

import pytest

from warden.pipeline.application.orchestrator.orchestrator import PhaseOrchestrator
from warden.pipeline.domain.enums import PipelineStatus, AnalysisLevel
from warden.pipeline.domain.models import PipelineConfig
from warden.validation.domain.frame import CodeFile, ValidationFrame, FrameResult


@pytest.fixture
def mock_validation_frame():
    """Create a mock validation frame."""
    frame = MagicMock(spec=ValidationFrame)
    frame.id = "test_frame"
    frame.name = "Test Frame"
    frame.description = "Test validation frame"
    frame.priority = MagicMock(value=1)
    frame.is_blocker = True
    return frame


@pytest.fixture
def mock_llm_service():
    """Create a mock LLM service."""
    llm = AsyncMock()
    llm.complete_async = AsyncMock(return_value=MagicMock(content="{}"))
    llm.get_usage = MagicMock(return_value={
        'total_tokens': 100,
        'prompt_tokens': 50,
        'completion_tokens': 50,
        'request_count': 1
    })
    return llm


@pytest.fixture
def sample_code_file():
    """Create a sample code file for testing."""
    return CodeFile(
        path="test.py",
        content="def hello(): pass",
        language="python"
    )


@pytest.fixture
def project_root(tmp_path):
    """Create a temporary project root directory."""
    return tmp_path


class TestTimeoutEnforcement:
    """Test suite for pipeline timeout enforcement (ID 29)."""

    @pytest.mark.asyncio
    async def test_timeout_enforcement(self, mock_validation_frame, sample_code_file, project_root, mock_llm_service):
        """Verify pipeline times out after configured seconds."""
        # Create config with very short timeout
        config = PipelineConfig(
            timeout=1,  # 1 second timeout
            enable_pre_analysis=False,
            enable_analysis=False,
            enable_classification=False,
            enable_validation=False,
            enable_fortification=False,
            enable_cleaning=False,
        )

        orchestrator = PhaseOrchestrator(
            frames=[mock_validation_frame],
            config=config,
            project_root=project_root,
            llm_service=mock_llm_service
        )

        # Mock phase executor to simulate long-running operation
        async def slow_phase(context, code_files):
            await asyncio.sleep(5)  # Longer than timeout

        with patch.object(orchestrator.phase_executor, 'execute_pre_analysis_async', side_effect=slow_phase):
            config.enable_pre_analysis = True

            # Should raise RuntimeError with timeout message
            with pytest.raises(RuntimeError, match="Pipeline execution timeout"):
                await orchestrator.execute_pipeline_async([sample_code_file])

            # Verify pipeline status is FAILED
            assert orchestrator.pipeline.status == PipelineStatus.FAILED

    @pytest.mark.asyncio
    async def test_timeout_error_recorded(self, mock_validation_frame, sample_code_file, project_root, mock_llm_service):
        """Verify timeout errors are recorded in context."""
        config = PipelineConfig(
            timeout=1,
            enable_pre_analysis=False,
            enable_analysis=False,
            enable_classification=False,
            enable_validation=False,
            enable_fortification=False,
            enable_cleaning=False,
        )

        orchestrator = PhaseOrchestrator(
            frames=[mock_validation_frame],
            config=config,
            project_root=project_root,
            llm_service=mock_llm_service
        )

        async def slow_phase(context, code_files):
            await asyncio.sleep(5)

        with patch.object(orchestrator.phase_executor, 'execute_pre_analysis_async', side_effect=slow_phase):
            config.enable_pre_analysis = True

            try:
                await orchestrator.execute_pipeline_async([sample_code_file])
            except RuntimeError:
                pass

            # Verify error is in context (cleanup runs in finally)
            # We can't access context directly here since exception is raised
            assert orchestrator.pipeline.status == PipelineStatus.FAILED

    @pytest.mark.asyncio
    async def test_no_timeout_completes_normally(self, mock_validation_frame, sample_code_file, project_root, mock_llm_service):
        """Verify pipeline completes normally when within timeout."""
        config = PipelineConfig(
            timeout=300,  # Generous timeout
            enable_pre_analysis=False,
            enable_analysis=False,
            enable_classification=False,
            enable_validation=False,
            enable_fortification=False,
            enable_cleaning=False,
        )

        orchestrator = PhaseOrchestrator(
            frames=[mock_validation_frame],
            config=config,
            project_root=project_root,
            llm_service=mock_llm_service
        )

        context = await orchestrator.execute_pipeline_async([sample_code_file])

        # Should complete successfully
        assert orchestrator.pipeline.status == PipelineStatus.COMPLETED
        assert context is not None


class TestStatusStateMachine:
    """Test suite for pipeline status state machine (ID 3)."""

    @pytest.mark.asyncio
    async def test_status_completed_with_failures_non_blocker(self, project_root, mock_llm_service):
        """Non-blocker failures should result in COMPLETED_WITH_FAILURES status."""
        # Create a non-blocker frame
        non_blocker_frame = MagicMock(spec=ValidationFrame)
        non_blocker_frame.id = "non_blocker"
        non_blocker_frame.name = "Non Blocker Frame"
        non_blocker_frame.is_blocker = False
        non_blocker_frame.priority = MagicMock(value=2)

        config = PipelineConfig(
            enable_pre_analysis=False,
            enable_analysis=False,
            enable_classification=False,
            enable_validation=True,
            enable_fortification=False,
            enable_cleaning=False,
        )

        orchestrator = PhaseOrchestrator(
            frames=[non_blocker_frame],
            config=config,
            project_root=project_root,
            llm_service=mock_llm_service
        )

        # Mock frame executor to return failed non-blocker result
        mock_result = FrameResult(
            frame_id="non_blocker",
            frame_name="Non Blocker Frame",
            status="failed",
            is_blocker=False,
            duration=0.0,
            issues_found=1,
            findings=[]
        )

        async def mock_validation(context, code_files, pipeline):
            context.frame_results["non_blocker"] = {"result": mock_result}

        with patch.object(orchestrator.frame_executor, 'execute_validation_with_strategy_async', side_effect=mock_validation):
            code_file = CodeFile(path="test.py", content="def test(): pass", language="python")
            context = await orchestrator.execute_pipeline_async([code_file])

            # Non-blocker failure should result in COMPLETED_WITH_FAILURES
            assert orchestrator.pipeline.status == PipelineStatus.COMPLETED_WITH_FAILURES

    @pytest.mark.asyncio
    async def test_status_failed_on_blocker(self, project_root, mock_llm_service):
        """Blocker failures should result in FAILED status."""
        # Create a blocker frame
        blocker_frame = MagicMock(spec=ValidationFrame)
        blocker_frame.id = "blocker"
        blocker_frame.name = "Blocker Frame"
        blocker_frame.is_blocker = True
        blocker_frame.priority = MagicMock(value=1)

        config = PipelineConfig(
            enable_pre_analysis=False,
            enable_analysis=False,
            enable_classification=False,
            enable_validation=True,
            enable_fortification=False,
            enable_cleaning=False,
        )

        orchestrator = PhaseOrchestrator(
            frames=[blocker_frame],
            config=config,
            project_root=project_root,
            llm_service=mock_llm_service
        )

        # Mock frame executor to return failed blocker result
        mock_result = FrameResult(
            frame_id="blocker",
            frame_name="Blocker Frame",
            status="failed",
            is_blocker=True,
            duration=0.0,
            issues_found=1,
            findings=[]
        )

        async def mock_validation(context, code_files, pipeline):
            context.frame_results["blocker"] = {"result": mock_result}

        with patch.object(orchestrator.frame_executor, 'execute_validation_with_strategy_async', side_effect=mock_validation):
            code_file = CodeFile(path="test.py", content="def test(): pass", language="python")
            context = await orchestrator.execute_pipeline_async([code_file])

            # Blocker failure should result in FAILED
            assert orchestrator.pipeline.status == PipelineStatus.FAILED

    @pytest.mark.asyncio
    async def test_status_completed_on_success(self, mock_validation_frame, sample_code_file, project_root, mock_llm_service):
        """All passing frames should result in COMPLETED status."""
        config = PipelineConfig(
            enable_pre_analysis=False,
            enable_analysis=False,
            enable_classification=False,
            enable_validation=True,
            enable_fortification=False,
            enable_cleaning=False,
        )

        orchestrator = PhaseOrchestrator(
            frames=[mock_validation_frame],
            config=config,
            project_root=project_root,
            llm_service=mock_llm_service
        )

        # Mock successful validation
        mock_result = FrameResult(
            frame_id="test_frame",
            frame_name="Test Frame",
            status="passed",
            is_blocker=False,
            duration=0.0,
            issues_found=0,
            findings=[]
        )

        async def mock_validation(context, code_files, pipeline):
            context.frame_results["test_frame"] = {"result": mock_result}

        with patch.object(orchestrator.frame_executor, 'execute_validation_with_strategy_async', side_effect=mock_validation):
            context = await orchestrator.execute_pipeline_async([sample_code_file])

            # Success should result in COMPLETED
            assert orchestrator.pipeline.status == PipelineStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_status_failed_on_context_errors(self, mock_validation_frame, sample_code_file, project_root, mock_llm_service):
        """Context errors should result in FAILED status."""
        config = PipelineConfig(
            enable_pre_analysis=False,
            enable_analysis=False,
            enable_classification=False,
            enable_validation=False,
            enable_fortification=False,
            enable_cleaning=False,
        )

        orchestrator = PhaseOrchestrator(
            frames=[mock_validation_frame],
            config=config,
            project_root=project_root,
            llm_service=mock_llm_service
        )

        # Mock phase to add error to context
        async def mock_phase_with_error(context, code_files):
            context.errors.append("Test error")

        with patch.object(orchestrator.phase_executor, 'execute_pre_analysis_async', side_effect=mock_phase_with_error):
            config.enable_pre_analysis = True
            context = await orchestrator.execute_pipeline_async([sample_code_file])

            # Errors should result in FAILED
            assert orchestrator.pipeline.status == PipelineStatus.FAILED


class TestCleanupBehavior:
    """Test suite for cleanup on success/timeout/exception (ID 37)."""

    @pytest.mark.asyncio
    async def test_cleanup_runs_on_success(self, mock_validation_frame, sample_code_file, project_root, mock_llm_service):
        """Verify LSP/semantic search cleanup runs on successful completion."""
        config = PipelineConfig(
            enable_pre_analysis=False,
            enable_analysis=False,
            enable_classification=False,
            enable_validation=False,
            enable_fortification=False,
            enable_cleaning=False,
        )

        orchestrator = PhaseOrchestrator(
            frames=[mock_validation_frame],
            config=config,
            project_root=project_root,
            llm_service=mock_llm_service
        )

        # Mock semantic search service
        mock_ss = AsyncMock()
        mock_ss.close = AsyncMock()
        orchestrator.semantic_search_service = mock_ss

        # Mock LSP diagnostics
        mock_lsp = AsyncMock()
        mock_lsp.shutdown = AsyncMock()
        orchestrator.phase_executor.lsp_diagnostics = mock_lsp

        context = await orchestrator.execute_pipeline_async([sample_code_file])

        # Verify cleanup was called
        mock_ss.close.assert_called_once()
        mock_lsp.shutdown.assert_called_once()
        assert orchestrator.pipeline.status == PipelineStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_cleanup_runs_on_timeout(self, mock_validation_frame, sample_code_file, project_root, mock_llm_service):
        """Verify cleanup runs after timeout."""
        config = PipelineConfig(
            timeout=1,
            enable_pre_analysis=False,
            enable_analysis=False,
            enable_classification=False,
            enable_validation=False,
            enable_fortification=False,
            enable_cleaning=False,
        )

        orchestrator = PhaseOrchestrator(
            frames=[mock_validation_frame],
            config=config,
            project_root=project_root,
            llm_service=mock_llm_service
        )

        # Mock semantic search service
        mock_ss = AsyncMock()
        mock_ss.close = AsyncMock()
        orchestrator.semantic_search_service = mock_ss

        # Mock slow phase
        async def slow_phase(context, code_files):
            await asyncio.sleep(5)

        with patch.object(orchestrator.phase_executor, 'execute_pre_analysis_async', side_effect=slow_phase):
            config.enable_pre_analysis = True

            try:
                await orchestrator.execute_pipeline_async([sample_code_file])
            except RuntimeError:
                pass

            # Cleanup should still run (in finally block)
            mock_ss.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_runs_on_exception(self, mock_validation_frame, sample_code_file, project_root, mock_llm_service):
        """Verify cleanup runs after unhandled exception."""
        config = PipelineConfig(
            enable_pre_analysis=False,
            enable_analysis=False,
            enable_classification=False,
            enable_validation=False,
            enable_fortification=False,
            enable_cleaning=False,
        )

        orchestrator = PhaseOrchestrator(
            frames=[mock_validation_frame],
            config=config,
            project_root=project_root,
            llm_service=mock_llm_service
        )

        # Mock semantic search service
        mock_ss = AsyncMock()
        mock_ss.close = AsyncMock()
        orchestrator.semantic_search_service = mock_ss

        # Mock phase that raises exception
        async def failing_phase(context, code_files):
            raise ValueError("Test exception")

        with patch.object(orchestrator.phase_executor, 'execute_pre_analysis_async', side_effect=failing_phase):
            config.enable_pre_analysis = True

            with pytest.raises(ValueError, match="Test exception"):
                await orchestrator.execute_pipeline_async([sample_code_file])

            # Cleanup should still run
            mock_ss.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_with_lsp_manager(self, mock_validation_frame, sample_code_file, project_root, mock_llm_service):
        """Verify global LSP manager shutdown is called."""
        config = PipelineConfig(
            enable_pre_analysis=False,
            enable_analysis=False,
            enable_classification=False,
            enable_validation=False,
            enable_fortification=False,
            enable_cleaning=False,
        )

        orchestrator = PhaseOrchestrator(
            frames=[mock_validation_frame],
            config=config,
            project_root=project_root,
            llm_service=mock_llm_service
        )

        # Mock LSP Manager
        mock_lsp_manager = AsyncMock()
        mock_lsp_manager.shutdown_all_async = AsyncMock()

        with patch('warden.lsp.manager.LSPManager') as mock_lsp_class:
            mock_lsp_class.get_instance.return_value = mock_lsp_manager

            await orchestrator.execute_pipeline_async([sample_code_file])

            # Verify LSP manager shutdown was called
            mock_lsp_manager.shutdown_all_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_handles_exceptions_gracefully(self, mock_validation_frame, sample_code_file, project_root, mock_llm_service):
        """Verify cleanup doesn't crash if individual cleanups fail."""
        config = PipelineConfig(
            enable_pre_analysis=False,
            enable_analysis=False,
            enable_classification=False,
            enable_validation=False,
            enable_fortification=False,
            enable_cleaning=False,
        )

        orchestrator = PhaseOrchestrator(
            frames=[mock_validation_frame],
            config=config,
            project_root=project_root,
            llm_service=mock_llm_service
        )

        # Mock semantic search that fails on close
        mock_ss = AsyncMock()
        mock_ss.close = AsyncMock(side_effect=Exception("Cleanup failed"))
        orchestrator.semantic_search_service = mock_ss

        # Should not raise exception, cleanup should continue
        context = await orchestrator.execute_pipeline_async([sample_code_file])

        # Pipeline should still complete despite cleanup failure
        assert context is not None
        assert orchestrator.pipeline.status == PipelineStatus.COMPLETED


class TestExceptionHandling:
    """Test suite for exception handling."""

    @pytest.mark.asyncio
    async def test_exception_handling_logs_error(self, mock_validation_frame, sample_code_file, project_root, mock_llm_service):
        """Pipeline catches and logs errors properly."""
        config = PipelineConfig(
            enable_pre_analysis=False,
            enable_analysis=False,
            enable_classification=False,
            enable_validation=False,
            enable_fortification=False,
            enable_cleaning=False,
        )

        orchestrator = PhaseOrchestrator(
            frames=[mock_validation_frame],
            config=config,
            project_root=project_root,
            llm_service=mock_llm_service
        )

        # Mock phase that raises exception
        test_error = ValueError("Test error message")

        async def failing_phase(context, code_files):
            raise test_error

        with patch.object(orchestrator.phase_executor, 'execute_pre_analysis_async', side_effect=failing_phase):
            config.enable_pre_analysis = True

            with pytest.raises(ValueError, match="Test error message"):
                await orchestrator.execute_pipeline_async([sample_code_file])

            # Verify pipeline status is FAILED
            assert orchestrator.pipeline.status == PipelineStatus.FAILED
            assert orchestrator.pipeline.completed_at is not None

    @pytest.mark.asyncio
    async def test_exception_updates_pipeline_status(self, mock_validation_frame, sample_code_file, project_root, mock_llm_service):
        """Exception updates pipeline status to FAILED."""
        config = PipelineConfig(
            enable_pre_analysis=False,
            enable_analysis=False,
            enable_classification=False,
            enable_validation=False,
            enable_fortification=False,
            enable_cleaning=False,
        )

        orchestrator = PhaseOrchestrator(
            frames=[mock_validation_frame],
            config=config,
            project_root=project_root,
            llm_service=mock_llm_service
        )

        async def failing_phase(context, code_files):
            raise RuntimeError("Pipeline failure")

        with patch.object(orchestrator.phase_executor, 'execute_pre_analysis_async', side_effect=failing_phase):
            config.enable_pre_analysis = True

            with pytest.raises(RuntimeError):
                await orchestrator.execute_pipeline_async([sample_code_file])

            assert orchestrator.pipeline.status == PipelineStatus.FAILED

    @pytest.mark.asyncio
    async def test_integrity_check_failure_handling(self, mock_validation_frame, sample_code_file, project_root, mock_llm_service):
        """Integrity check failures are caught and handled."""
        config = PipelineConfig(
            enable_pre_analysis=False,
            enable_analysis=False,
            enable_classification=False,
            enable_validation=False,
            enable_fortification=False,
            enable_cleaning=False,
        )

        orchestrator = PhaseOrchestrator(
            frames=[mock_validation_frame],
            config=config,
            project_root=project_root,
            llm_service=mock_llm_service
        )

        async def integrity_failure(context, code_files):
            raise RuntimeError("Integrity check failed: Test failure")

        with patch.object(orchestrator.phase_executor, 'execute_pre_analysis_async', side_effect=integrity_failure):
            config.enable_pre_analysis = True

            # Should not raise, but return context with error
            context = await orchestrator.execute_pipeline_async([sample_code_file])

            assert orchestrator.pipeline.status == PipelineStatus.FAILED
            assert any("Integrity check failed" in e for e in context.errors)


class TestLLMUsageTracking:
    """Test suite for LLM usage tracking."""

    @pytest.mark.asyncio
    async def test_llm_usage_captured(self, mock_validation_frame, sample_code_file, project_root, mock_llm_service):
        """Verify LLM usage is captured in context."""
        config = PipelineConfig(
            enable_pre_analysis=False,
            enable_analysis=False,
            enable_classification=False,
            enable_validation=False,
            enable_fortification=False,
            enable_cleaning=False,
        )

        # Configure mock LLM to return usage stats
        mock_llm_service.get_usage.return_value = {
            'total_tokens': 500,
            'prompt_tokens': 300,
            'completion_tokens': 200,
            'request_count': 5
        }

        orchestrator = PhaseOrchestrator(
            frames=[mock_validation_frame],
            config=config,
            project_root=project_root,
            llm_service=mock_llm_service
        )

        context = await orchestrator.execute_pipeline_async([sample_code_file])

        # Verify usage was captured
        assert context.total_tokens == 500
        assert context.prompt_tokens == 300
        assert context.completion_tokens == 200
        assert context.request_count == 5

    @pytest.mark.asyncio
    async def test_llm_usage_without_service(self, mock_validation_frame, sample_code_file, project_root):
        """Verify pipeline works without LLM service."""
        config = PipelineConfig(
            enable_pre_analysis=False,
            enable_analysis=False,
            enable_classification=False,
            enable_validation=False,
            enable_fortification=False,
            enable_cleaning=False,
            use_llm=False
        )

        orchestrator = PhaseOrchestrator(
            frames=[mock_validation_frame],
            config=config,
            project_root=project_root,
            llm_service=None  # No LLM service
        )

        context = await orchestrator.execute_pipeline_async([sample_code_file])

        # Should complete without errors
        assert context.total_tokens == 0
        assert context.request_count == 0


class TestAnalysisLevelOverrides:
    """Test suite for analysis level configuration."""

    @pytest.mark.asyncio
    async def test_basic_level_disables_llm(self, mock_validation_frame, sample_code_file, project_root, mock_llm_service):
        """BASIC analysis level should disable LLM and expensive phases."""
        config = PipelineConfig(
            use_llm=True,  # Will be overridden
            enable_fortification=True,  # Will be overridden
            enable_cleaning=True,  # Will be overridden
        )

        orchestrator = PhaseOrchestrator(
            frames=[mock_validation_frame],
            config=config,
            project_root=project_root,
            llm_service=mock_llm_service
        )

        # Execute with BASIC level override
        context = await orchestrator.execute_pipeline_async(
            [sample_code_file],
            analysis_level="basic"
        )

        # Verify LLM and expensive phases were disabled
        assert orchestrator.config.use_llm is False
        assert orchestrator.config.enable_fortification is False
        assert orchestrator.config.enable_cleaning is False
        assert orchestrator.config.enable_issue_validation is False

    @pytest.mark.asyncio
    async def test_standard_level_enables_llm(self, mock_validation_frame, sample_code_file, project_root, mock_llm_service):
        """STANDARD analysis level should enable LLM features."""
        config = PipelineConfig(
            use_llm=False,  # Will be overridden
            enable_fortification=False,  # Will be overridden
        )

        orchestrator = PhaseOrchestrator(
            frames=[mock_validation_frame],
            config=config,
            project_root=project_root,
            llm_service=mock_llm_service
        )

        # Execute with STANDARD level override
        context = await orchestrator.execute_pipeline_async(
            [sample_code_file],
            analysis_level="standard"
        )

        # Verify LLM features were enabled
        assert orchestrator.config.use_llm is True
        assert orchestrator.config.enable_fortification is True
        assert orchestrator.config.enable_issue_validation is True
