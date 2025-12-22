"""Tests for @ file injection commands."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock

from warden.cli.commands.command_system import (
    AtCommandHandler,
    CommandContext,
    parse_at_command,
)


@pytest.fixture
def temp_project(tmp_path):
    """Create a temporary project directory with test files."""
    project = tmp_path / "project"
    project.mkdir()

    # Create test files
    (project / "test.py").write_text("print('hello')")
    (project / "README.md").write_text("# Test Project")

    # Create subdirectory
    subdir = project / "src"
    subdir.mkdir()
    (subdir / "main.py").write_text("def main(): pass")

    # Create .gitignore
    (project / ".gitignore").write_text("*.pyc\n__pycache__/\n")

    # Create ignored file
    (project / "test.pyc").write_text("binary data")

    return project


@pytest.fixture
def mock_context(temp_project):
    """Create a mock command context."""
    context = MagicMock(spec=CommandContext)
    context.project_root = temp_project
    context.add_message = MagicMock()
    return context


@pytest.mark.asyncio
async def test_read_single_file(temp_project):
    """Test reading a single file."""
    handler = AtCommandHandler(temp_project)
    result = await handler.read_file(temp_project / "test.py")

    assert result is not None
    assert result.path == temp_project / "test.py"
    assert result.content == "print('hello')"
    assert result.language == "python"


@pytest.mark.asyncio
async def test_read_nonexistent_file(temp_project):
    """Test reading a file that doesn't exist."""
    handler = AtCommandHandler(temp_project)
    result = await handler.read_file(temp_project / "nonexistent.py")

    assert result is None


@pytest.mark.asyncio
async def test_read_ignored_file(temp_project):
    """Test that ignored files are skipped."""
    handler = AtCommandHandler(temp_project)
    result = await handler.read_file(temp_project / "test.pyc")

    assert result is None


@pytest.mark.asyncio
async def test_read_directory(temp_project):
    """Test reading all files in a directory."""
    handler = AtCommandHandler(temp_project)
    results = await handler.read_directory(temp_project)

    # Should read Python and Markdown files, but not .pyc
    assert len(results) >= 2
    paths = {r.path.name for r in results}
    assert "test.py" in paths
    assert "README.md" in paths
    assert "test.pyc" not in paths


@pytest.mark.asyncio
async def test_detect_language(temp_project):
    """Test language detection from file extensions."""
    handler = AtCommandHandler(temp_project)

    assert handler._detect_language(Path("test.py")) == "python"
    assert handler._detect_language(Path("test.js")) == "javascript"
    assert handler._detect_language(Path("test.ts")) == "typescript"
    assert handler._detect_language(Path("test.md")) == "markdown"
    assert handler._detect_language(Path("test.yaml")) == "yaml"
    assert handler._detect_language(Path("test.json")) == "json"
    assert handler._detect_language(Path("test.unknown")) is None


@pytest.mark.asyncio
async def test_handle_at_command_file(temp_project, mock_context):
    """Test handling @ command for a single file."""
    handler = AtCommandHandler(temp_project)
    result = await handler.handle_at_command("test.py", mock_context)

    assert result is not None
    assert result.type == "submit_prompt"
    assert len(result.content) == 1
    assert result.content[0].path.name == "test.py"


@pytest.mark.asyncio
async def test_handle_at_command_directory(temp_project, mock_context):
    """Test handling @ command for a directory."""
    handler = AtCommandHandler(temp_project)
    result = await handler.handle_at_command("src", mock_context)

    assert result is not None
    assert result.type == "submit_prompt"
    assert len(result.content) >= 1
    mock_context.add_message.assert_called_once()


@pytest.mark.asyncio
async def test_handle_at_command_nonexistent(temp_project, mock_context):
    """Test handling @ command for nonexistent path."""
    handler = AtCommandHandler(temp_project)
    result = await handler.handle_at_command("nonexistent.py", mock_context)

    assert result is None
    mock_context.add_message.assert_called_once()
    call_args = mock_context.add_message.call_args
    assert "does not exist" in call_args[0][0]


@pytest.mark.asyncio
async def test_handle_at_command_outside_project(temp_project, mock_context):
    """Test that @ command rejects paths outside project."""
    handler = AtCommandHandler(temp_project)
    result = await handler.handle_at_command("../../etc/passwd", mock_context)

    assert result is None
    mock_context.add_message.assert_called_once()
    call_args = mock_context.add_message.call_args
    assert "outside project root" in call_args[0][0]


def test_parse_at_command():
    """Test parsing @ commands."""
    assert parse_at_command("@test.py") == "test.py"
    assert parse_at_command("@src/main.py") == "src/main.py"
    assert parse_at_command("@  test.py  ") == "test.py"
    assert parse_at_command("test.py") is None
    assert parse_at_command("/help") is None
