"""Tests for CommandService orchestration."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from warden.cli.commands.command_system import (
    CommandService,
    CommandKind,
    ICommandLoader,
)


class MockCommandLoader(ICommandLoader):
    """Mock command loader for testing."""

    def __init__(self, commands):
        self.commands = commands

    async def load_commands(self):
        return self.commands


@pytest.fixture
def mock_commands():
    """Create mock commands for testing."""
    cmd1 = MagicMock()
    cmd1.name = "test1"
    cmd1.description = "Test command 1"
    cmd1.kind = CommandKind.BUILTIN
    cmd1.extension_name = None

    cmd2 = MagicMock()
    cmd2.name = "test2"
    cmd2.description = "Test command 2"
    cmd2.kind = CommandKind.FILE
    cmd2.extension_name = None

    cmd3 = MagicMock()
    cmd3.name = "test1"  # Duplicate name
    cmd3.description = "Extension command"
    cmd3.kind = CommandKind.EXTENSION
    cmd3.extension_name = "myext"

    return [cmd1, cmd2, cmd3]


@pytest.mark.asyncio
async def test_create_service_with_loaders(mock_commands):
    """Test creating CommandService with loaders."""
    loader = MockCommandLoader(mock_commands)
    service = await CommandService.create([loader])

    commands = service.get_commands()
    assert len(commands) > 0


@pytest.mark.asyncio
async def test_service_deduplicates_commands(mock_commands):
    """Test that CommandService deduplicates commands."""
    loader = MockCommandLoader(mock_commands)
    service = await CommandService.create([loader])

    commands = service.get_commands()

    # Should have 3 commands (test1, test2, myext.test1)
    assert len(commands) == 3

    command_names = {cmd.name for cmd in commands}
    assert "test1" in command_names
    assert "test2" in command_names
    assert "myext.test1" in command_names


@pytest.mark.asyncio
async def test_service_renames_conflicting_extension_commands():
    """Test that extension commands are renamed on conflict."""
    cmd1 = MagicMock()
    cmd1.name = "help"
    cmd1.kind = CommandKind.BUILTIN
    cmd1.extension_name = None

    cmd2 = MagicMock()
    cmd2.name = "help"
    cmd2.kind = CommandKind.EXTENSION
    cmd2.extension_name = "myext"

    loader = MockCommandLoader([cmd1, cmd2])
    service = await CommandService.create([loader])

    # Extension command should be renamed to myext.help
    cmd = service.get_command("myext.help")
    assert cmd is not None


@pytest.mark.asyncio
async def test_get_command_by_name(mock_commands):
    """Test getting a command by name."""
    loader = MockCommandLoader(mock_commands)
    service = await CommandService.create([loader])

    cmd = service.get_command("test2")
    assert cmd is not None
    assert cmd.name == "test2"


@pytest.mark.asyncio
async def test_get_nonexistent_command(mock_commands):
    """Test getting a command that doesn't exist."""
    loader = MockCommandLoader(mock_commands)
    service = await CommandService.create([loader])

    cmd = service.get_command("nonexistent")
    assert cmd is None


@pytest.mark.asyncio
async def test_find_commands_by_prefix(mock_commands):
    """Test finding commands by prefix."""
    loader = MockCommandLoader(mock_commands)
    service = await CommandService.create([loader])

    commands = service.find_commands("test")
    assert len(commands) >= 2


@pytest.mark.asyncio
async def test_find_commands_case_insensitive(mock_commands):
    """Test that find_commands is case insensitive."""
    loader = MockCommandLoader(mock_commands)
    service = await CommandService.create([loader])

    commands = service.find_commands("TEST")
    assert len(commands) >= 2


@pytest.mark.asyncio
async def test_create_default_service(tmp_path):
    """Test creating default CommandService."""
    project_root = tmp_path / "project"
    project_root.mkdir()

    service = await CommandService.create_default(project_root)

    # Should have built-in commands
    commands = service.get_commands()
    assert len(commands) > 0

    # Should have help command
    help_cmd = service.get_command("help")
    assert help_cmd is not None


@pytest.mark.asyncio
async def test_loader_failure_doesnt_crash_service():
    """Test that a failing loader doesn't crash the service."""

    class FailingLoader(ICommandLoader):
        async def load_commands(self):
            raise Exception("Loader failed")

    cmd = MagicMock()
    cmd.name = "test"
    cmd.kind = CommandKind.BUILTIN
    cmd.extension_name = None

    working_loader = MockCommandLoader([cmd])
    failing_loader = FailingLoader()

    service = await CommandService.create([working_loader, failing_loader])

    # Should still have commands from working loader
    commands = service.get_commands()
    assert len(commands) > 0
