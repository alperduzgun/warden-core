"""Tests for ! shell execution commands."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock

from warden.cli.commands.command_system import (
    BangCommandHandler,
    parse_bang_command,
)


@pytest.fixture
def temp_project(tmp_path):
    """Create a temporary project directory."""
    project = tmp_path / "project"
    project.mkdir()
    return project


@pytest.fixture
def mock_context(temp_project):
    """Create a mock command context."""
    from warden.cli.commands.command_system import CommandContext

    context = MagicMock(spec=CommandContext)
    context.project_root = temp_project
    context.add_message = MagicMock()
    context.invocation = MagicMock()
    return context


def test_is_dangerous_command(temp_project):
    """Test detection of dangerous commands."""
    handler = BangCommandHandler(temp_project)

    # Dangerous commands
    assert handler._is_dangerous_command("rm -rf /")
    assert handler._is_dangerous_command("sudo rm file")
    assert handler._is_dangerous_command("chmod 777 file")
    assert handler._is_dangerous_command("shutdown now")
    assert handler._is_dangerous_command("kill -9 1234")
    assert handler._is_dangerous_command("dd if=/dev/zero of=/dev/sda")

    # Safe commands
    assert not handler._is_dangerous_command("ls -la")
    assert not handler._is_dangerous_command("cat file.txt")
    assert not handler._is_dangerous_command("echo hello")
    assert not handler._is_dangerous_command("grep pattern file")


def test_is_dangerous_with_patterns(temp_project):
    """Test detection of dangerous patterns."""
    handler = BangCommandHandler(temp_project)

    # Piping and chaining
    assert handler._is_dangerous_command("ls | grep test")
    assert handler._is_dangerous_command("echo hello && rm file")
    assert handler._is_dangerous_command("cat file ; rm file")

    # Redirects
    assert handler._is_dangerous_command("echo test >/dev/null")


@pytest.mark.asyncio
async def test_execute_safe_command(temp_project, mock_context):
    """Test executing a safe shell command."""
    handler = BangCommandHandler(temp_project, require_confirmation=False)

    result = await handler.execute_shell_command("echo hello", mock_context)

    assert result.command == "echo hello"
    assert "hello" in result.output
    assert result.exit_code == 0


@pytest.mark.asyncio
async def test_execute_failing_command(temp_project, mock_context):
    """Test executing a command that fails."""
    handler = BangCommandHandler(temp_project, require_confirmation=False)

    result = await handler.execute_shell_command(
        "ls /nonexistent_directory_12345", mock_context
    )

    assert result.exit_code != 0
    assert len(result.output) > 0


@pytest.mark.asyncio
async def test_handle_safe_command(temp_project, mock_context):
    """Test handling a safe command without confirmation."""
    handler = BangCommandHandler(temp_project, require_confirmation=False)

    result = await handler.handle_bang_command("echo test", mock_context)

    assert result is not None
    assert result.type == "submit_prompt"
    assert len(result.content) > 0


@pytest.mark.asyncio
async def test_handle_dangerous_command_requires_confirmation(temp_project, mock_context):
    """Test that dangerous commands require confirmation."""
    handler = BangCommandHandler(temp_project, require_confirmation=True)

    result = await handler.handle_bang_command("rm -rf test", mock_context)

    assert result is not None
    assert result.type == "confirm_shell_commands"
    assert "rm -rf test" in result.commands_to_confirm


@pytest.mark.asyncio
async def test_handle_confirmed_commands(temp_project, mock_context):
    """Test executing confirmed commands."""
    handler = BangCommandHandler(temp_project, require_confirmation=True)

    result = await handler.handle_confirmed_commands(
        ["echo hello", "echo world"], mock_context
    )

    assert result is not None
    assert result.type == "submit_prompt"
    assert len(result.content) >= 2


@pytest.mark.asyncio
async def test_handle_empty_command(temp_project, mock_context):
    """Test handling empty command."""
    handler = BangCommandHandler(temp_project)

    result = await handler.handle_bang_command("", mock_context)

    assert result is None
    mock_context.add_message.assert_called_once()


def test_parse_bang_command():
    """Test parsing ! commands."""
    assert parse_bang_command("!ls -la") == "ls -la"
    assert parse_bang_command("!echo hello") == "echo hello"
    assert parse_bang_command("!  ls  ") == "ls"
    assert parse_bang_command("ls -la") is None
    assert parse_bang_command("/help") is None
