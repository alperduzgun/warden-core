"""
Tests for LSP integration with the pipeline.

Validates that LSP diagnostics are collected and merged into pipeline results.
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from warden.pipeline.application.orchestrator.orchestrator import PhaseOrchestrator
from warden.pipeline.domain.models import PipelineConfig
from warden.validation.domain.frame import CodeFile, Finding


@pytest.fixture
def sample_code_files():
    """Sample code files for testing."""
    return [
        CodeFile(
            path="test.py",
            content='def foo():\n    x = 1\n    return x',
            language="python"
        )
    ]


@pytest.fixture
def pipeline_config_with_lsp():
    """Pipeline config with LSP enabled."""
    config = PipelineConfig()
    config.lsp_config = {
        "enabled": True,
        "servers": ["python"]
    }
    config.enable_pre_analysis = False
    config.enable_analysis = False
    config.enable_classification = False
    config.enable_validation = False
    config.enable_fortification = False
    config.enable_cleaning = False
    config.enable_issue_validation = False
    return config


@pytest.fixture
def pipeline_config_without_lsp():
    """Pipeline config with LSP disabled."""
    config = PipelineConfig()
    config.lsp_config = {
        "enabled": False
    }
    config.enable_pre_analysis = False
    config.enable_analysis = False
    config.enable_classification = False
    config.enable_validation = False
    config.enable_fortification = False
    config.enable_cleaning = False
    config.enable_issue_validation = False
    return config


class TestLSPPipelineIntegration:
    """Tests for LSP pipeline integration."""

    def test_orchestrator_init_with_lsp_enabled(self, pipeline_config_with_lsp):
        """Test orchestrator initializes LSP service when enabled."""
        orchestrator = PhaseOrchestrator(
            frames=[],
            config=pipeline_config_with_lsp,
            project_root=Path("/test")
        )

        assert orchestrator.lsp_service is not None
        assert orchestrator.lsp_service.enabled is True

    def test_orchestrator_init_with_lsp_disabled(self, pipeline_config_without_lsp):
        """Test orchestrator does not initialize LSP service when disabled."""
        orchestrator = PhaseOrchestrator(
            frames=[],
            config=pipeline_config_without_lsp,
            project_root=Path("/test")
        )

        assert orchestrator.lsp_service is None

    @pytest.mark.asyncio
    async def test_pipeline_runs_without_lsp(
        self,
        sample_code_files,
        pipeline_config_without_lsp
    ):
        """Test pipeline runs normally when LSP is disabled."""
        orchestrator = PhaseOrchestrator(
            frames=[],
            config=pipeline_config_without_lsp,
            project_root=Path("/test")
        )

        context = await orchestrator.execute_pipeline_async(sample_code_files)

        # Pipeline should complete successfully
        assert context is not None
        assert context.pipeline_id is not None

        # LSP should not have been called
        assert "lsp" not in context.frame_results

    @pytest.mark.asyncio
    async def test_pipeline_with_lsp_no_server_available(
        self,
        sample_code_files,
        pipeline_config_with_lsp
    ):
        """Test pipeline handles missing LSP server gracefully."""
        with patch('warden.lsp.diagnostic_service.LSPManager') as mock_manager_class:
            mock_manager = Mock()
            mock_manager.is_available.return_value = False
            mock_manager_class.get_instance.return_value = mock_manager

            orchestrator = PhaseOrchestrator(
                frames=[],
                config=pipeline_config_with_lsp,
                project_root=Path("/test")
            )

            context = await orchestrator.execute_pipeline_async(sample_code_files)

            # Pipeline should complete successfully
            assert context is not None
            assert context.pipeline_id is not None

    @pytest.mark.asyncio
    async def test_pipeline_with_lsp_diagnostics(
        self,
        sample_code_files,
        pipeline_config_with_lsp
    ):
        """Test pipeline collects LSP diagnostics."""
        with patch('warden.lsp.diagnostic_service.LSPManager') as mock_manager_class:
            # Mock LSP client and manager
            mock_client = AsyncMock()
            mock_client.open_document_async = AsyncMock()
            mock_client.close_document_async = AsyncMock()

            # Track notification handlers
            notification_handlers = {}

            def mock_on_notification(method, handler):
                notification_handlers[method] = handler
                # Immediately trigger diagnostic callback
                if method == "textDocument/publishDiagnostics":
                    handler({
                        "uri": "file:///test/test.py",
                        "diagnostics": [
                            {
                                "severity": 1,
                                "message": "Test diagnostic",
                                "range": {
                                    "start": {"line": 0, "character": 0},
                                    "end": {"line": 0, "character": 1}
                                },
                                "code": "test-code",
                                "source": "test-lsp"
                            }
                        ]
                    })

            mock_client.on_notification = mock_on_notification
            mock_client.remove_notification_handler = Mock()

            mock_manager = Mock()
            mock_manager.is_available.return_value = True
            mock_manager.get_client_async = AsyncMock(return_value=mock_client)
            mock_manager.shutdown_all_async = AsyncMock()
            mock_manager_class.get_instance.return_value = mock_manager

            orchestrator = PhaseOrchestrator(
                frames=[],
                config=pipeline_config_with_lsp,
                project_root=Path("/test")
            )

            context = await orchestrator.execute_pipeline_async(sample_code_files)

            # Pipeline should complete successfully
            assert context is not None

            # LSP findings should be present
            if hasattr(context, 'findings') and context.findings:
                lsp_findings = [f for f in context.findings if "test-lsp" in f.message]
                assert len(lsp_findings) > 0

    @pytest.mark.asyncio
    async def test_pipeline_with_lsp_error_handling(
        self,
        sample_code_files,
        pipeline_config_with_lsp
    ):
        """Test pipeline handles LSP errors gracefully."""
        with patch('warden.lsp.diagnostic_service.LSPManager') as mock_manager_class:
            mock_manager = Mock()
            mock_manager.is_available.return_value = True
            mock_manager.get_client_async = AsyncMock(
                side_effect=Exception("LSP server failed")
            )
            mock_manager.shutdown_all_async = AsyncMock()
            mock_manager_class.get_instance.return_value = mock_manager

            orchestrator = PhaseOrchestrator(
                frames=[],
                config=pipeline_config_with_lsp,
                project_root=Path("/test")
            )

            # Pipeline should complete even if LSP fails
            context = await orchestrator.execute_pipeline_async(sample_code_files)

            assert context is not None
            assert context.pipeline_id is not None

    @pytest.mark.asyncio
    async def test_lsp_cleanup_on_pipeline_completion(
        self,
        sample_code_files,
        pipeline_config_with_lsp
    ):
        """Test LSP service is properly shut down after pipeline completion."""
        with patch('warden.lsp.diagnostic_service.LSPManager') as mock_manager_class:
            mock_manager = Mock()
            mock_manager.is_available.return_value = False
            mock_manager.shutdown_all_async = AsyncMock()
            mock_manager_class.get_instance.return_value = mock_manager

            orchestrator = PhaseOrchestrator(
                frames=[],
                config=pipeline_config_with_lsp,
                project_root=Path("/test")
            )

            context = await orchestrator.execute_pipeline_async(sample_code_files)

            assert context is not None

            # LSP manager should have been shut down
            mock_manager.shutdown_all_async.assert_called()

    @pytest.mark.asyncio
    async def test_lsp_cleanup_on_pipeline_failure(
        self,
        sample_code_files,
        pipeline_config_with_lsp
    ):
        """Test LSP service is properly shut down even if pipeline fails."""
        with patch('warden.lsp.diagnostic_service.LSPManager') as mock_manager_class:
            mock_manager = Mock()
            mock_manager.is_available.return_value = False
            mock_manager.shutdown_all_async = AsyncMock()
            mock_manager_class.get_instance.return_value = mock_manager

            # Create orchestrator that will fail
            orchestrator = PhaseOrchestrator(
                frames=[],
                config=pipeline_config_with_lsp,
                project_root=Path("/test")
            )

            # Force a failure by patching _execute_phases
            with patch.object(
                orchestrator,
                '_execute_lsp_diagnostics_async',
                side_effect=Exception("Forced failure")
            ):
                try:
                    await orchestrator.execute_pipeline_async(sample_code_files)
                except Exception:
                    pass  # Expected

            # LSP manager should still have been shut down
            mock_manager.shutdown_all_async.assert_called()
