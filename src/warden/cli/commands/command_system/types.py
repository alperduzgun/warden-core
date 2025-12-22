"""Command system type definitions and base classes."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Awaitable, Callable, Protocol


class CommandKind(str, Enum):
    """Type of command."""

    BUILTIN = "builtin"  # Built-in slash commands
    FILE = "file"  # Custom TOML-based commands
    EXTENSION = "extension"  # Extension-provided commands


@dataclass
class CommandContext:
    """Context passed to command handlers."""

    app: Any  # Textual App instance
    project_root: Path
    session_id: str | None
    llm_available: bool
    orchestrator: Any | None  # CodeAnalyzer instance
    add_message: Callable[[str, str, bool], None]
    invocation: "CommandInvocation | None" = None


@dataclass
class CommandInvocation:
    """Details about how a command was invoked."""

    raw: str  # Raw input string
    command: str  # Command name (without prefix)
    args: str  # Arguments string
    prefix: str  # Command prefix (/, @, !)


@dataclass
class TextContent:
    """Text content in a prompt."""

    text: str


@dataclass
class FileContent:
    """File content in a prompt."""

    path: Path
    content: str
    language: str | None = None


@dataclass
class ShellContent:
    """Shell command output in a prompt."""

    command: str
    output: str
    exit_code: int


# Union type for prompt content
PromptContent = TextContent | FileContent | ShellContent


@dataclass
class SubmitPromptReturn:
    """Return value for submitting a prompt."""

    type: str = "submit_prompt"
    content: list[PromptContent] = None  # type: ignore

    def __post_init__(self) -> None:
        if self.content is None:
            self.content = []


@dataclass
class ConfirmShellReturn:
    """Return value for requesting shell command confirmation."""

    type: str = "confirm_shell_commands"
    commands_to_confirm: list[str] = None  # type: ignore
    original_invocation: CommandInvocation = None  # type: ignore

    def __post_init__(self) -> None:
        if self.commands_to_confirm is None:
            self.commands_to_confirm = []


# Union type for command action return values
CommandActionReturn = SubmitPromptReturn | ConfirmShellReturn | None


class Command(Protocol):
    """Protocol for command objects."""

    name: str
    description: str
    kind: CommandKind
    extension_name: str | None

    async def action(self, context: CommandContext, args: str) -> CommandActionReturn:
        """Execute the command."""
        ...


class ICommandLoader(ABC):
    """Interface for command loaders."""

    @abstractmethod
    async def load_commands(self) -> list[Command]:
        """
        Load commands from this loader's source.

        Returns:
            List of loaded commands
        """
        pass


class IPromptProcessor(ABC):
    """Interface for prompt content processors."""

    @abstractmethod
    async def process(
        self, content: list[PromptContent], context: CommandContext
    ) -> list[PromptContent]:
        """
        Process prompt content.

        Args:
            content: Input content to process
            context: Command execution context

        Returns:
            Processed content
        """
        pass


# Template variable placeholders
SHORTHAND_ARGS_PLACEHOLDER = "{{args}}"
SHELL_INJECTION_TRIGGER = "!{"
AT_FILE_INJECTION_TRIGGER = "@{"


class ConfirmationRequiredError(Exception):
    """Raised when shell command confirmation is required."""

    def __init__(self, commands: list[str]) -> None:
        self.commands_to_confirm = commands
        super().__init__(f"Confirmation required for commands: {commands}")
