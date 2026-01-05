
import pytest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch
from warden.analysis.application.integrity_scanner import IntegrityScanner, IntegrityIssue
from warden.analysis.domain.project_context import ProjectContext, Framework
from warden.ast.domain.enums import CodeLanguage
from warden.validation.domain.frame import CodeFile

@pytest.mark.asyncio
async def test_integrity_scanner_syntax_check():
    # Helper to create mock provider with error tree
    mock_registry = MagicMock()
    mock_provider = MagicMock()
    mock_tree = MagicMock()
    mock_node = MagicMock()
    
    # Simulate syntax error
    mock_node.has_error = True
    mock_node.start_point.row = 10
    mock_tree.root_node = mock_node
    mock_provider.parse.return_value = mock_tree
    
    # Configure registry to return mock provider
    mock_registry.get_provider.return_value = mock_provider
    
    scanner = IntegrityScanner(Path("/tmp"), mock_registry)
    
    code_files = [
        CodeFile(path="/tmp/broken.py", content="impot os", language="python")
    ]
    
    issues = await scanner.scan(code_files, ProjectContext())
    
    assert len(issues) == 1
    assert issues[0].file_path == "broken.py"
    assert "Syntax error detected" in issues[0].message
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
        
        issues = await scanner.scan([], context)
        
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
        
        issues = await scanner.scan([], context)
        
        assert len(issues) == 1
        assert issues[0].file_path == "BUILD"
        assert "Build validation failed" in issues[0].message
