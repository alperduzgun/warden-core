"""! shell execution command handler."""

import asyncio
import shlex
from pathlib import Path
from typing import TYPE_CHECKING

from .types import (
    CommandActionReturn,
    CommandContext,
    ConfirmShellReturn,
    ShellContent,
    SubmitPromptReturn,
    TextContent,
)

if TYPE_CHECKING:
    pass


# Dangerous commands that should always require confirmation
DANGEROUS_COMMANDS = [
    "rm",
    "rmdir",
    "del",
    "delete",
    "format",
    "dd",
    "mkfs",
    "fdisk",
    "parted",
    "shutdown",
    "reboot",
    "halt",
    "poweroff",
    "init",
    "systemctl",
    "service",
    "kill",
    "killall",
    "pkill",
    "chmod",
    "chown",
    "chgrp",
    "mv",
    "move",
    "sudo",
    "su",
    "doas",
]


class BangCommandHandler:
    """Handler for ! shell execution commands."""

    def __init__(self, project_root: Path, require_confirmation: bool = True):
        """
        Initialize the handler.

        Args:
            project_root: Root directory of the project
            require_confirmation: Whether to require confirmation for dangerous commands
        """
        self.project_root = project_root
        self.require_confirmation = require_confirmation

    def _is_dangerous_command(self, command: str) -> bool:
        """
        Check if a command is potentially dangerous.

        Args:
            command: Shell command to check

        Returns:
            True if the command is dangerous
        """
        # Parse command to get the base command
        try:
            parts = shlex.split(command)
            if not parts:
                return False

            base_cmd = parts[0].split("/")[-1]  # Handle paths like /usr/bin/rm

            # Check if base command is in dangerous list
            if base_cmd in DANGEROUS_COMMANDS:
                return True

            # Check for destructive flags
            dangerous_patterns = [
                "-rf",
                "--force",
                "--recursive",
                ">/dev/null",
                "2>&1",
                "|",  # Piping might hide output
                "&&",  # Command chaining
                ";",  # Command chaining
            ]

            for pattern in dangerous_patterns:
                if pattern in command:
                    return True

        except ValueError:
            # If we can't parse it, treat it as dangerous
            return True

        return False

    async def execute_shell_command(
        self, command: str, context: CommandContext
    ) -> ShellContent:
        """
        Execute a shell command.

        Args:
            command: Shell command to execute
            context: Command execution context

        Returns:
            ShellContent with command output
        """
        try:
            # Execute command
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.project_root,
            )

            stdout, stderr = await process.communicate()

            # Combine stdout and stderr
            output = ""
            if stdout:
                output += stdout.decode("utf-8", errors="replace")
            if stderr:
                if output:
                    output += "\n"
                output += stderr.decode("utf-8", errors="replace")

            exit_code = process.returncode or 0

            return ShellContent(command=command, output=output, exit_code=exit_code)

        except Exception as e:
            return ShellContent(
                command=command,
                output=f"Error executing command: {str(e)}",
                exit_code=1,
            )

    async def handle_bang_command(
        self, command: str, context: CommandContext
    ) -> CommandActionReturn:
        """
        Handle ! shell execution command.

        Args:
            command: Shell command to execute
            context: Command execution context

        Returns:
            CommandActionReturn with command output or confirmation request
        """
        command = command.strip()
        if not command:
            context.add_message("No command specified", "error-message", True)
            return None

        # Check if confirmation is needed
        if self.require_confirmation and self._is_dangerous_command(command):
            # Return confirmation request
            return ConfirmShellReturn(
                type="confirm_shell_commands",
                commands_to_confirm=[command],
                original_invocation=context.invocation,
            )

        # Execute command
        result = await self.execute_shell_command(command, context)

        # Show result in UI
        if result.exit_code == 0:
            context.add_message(
                f"**Command:** `{command}`\n\n**Output:**\n```\n{result.output}\n```",
                "info-message",
                True,
            )
        else:
            context.add_message(
                f"**Command:** `{command}`\n\n**Error (exit code {result.exit_code}):**\n```\n{result.output}\n```",
                "error-message",
                True,
            )

        # Return output for prompt injection
        return SubmitPromptReturn(
            type="submit_prompt", content=[result, TextContent(text="")]
        )

    async def handle_confirmed_commands(
        self, commands: list[str], context: CommandContext
    ) -> CommandActionReturn:
        """
        Execute confirmed shell commands.

        Args:
            commands: List of confirmed commands
            context: Command execution context

        Returns:
            CommandActionReturn with command outputs
        """
        results: list[ShellContent | TextContent] = []

        for command in commands:
            result = await self.execute_shell_command(command, context)
            results.append(result)

            # Show result in UI
            if result.exit_code == 0:
                context.add_message(
                    f"**Command:** `{command}`\n\n**Output:**\n```\n{result.output}\n```",
                    "info-message",
                    True,
                )
            else:
                context.add_message(
                    f"**Command:** `{command}`\n\n**Error (exit code {result.exit_code}):**\n```\n{result.output}\n```",
                    "error-message",
                    True,
                )

        return SubmitPromptReturn(type="submit_prompt", content=results)


def parse_bang_command(input_text: str) -> str | None:
    """
    Parse ! command from input text.

    Args:
        input_text: Input text to parse

    Returns:
        Command string if ! command found, None otherwise
    """
    input_text = input_text.strip()
    if input_text.startswith("!"):
        return input_text[1:].strip()
    return None
