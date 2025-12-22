"""Tests for slash command handlers."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from warden.cli.commands.command_system import (
    BuiltinCommandLoader,
    CommandContext,
    CommandKind,
    get_autocomplete_suggestions,
)


@pytest.fixture
def mock_context():
    """Create a mock command context."""
    context = MagicMock(spec=CommandContext)
    context.app = AsyncMock()
    context.project_root = Path("/test/project")
    context.session_id = "test-session"
    context.llm_available = True
    context.orchestrator = MagicMock()
    context.add_message = MagicMock()
    context.invocation = None
    return context


@pytest.mark.asyncio
async def test_builtin_loader_loads_all_commands():
    """Test that BuiltinCommandLoader loads all expected commands."""
    loader = BuiltinCommandLoader()
    commands = await loader.load_commands()

    # Check that we have commands
    assert len(commands) > 0

    # Check for specific commands
    command_names = {cmd.name for cmd in commands}
    expected_commands = [
        "help",
        "h",
        "?",
        "analyze",
        "a",
        "scan",
        "s",
        "config",
        "status",
        "rules",
        "clear",
        "quit",
    ]

    for expected in expected_commands:
        assert expected in command_names, f"Missing command: {expected}"


@pytest.mark.asyncio
async def test_builtin_commands_have_correct_kind():
    """Test that all built-in commands have BUILTIN kind."""
    loader = BuiltinCommandLoader()
    commands = await loader.load_commands()

    for cmd in commands:
        assert cmd.kind == CommandKind.BUILTIN
        assert cmd.extension_name is None


@pytest.mark.asyncio
async def test_help_command_action(mock_context):
    """Test help command action."""
    loader = BuiltinCommandLoader()
    commands = await loader.load_commands()

    help_cmd = next(cmd for cmd in commands if cmd.name == "help")
    result = await help_cmd.action(mock_context, "")

    # Should add a help message
    mock_context.add_message.assert_called_once()
    call_args = mock_context.add_message.call_args
    assert "Available Commands" in call_args[0][0]


@pytest.mark.asyncio
async def test_clear_command_action(mock_context):
    """Test clear command action."""
    loader = BuiltinCommandLoader()
    commands = await loader.load_commands()

    clear_cmd = next(cmd for cmd in commands if cmd.name == "clear")
    await clear_cmd.action(mock_context, "")

    # Should call app.action_clear_chat
    mock_context.app.action_clear_chat.assert_called_once()


@pytest.mark.asyncio
async def test_quit_command_action(mock_context):
    """Test quit command action."""
    loader = BuiltinCommandLoader()
    commands = await loader.load_commands()

    quit_cmd = next(cmd for cmd in commands if cmd.name == "quit")
    await quit_cmd.action(mock_context, "")

    # Should call app.action_quit
    mock_context.app.action_quit.assert_called_once()


def test_autocomplete_suggestions():
    """Test autocomplete suggestions."""
    # Create mock commands
    commands = [
        MagicMock(name="help"),
        MagicMock(name="analyze"),
        MagicMock(name="scan"),
        MagicMock(name="status"),
    ]

    # Test exact prefix match
    suggestions = get_autocomplete_suggestions("h", commands)
    assert suggestions == ["help"]

    # Test partial match
    suggestions = get_autocomplete_suggestions("a", commands)
    assert suggestions == ["analyze"]

    # Test multiple matches
    suggestions = get_autocomplete_suggestions("s", commands)
    assert set(suggestions) == {"scan", "status"}

    # Test no match
    suggestions = get_autocomplete_suggestions("xyz", commands)
    assert suggestions == []

    # Test case insensitive
    suggestions = get_autocomplete_suggestions("H", commands)
    assert suggestions == ["help"]
