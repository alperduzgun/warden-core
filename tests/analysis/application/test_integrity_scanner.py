
import pytest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch
from warden.analysis.application.integrity_scanner import IntegrityScanner
from warden.analysis.domain.project_context import ProjectContext, Framework
from warden.validation.domain.frame import CodeFile

@pytest.mark.asyncio
async def test_integrity_scanner_syntax_check():
    # Create mock provider that returns ParseResult with syntax error
    mock_registry = MagicMock()
    mock_provider = MagicMock()

    # Mock ParseResult with error
    mock_result = MagicMock()
    mock_result.status = "failed"
    mock_error = MagicMock()
    mock_error.message = "Syntax error detected at line 1"
    mock_result.errors = [mock_error]

    # Parse returns ParseResult (async)
    async def mock_parse(content: str, lang, path: str):
        return mock_result

    mock_provider.parse = mock_parse

    # Configure registry to return mock provider
    mock_registry.get_provider.return_value = mock_provider

    scanner = IntegrityScanner(Path("/tmp"), mock_registry)

    code_files = [
        CodeFile(path="/tmp/broken.py", content="impot os", language="python")
    ]

    issues = await scanner.scan_async(code_files, ProjectContext())

    assert len(issues) == 1
    assert issues[0].file_path == "broken.py"
    assert "Syntax error" in issues[0].message
    assert issues[0].severity == "error"

@pytest.mark.asyncio
async def test_integrity_scanner_build_verification_success():
    mock_registry = MagicMock()
    scanner = IntegrityScanner(Path("/tmp"), mock_registry, config={"enable_build_check": True})
    
    context = ProjectContext()
    context.framework = Framework.FASTAPI
    
    with patch("asyncio.create_subprocess_shell") as mock_subprocess:
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"")
        mock_proc.returncode = 0
        mock_subprocess.return_value = mock_proc
        
        issues = await scanner.scan_async([], context)
        
        assert len(issues) == 0
        mock_subprocess.assert_called_once()
        assert "python3 -m compileall" in mock_subprocess.call_args[0][0]

@pytest.mark.asyncio
async def test_integrity_scanner_build_verification_failure():
    mock_registry = MagicMock()
    scanner = IntegrityScanner(Path("/tmp"), mock_registry, config={"enable_build_check": True})
    
    context = ProjectContext()
    context.framework = Framework.FASTAPI
    
    with patch("asyncio.create_subprocess_shell") as mock_subprocess:
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"SyntaxError: invalid syntax")
        mock_proc.returncode = 1
        mock_subprocess.return_value = mock_proc
        
        issues = await scanner.scan_async([], context)
        
        assert len(issues) == 1
        assert issues[0].file_path == "BUILD"
        assert "Build validation failed" in issues[0].message
