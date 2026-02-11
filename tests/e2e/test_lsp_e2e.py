"""
E2E test for LSP integration.

Tests the complete flow from config to pipeline execution.
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from warden.pipeline.application.orchestrator.orchestrator import PhaseOrchestrator
from warden.pipeline.domain.models import PipelineConfig
from warden.validation.domain.frame import CodeFile


@pytest.fixture
def python_code_file():
    """Sample Python code file."""
    return CodeFile(
        path="app.py",
        content="""
def calculate(x, y):
    # Missing type hints
    result = x + y
    return result

def main():
    # Undefined variable
    print(undefined_var)
""",
        language="python"
    )


class TestLSPE2E:
    """End-to-end tests for LSP integration."""

    @pytest.mark.asyncio
    async def test_lsp_disabled_by_default(self, python_code_file):
        """Test that LSP is disabled by default."""
        config = PipelineConfig()
        config.enable_pre_analysis = False
        config.enable_analysis = False
        config.enable_classification = False
        config.enable_validation = False
        config.enable_fortification = False
        config.enable_cleaning = False
        config.enable_issue_validation = False  # Disable verification to preserve LSP findings

        orchestrator = PhaseOrchestrator(
            frames=[],
            config=config,
            project_root=Path("/test")
        )

        # LSP service should not be initialized
        assert orchestrator.lsp_service is None

        context = await orchestrator.execute_pipeline_async([python_code_file])

        # No LSP findings
        assert "lsp" not in getattr(context, 'frame_results', {})

    @pytest.mark.asyncio
    async def test_lsp_enabled_with_config(self, python_code_file):
        """Test LSP integration with explicit config."""
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
        config.enable_issue_validation = False  # Disable verification to preserve LSP findings

        with patch('warden.lsp.diagnostic_service.LSPManager') as mock_manager_class:
            # Mock LSP manager and client
            mock_client = AsyncMock()
            mock_client.open_document_async = AsyncMock()
            mock_client.close_document_async = AsyncMock()

            notification_handlers = {}

            def mock_on_notification(method, handler):
                notification_handlers[method] = handler
                if method == "textDocument/publishDiagnostics":
                    # Simulate pyright diagnostic
                    handler({
                        "uri": "file:///test/app.py",
                        "diagnostics": [
                            {
                                "severity": 1,
                                "message": "Undefined name 'undefined_var'",
                                "range": {
                                    "start": {"line": 8, "character": 10},
                                    "end": {"line": 8, "character": 23}
                                },
                                "code": "undefined-name",
                                "source": "pyright"
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
                config=config,
                project_root=Path("/test")
            )

            # LSP service should be initialized
            assert orchestrator.lsp_service is not None
            assert orchestrator.lsp_service.enabled is True

            context = await orchestrator.execute_pipeline_async([python_code_file])

            # LSP findings should be present
            assert hasattr(context, 'findings')
            lsp_findings = [f for f in context.findings if "pyright" in f.message]
            assert len(lsp_findings) > 0

            # Verify finding details
            finding = lsp_findings[0]
            assert "undefined_var" in finding.message
            assert finding.severity == "critical"  # Error maps to critical
            assert finding.line == 9  # Line 8 (0-indexed) + 1

    @pytest.mark.asyncio
    async def test_lsp_graceful_failure(self, python_code_file):
        """Test pipeline continues when LSP fails."""
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
        config.enable_issue_validation = False  # Disable verification to preserve LSP findings

        with patch('warden.lsp.diagnostic_service.LSPManager') as mock_manager_class:
            mock_manager = Mock()
            mock_manager.is_available.return_value = True
            mock_manager.get_client_async = AsyncMock(
                side_effect=RuntimeError("Language server crashed")
            )
            mock_manager.shutdown_all_async = AsyncMock()
            mock_manager_class.get_instance.return_value = mock_manager

            orchestrator = PhaseOrchestrator(
                frames=[],
                config=config,
                project_root=Path("/test")
            )

            # Should not raise, pipeline completes
            context = await orchestrator.execute_pipeline_async([python_code_file])

            assert context is not None
            assert context.pipeline_id is not None

    @pytest.mark.asyncio
    async def test_lsp_with_multiple_languages(self):
        """Test LSP with multiple language files."""
        files = [
            CodeFile(
                path="app.py",
                content="def foo():\n    x = 1",
                language="python"
            ),
            CodeFile(
                path="app.ts",
                content="function bar() {\n    const y = 2;\n}",
                language="typescript"
            )
        ]

        config = PipelineConfig()
        config.lsp_config = {
            "enabled": True,
            "servers": ["python", "typescript"]
        }
        config.enable_pre_analysis = False
        config.enable_analysis = False
        config.enable_classification = False
        config.enable_validation = False
        config.enable_fortification = False
        config.enable_cleaning = False
        config.enable_issue_validation = False  # Disable verification to preserve LSP findings

        with patch('warden.lsp.diagnostic_service.LSPManager') as mock_manager_class:
            mock_client = AsyncMock()
            mock_client.open_document_async = AsyncMock()
            mock_client.close_document_async = AsyncMock()
            mock_client.on_notification = Mock()
            mock_client.remove_notification_handler = Mock()

            mock_manager = Mock()
            mock_manager.is_available.return_value = True
            mock_manager.get_client_async = AsyncMock(return_value=mock_client)
            mock_manager.shutdown_all_async = AsyncMock()
            mock_manager_class.get_instance.return_value = mock_manager

            orchestrator = PhaseOrchestrator(
                frames=[],
                config=config,
                project_root=Path("/test")
            )

            context = await orchestrator.execute_pipeline_async(files)

            # Verify both languages were processed
            # (open_document_async called for each file)
            assert mock_client.open_document_async.call_count >= 2
