"""Loader for TOML-based custom commands."""

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .processors import ArgumentProcessor, AtFileProcessor, ShellProcessor
from .processors.argument_processor import DefaultArgumentProcessor
from .types import (
    AT_FILE_INJECTION_TRIGGER,
    Command,
    CommandActionReturn,
    CommandContext,
    CommandKind,
    ConfirmationRequiredError,
    ICommandLoader,
    IPromptProcessor,
    SHELL_INJECTION_TRIGGER,
    SHORTHAND_ARGS_PLACEHOLDER,
    SubmitPromptReturn,
    TextContent,
)


@dataclass
class TomlCommandDef:
    """TOML command definition."""

    prompt: str
    description: str | None = None


@dataclass
class FileCommand:
    """A file-based custom command."""

    name: str
    description: str
    kind: CommandKind
    extension_name: str | None
    prompt: str
    processors: list[IPromptProcessor]

    async def action(
        self, context: CommandContext, args: str
    ) -> CommandActionReturn:
        """Execute the command."""
        if not context.invocation:
            # Fallback to unprocessed prompt
            return SubmitPromptReturn(
                type="submit_prompt", content=[TextContent(text=self.prompt)]
            )

        try:
            # Start with prompt as text content
            processed_content: list[Any] = [TextContent(text=self.prompt)]

            # Run through processors
            for processor in self.processors:
                processed_content = await processor.process(
                    processed_content, context
                )

            return SubmitPromptReturn(type="submit_prompt", content=processed_content)

        except ConfirmationRequiredError as e:
            # Request confirmation for dangerous commands
            from .types import ConfirmShellReturn

            return ConfirmShellReturn(
                type="confirm_shell_commands",
                commands_to_confirm=e.commands_to_confirm,
                original_invocation=context.invocation,
            )


class FileCommandLoader(ICommandLoader):
    """Loads custom commands from TOML files."""

    def __init__(
        self,
        user_commands_dir: Path | None = None,
        project_commands_dir: Path | None = None,
    ):
        """
        Initialize the loader.

        Args:
            user_commands_dir: User-level commands directory (~/.warden/commands)
            project_commands_dir: Project-level commands directory (.warden/commands)
        """
        self.user_commands_dir = user_commands_dir
        self.project_commands_dir = project_commands_dir

    def _get_command_directories(self) -> list[tuple[Path, str | None]]:
        """
        Get command directories in load order.

        Returns:
            List of (directory, extension_name) tuples
        """
        dirs: list[tuple[Path, str | None]] = []

        # User commands
        if self.user_commands_dir and self.user_commands_dir.exists():
            dirs.append((self.user_commands_dir, None))

        # Project commands (override user commands)
        if self.project_commands_dir and self.project_commands_dir.exists():
            dirs.append((self.project_commands_dir, None))

        return dirs

    def _parse_toml_file(self, file_path: Path) -> TomlCommandDef | None:
        """
        Parse a TOML command definition file.

        Args:
            file_path: Path to TOML file

        Returns:
            TomlCommandDef or None if invalid
        """
        try:
            with open(file_path, "rb") as f:
                data = tomllib.load(f)

            # Validate required fields
            if "prompt" not in data:
                print(
                    f"[FileCommandLoader] Skipping {file_path}: missing 'prompt' field"
                )
                return None

            if not isinstance(data["prompt"], str):
                print(
                    f"[FileCommandLoader] Skipping {file_path}: 'prompt' must be a string"
                )
                return None

            description = data.get("description")
            if description is not None and not isinstance(description, str):
                print(
                    f"[FileCommandLoader] Skipping {file_path}: 'description' must be a string"
                )
                return None

            return TomlCommandDef(prompt=data["prompt"], description=description)

        except Exception as e:
            print(f"[FileCommandLoader] Error parsing {file_path}: {e}")
            return None

    def _create_command(
        self,
        name: str,
        definition: TomlCommandDef,
        extension_name: str | None,
    ) -> FileCommand:
        """
        Create a command from a TOML definition.

        Args:
            name: Command name
            definition: TOML command definition
            extension_name: Optional extension name

        Returns:
            FileCommand instance
        """
        # Determine which processors are needed
        processors: list[IPromptProcessor] = []
        uses_args = SHORTHAND_ARGS_PLACEHOLDER in definition.prompt
        uses_shell = SHELL_INJECTION_TRIGGER in definition.prompt
        uses_at_file = AT_FILE_INJECTION_TRIGGER in definition.prompt

        # Order matters: file injection -> shell/args -> default args

        # 1. File injection (security first)
        if uses_at_file:
            processors.append(AtFileProcessor(name))

        # 2. Shell and argument injection
        if uses_shell or uses_args:
            processors.append(ShellProcessor(name))

        # 3. Default argument handling (if no explicit {{args}})
        if not uses_args:
            processors.append(DefaultArgumentProcessor())

        # Create description
        description = definition.description or f"Custom command from {name}.toml"
        if extension_name:
            description = f"[{extension_name}] {description}"

        return FileCommand(
            name=name,
            description=description,
            kind=CommandKind.FILE,
            extension_name=extension_name,
            prompt=definition.prompt,
            processors=processors,
        )

    async def load_commands(self) -> list[Command]:
        """
        Load all custom commands from TOML files.

        Returns:
            List of loaded commands
        """
        commands: list[Command] = []
        command_dirs = self._get_command_directories()

        for directory, extension_name in command_dirs:
            # Find all .toml files recursively
            for toml_file in directory.rglob("*.toml"):
                # Parse TOML
                definition = self._parse_toml_file(toml_file)
                if not definition:
                    continue

                # Calculate command name from path
                relative_path = toml_file.relative_to(directory)
                # Remove .toml extension
                name_parts = list(relative_path.parts[:-1]) + [
                    relative_path.stem
                ]
                # Join with : separator (like qwen-code)
                command_name = ":".join(name_parts)

                # Create command
                command = self._create_command(command_name, definition, extension_name)
                commands.append(command)  # type: ignore

        return commands  # type: ignore


def get_user_commands_dir() -> Path:
    """
    Get the user-level commands directory.

    Returns:
        Path to ~/.warden/commands
    """
    return Path.home() / ".warden" / "commands"


def get_project_commands_dir(project_root: Path) -> Path:
    """
    Get the project-level commands directory.

    Args:
        project_root: Project root directory

    Returns:
        Path to <project>/.warden/commands
    """
    return project_root / ".warden" / "commands"
