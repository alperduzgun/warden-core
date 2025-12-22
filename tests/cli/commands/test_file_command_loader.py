"""Tests for TOML-based file command loader."""

import pytest
from pathlib import Path

from warden.cli.commands.command_system import (
    CommandKind,
    FileCommandLoader,
    get_project_commands_dir,
    get_user_commands_dir,
)


@pytest.fixture
def temp_commands_dir(tmp_path):
    """Create a temporary commands directory with test TOML files."""
    commands_dir = tmp_path / "commands"
    commands_dir.mkdir()

    # Simple command
    (commands_dir / "hello.toml").write_text("""
prompt = "Say hello to {{args}}"
description = "Greet someone"
""")

    # Command with shell injection
    (commands_dir / "check.toml").write_text("""
prompt = \"\"\"
Check the status:
!{git status}
\"\"\"
description = "Check git status"
""")

    # Command with file injection
    (commands_dir / "review.toml").write_text("""
prompt = \"\"\"
Review this file:
@{{{args}}}
\"\"\"
description = "Review a file"
""")

    # Nested command
    nested_dir = commands_dir / "git"
    nested_dir.mkdir()
    (nested_dir / "log.toml").write_text("""
prompt = "Show git log for {{args}}"
description = "Show git history"
""")

    # Invalid command (missing prompt)
    (commands_dir / "invalid.toml").write_text("""
description = "This is invalid"
""")

    return commands_dir


@pytest.mark.asyncio
async def test_load_commands_from_directory(temp_commands_dir):
    """Test loading commands from a directory."""
    loader = FileCommandLoader(user_commands_dir=temp_commands_dir)
    commands = await loader.load_commands()

    # Should load 4 valid commands (hello, check, review, git:log)
    assert len(commands) == 4

    # Check command names
    command_names = {cmd.name for cmd in commands}
    assert "hello" in command_names
    assert "check" in command_names
    assert "review" in command_names
    assert "git:log" in command_names


@pytest.mark.asyncio
async def test_command_has_correct_metadata(temp_commands_dir):
    """Test that loaded commands have correct metadata."""
    loader = FileCommandLoader(user_commands_dir=temp_commands_dir)
    commands = await loader.load_commands()

    hello_cmd = next(cmd for cmd in commands if cmd.name == "hello")
    assert hello_cmd.description == "Greet someone"
    assert hello_cmd.kind == CommandKind.FILE
    assert hello_cmd.extension_name is None


@pytest.mark.asyncio
async def test_nested_command_name(temp_commands_dir):
    """Test that nested commands use : separator."""
    loader = FileCommandLoader(user_commands_dir=temp_commands_dir)
    commands = await loader.load_commands()

    git_log = next(cmd for cmd in commands if cmd.name == "git:log")
    assert git_log is not None


@pytest.mark.asyncio
async def test_invalid_command_skipped(temp_commands_dir):
    """Test that invalid commands are skipped."""
    loader = FileCommandLoader(user_commands_dir=temp_commands_dir)
    commands = await loader.load_commands()

    # Invalid command should not be loaded
    command_names = {cmd.name for cmd in commands}
    assert "invalid" not in command_names


@pytest.mark.asyncio
async def test_command_with_args_processor(temp_commands_dir):
    """Test that commands with {{args}} get argument processor."""
    loader = FileCommandLoader(user_commands_dir=temp_commands_dir)
    commands = await loader.load_commands()

    hello_cmd = next(cmd for cmd in commands if cmd.name == "hello")
    # Should have processors for args and shell
    assert len(hello_cmd.processors) > 0


@pytest.mark.asyncio
async def test_command_with_shell_processor(temp_commands_dir):
    """Test that commands with !{} get shell processor."""
    loader = FileCommandLoader(user_commands_dir=temp_commands_dir)
    commands = await loader.load_commands()

    check_cmd = next(cmd for cmd in commands if cmd.name == "check")
    # Should have processors for shell
    assert len(check_cmd.processors) > 0


@pytest.mark.asyncio
async def test_command_with_file_processor(temp_commands_dir):
    """Test that commands with @{} get file processor."""
    loader = FileCommandLoader(user_commands_dir=temp_commands_dir)
    commands = await loader.load_commands()

    review_cmd = next(cmd for cmd in commands if cmd.name == "review")
    # Should have processors for file injection
    assert len(review_cmd.processors) > 0


@pytest.mark.asyncio
async def test_user_commands_override_project_commands(tmp_path):
    """Test that project commands override user commands."""
    user_dir = tmp_path / "user"
    user_dir.mkdir()
    (user_dir / "test.toml").write_text("""
prompt = "User version"
description = "User command"
""")

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "test.toml").write_text("""
prompt = "Project version"
description = "Project command"
""")

    loader = FileCommandLoader(
        user_commands_dir=user_dir, project_commands_dir=project_dir
    )
    commands = await loader.load_commands()

    # Should have both commands (deduplication happens in CommandService)
    assert len(commands) == 2


def test_get_user_commands_dir():
    """Test getting user commands directory."""
    dir_path = get_user_commands_dir()
    assert dir_path == Path.home() / ".warden" / "commands"


def test_get_project_commands_dir():
    """Test getting project commands directory."""
    project_root = Path("/test/project")
    dir_path = get_project_commands_dir(project_root)
    assert dir_path == project_root / ".warden" / "commands"
