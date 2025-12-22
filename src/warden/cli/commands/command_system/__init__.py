"""Command system for Warden CLI.

This module provides a flexible command system inspired by Qwen Code,
supporting:
- Slash commands (/) for built-in commands
- At commands (@) for file injection
- Bang commands (!) for shell execution
- Custom TOML-based commands with template variable expansion
"""

from .at_commands import AtCommandHandler, parse_at_command
from .bang_commands import BangCommandHandler, parse_bang_command
from .command_service import CommandService
from .file_command_loader import (
    FileCommandLoader,
    get_project_commands_dir,
    get_user_commands_dir,
)
from .slash_commands import BuiltinCommandLoader, get_autocomplete_suggestions
from .types import (
    AT_FILE_INJECTION_TRIGGER,
    Command,
    CommandActionReturn,
    CommandContext,
    CommandInvocation,
    CommandKind,
    ConfirmationRequiredError,
    ConfirmShellReturn,
    FileContent,
    ICommandLoader,
    IPromptProcessor,
    PromptContent,
    SHELL_INJECTION_TRIGGER,
    SHORTHAND_ARGS_PLACEHOLDER,
    ShellContent,
    SubmitPromptReturn,
    TextContent,
)

__all__ = [
    # Command service
    "CommandService",
    # Command loaders
    "BuiltinCommandLoader",
    "FileCommandLoader",
    "ICommandLoader",
    # Command handlers
    "AtCommandHandler",
    "BangCommandHandler",
    # Parsing utilities
    "parse_at_command",
    "parse_bang_command",
    "get_autocomplete_suggestions",
    # Directory helpers
    "get_user_commands_dir",
    "get_project_commands_dir",
    # Types
    "Command",
    "CommandContext",
    "CommandInvocation",
    "CommandKind",
    "CommandActionReturn",
    "SubmitPromptReturn",
    "ConfirmShellReturn",
    "PromptContent",
    "TextContent",
    "FileContent",
    "ShellContent",
    "IPromptProcessor",
    "ConfirmationRequiredError",
    # Constants
    "SHORTHAND_ARGS_PLACEHOLDER",
    "SHELL_INJECTION_TRIGGER",
    "AT_FILE_INJECTION_TRIGGER",
]
