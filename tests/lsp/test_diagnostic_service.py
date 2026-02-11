"""
Tests for LSP Diagnostic Service.

Validates LSP integration into the pipeline.
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from warden.lsp.diagnostic_service import LSPDiagnosticService
from warden.validation.domain.frame import CodeFile, Finding


@pytest.fixture
def sample_code_files():
    """Sample code files for testing."""
    return [
        CodeFile(
            path="test.py",
            content='def foo():\n    x = 1\n    return x',
            language="python"
        ),
        CodeFile(
            path="test.ts",
            content='function bar() {\n    const y = 2;\n    return y;\n}',
            language="typescript"
        )
    ]


@pytest.fixture
def mock_lsp_manager():
    """Mock LSP Manager."""
    with patch('warden.lsp.diagnostic_service.LSPManager') as mock:
        manager_instance = Mock()
        mock.get_instance.return_value = manager_instance
        yield manager_instance


class TestLSPDiagnosticService:
    """Tests for LSP Diagnostic Service."""

    def test_init_disabled(self):
        """Test service initialization when disabled."""
        service = LSPDiagnosticService(enabled=False)

        assert service.enabled is False
        assert service.manager is None
        assert service.servers == []

    def test_init_enabled(self, mock_lsp_manager):
        """Test service initialization when enabled."""
        service = LSPDiagnosticService(enabled=True, servers=["python", "rust"])

        assert service.enabled is True
        assert service.manager is not None
        assert service.servers == ["python", "rust"]

    @pytest.mark.asyncio
    async def test_collect_diagnostics_disabled(self, sample_code_files):
        """Test diagnostics collection when service is disabled."""
        service = LSPDiagnosticService(enabled=False)

        findings = await service.collect_diagnostics_async(
            sample_code_files,
            Path("/test/project")
        )

        assert findings == []

    @pytest.mark.asyncio
    async def test_collect_diagnostics_no_server_available(
        self,
        sample_code_files,
        mock_lsp_manager
    ):
        """Test diagnostics collection when no LSP server is available."""
        mock_lsp_manager.is_available.return_value = False

        service = LSPDiagnosticService(enabled=True)

        findings = await service.collect_diagnostics_async(
            sample_code_files,
            Path("/test/project")
        )

        assert findings == []

    @pytest.mark.asyncio
    async def test_collect_diagnostics_success(
        self,
        sample_code_files,
        mock_lsp_manager
    ):
        """Test successful diagnostics collection."""
        # Mock LSP client
        mock_client = AsyncMock()
        mock_client.open_document_async = AsyncMock()
        mock_client.close_document_async = AsyncMock()
        mock_client.on_notification = Mock()
        mock_client.remove_notification_handler = Mock()

        mock_lsp_manager.is_available.return_value = True
        mock_lsp_manager.get_client_async = AsyncMock(return_value=mock_client)

        # Mock diagnostic notification handler to trigger callback
        def mock_on_notification(method, handler):
            if method == "textDocument/publishDiagnostics":
                # Simulate diagnostic callback
                handler({
                    "uri": "file:///test/project/test.py",
                    "diagnostics": [
                        {
                            "severity": 1,  # Error
                            "message": "Undefined variable 'z'",
                            "range": {
                                "start": {"line": 1, "character": 4},
                                "end": {"line": 1, "character": 5}
                            },
                            "code": "undefined-var",
                            "source": "pyright"
                        }
                    ]
                })

        mock_client.on_notification = mock_on_notification

        service = LSPDiagnosticService(enabled=True)

        findings = await service.collect_diagnostics_async(
            sample_code_files,
            Path("/test/project")
        )

        # Verify findings were created
        assert len(findings) > 0
        assert any("LSP" in (f.detail or "") for f in findings)

    @pytest.mark.asyncio
    async def test_collect_diagnostics_client_failure(
        self,
        sample_code_files,
        mock_lsp_manager
    ):
        """Test diagnostics collection handles client failures gracefully."""
        mock_lsp_manager.is_available.return_value = True
        mock_lsp_manager.get_client_async = AsyncMock(side_effect=Exception("Client failed"))

        service = LSPDiagnosticService(enabled=True)

        findings = await service.collect_diagnostics_async(
            sample_code_files,
            Path("/test/project")
        )

        # Should return empty list on error
        assert findings == []

    def test_convert_single_diagnostic(self):
        """Test conversion of single LSP diagnostic to Warden finding."""
        service = LSPDiagnosticService(enabled=True)

        diagnostic = {
            "severity": 2,  # Warning
            "message": "Unused variable 'foo'",
            "range": {
                "start": {"line": 5, "character": 4},
                "end": {"line": 5, "character": 7}
            },
            "code": "unused-var",
            "source": "pylint"
        }

        finding = service._convert_single_diagnostic(
            diagnostic,
            "/test/file.py",
            "python"
        )

        assert finding is not None
        assert finding.severity == "medium"  # Warning maps to medium
        assert "pylint" in finding.message
        assert "Unused variable" in finding.message
        assert finding.line == 6  # LSP is 0-indexed, Warden is 1-indexed
        assert "/test/file.py" in finding.location
        assert "pylint" in (finding.detail or "")
        assert "unused-var" in (finding.detail or "")

    def test_severity_mapping(self):
        """Test LSP severity to Warden severity mapping."""
        service = LSPDiagnosticService(enabled=True)

        test_cases = [
            (1, "critical"),   # Error
            (2, "medium"),     # Warning
            (3, "low"),        # Info
            (4, "low"),        # Hint
            (999, "low"),      # Unknown defaults to low
        ]

        for lsp_severity, expected_severity in test_cases:
            diagnostic = {
                "severity": lsp_severity,
                "message": "Test",
                "range": {"start": {"line": 0, "character": 0}},
                "source": "test"
            }

            finding = service._convert_single_diagnostic(diagnostic, "test.py", "python")
            assert finding.severity == expected_severity

    def test_group_files_by_language(self, sample_code_files):
        """Test grouping files by language."""
        service = LSPDiagnosticService(enabled=True)

        grouped = service._group_files_by_language(sample_code_files)

        assert "python" in grouped
        assert "typescript" in grouped
        assert len(grouped["python"]) == 1
        assert len(grouped["typescript"]) == 1
        assert grouped["python"][0].path == "test.py"
        assert grouped["typescript"][0].path == "test.ts"

    def test_detect_language_from_path(self):
        """Test language detection from file path."""
        service = LSPDiagnosticService(enabled=True)

        test_cases = [
            ("test.py", "python"),
            ("test.rs", "rust"),
            ("test.ts", "typescript"),
            ("test.js", "javascript"),
            ("test.go", "go"),
            ("unknown.xyz", "unknown"),
        ]

        for path, expected_lang in test_cases:
            detected = service._detect_language_from_path(path)
            assert detected == expected_lang

    @pytest.mark.asyncio
    async def test_shutdown(self, mock_lsp_manager):
        """Test service shutdown."""
        mock_lsp_manager.shutdown_all_async = AsyncMock()

        service = LSPDiagnosticService(enabled=True)
        await service.shutdown_async()

        mock_lsp_manager.shutdown_all_async.assert_called_once()
