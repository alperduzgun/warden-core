"""Command service for orchestrating command loaders."""

from pathlib import Path
from typing import TYPE_CHECKING

from .file_command_loader import FileCommandLoader, get_project_commands_dir, get_user_commands_dir
from .slash_commands import BuiltinCommandLoader
from .types import Command, ICommandLoader

if TYPE_CHECKING:
    pass


class CommandService:
    """Orchestrates discovery and loading of all commands."""

    def __init__(self, commands: list[Command]):
        """
        Initialize the service.

        Args:
            commands: List of loaded commands
        """
        self._commands = commands
        self._command_map = {cmd.name: cmd for cmd in commands}

    @classmethod
    async def create(
        cls, loaders: list[ICommandLoader]
    ) -> "CommandService":
        """
        Create and initialize a new CommandService instance.

        This factory method orchestrates the entire command loading process.
        It runs all provided loaders, aggregates their results, handles
        name conflicts, and returns a fully constructed CommandService instance.

        Conflict resolution:
        - Extension commands that conflict with existing commands are renamed to
          extensionName.commandName
        - Non-extension commands (built-in, user, project) override earlier commands
          with the same name based on loader order

        Args:
            loaders: Array of command loaders. Built-in commands should come first.

        Returns:
            A new, fully initialized CommandService instance
        """
        all_commands: list[Command] = []

        # Load commands from all loaders
        for loader in loaders:
            try:
                commands = await loader.load_commands()
                all_commands.extend(commands)
            except Exception as e:
                print(f"[CommandService] A command loader failed: {e}")

        # Deduplicate and handle conflicts
        command_map: dict[str, Command] = {}

        for cmd in all_commands:
            final_name = cmd.name

            # Extension commands get renamed if they conflict
            if cmd.extension_name and cmd.name in command_map:
                renamed_name = f"{cmd.extension_name}.{cmd.name}"
                suffix = 1

                # Keep trying until we find a name that doesn't conflict
                while renamed_name in command_map:
                    renamed_name = f"{cmd.extension_name}.{cmd.name}{suffix}"
                    suffix += 1

                final_name = renamed_name

            # Update command name if renamed
            if final_name != cmd.name:
                # Create a new command with updated name
                from dataclasses import replace
                cmd = replace(cmd, name=final_name)  # type: ignore

            command_map[final_name] = cmd

        final_commands = list(command_map.values())
        return cls(final_commands)

    @classmethod
    async def create_default(cls, project_root: Path) -> "CommandService":
        """
        Create a CommandService with default loaders.

        Args:
            project_root: Project root directory

        Returns:
            CommandService with built-in and file-based commands loaded
        """
        loaders: list[ICommandLoader] = [
            # Built-in commands (highest priority)
            BuiltinCommandLoader(),
            # File-based custom commands
            FileCommandLoader(
                user_commands_dir=get_user_commands_dir(),
                project_commands_dir=get_project_commands_dir(project_root),
            ),
        ]

        return await cls.create(loaders)

    def get_commands(self) -> list[Command]:
        """
        Get all loaded commands.

        Returns:
            List of all commands
        """
        return self._commands

    def get_command(self, name: str) -> Command | None:
        """
        Get a command by name.

        Args:
            name: Command name

        Returns:
            Command or None if not found
        """
        return self._command_map.get(name)

    def find_commands(self, prefix: str) -> list[Command]:
        """
        Find commands matching a prefix.

        Args:
            prefix: Command name prefix

        Returns:
            List of matching commands
        """
        prefix_lower = prefix.lower()
        return [
            cmd for cmd in self._commands if cmd.name.startswith(prefix_lower)
        ]
