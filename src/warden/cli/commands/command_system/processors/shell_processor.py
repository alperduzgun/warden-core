"""Processor for !{command} shell execution in prompts."""

import re

from ..bang_commands import BangCommandHandler
from ..types import (
    CommandContext,
    ConfirmationRequiredError,
    IPromptProcessor,
    PromptContent,
    SHELL_INJECTION_TRIGGER,
    SHORTHAND_ARGS_PLACEHOLDER,
    ShellContent,
    TextContent,
)


class ShellProcessor(IPromptProcessor):
    """Processes !{command} shell execution and {{args}} in prompts."""

    def __init__(self, command_name: str):
        """
        Initialize the processor.

        Args:
            command_name: Name of the command using this processor
        """
        self.command_name = command_name
        # Match !{...} but not escaped \!{...}
        self.shell_pattern = re.compile(r"(?<!\\)!\{([^}]+)\}")

    async def process(
        self, content: list[PromptContent], context: CommandContext
    ) -> list[PromptContent]:
        """
        Replace !{command} with shell output and {{args}} with arguments.

        Args:
            content: Input content to process
            context: Command execution context

        Returns:
            Processed content with shell commands executed

        Raises:
            ConfirmationRequiredError: If dangerous commands need confirmation
        """
        if not context.invocation:
            return content

        args = context.invocation.args
        handler = BangCommandHandler(context.project_root, require_confirmation=True)

        # First pass: collect all shell commands and check if confirmation needed
        commands_to_confirm: list[str] = []

        for item in content:
            if isinstance(item, TextContent):
                # Replace {{args}} first
                text = item.text.replace(SHORTHAND_ARGS_PLACEHOLDER, args)

                # Find all shell commands
                matches = self.shell_pattern.finditer(text)
                for match in matches:
                    command = match.group(1)
                    # Replace {{args}} in command
                    command = command.replace(SHORTHAND_ARGS_PLACEHOLDER, args)

                    if handler._is_dangerous_command(command):
                        commands_to_confirm.append(command)

        # If confirmation needed, raise error
        if commands_to_confirm:
            raise ConfirmationRequiredError(commands_to_confirm)

        # Second pass: execute commands and build result
        result: list[PromptContent] = []

        for item in content:
            if isinstance(item, TextContent):
                # Replace {{args}} first
                text = item.text.replace(SHORTHAND_ARGS_PLACEHOLDER, args)

                # Find all shell commands
                matches = list(self.shell_pattern.finditer(text))

                if not matches:
                    # No matches, keep as-is
                    result.append(TextContent(text=text))
                    continue

                # Process matches
                last_end = 0
                for match in matches:
                    # Add text before match
                    if match.start() > last_end:
                        result.append(TextContent(text=text[last_end : match.start()]))

                    # Execute shell command
                    command = match.group(1)
                    # Replace {{args}} in command
                    command = command.replace(SHORTHAND_ARGS_PLACEHOLDER, args)

                    try:
                        shell_result = await handler.execute_shell_command(
                            command, context
                        )
                        result.append(shell_result)
                    except Exception as e:
                        result.append(
                            TextContent(
                                text=f"[Error executing command '{command}': {str(e)}]"
                            )
                        )

                    last_end = match.end()

                # Add remaining text
                if last_end < len(text):
                    result.append(TextContent(text=text[last_end:]))
            else:
                # Keep other content types as-is
                result.append(item)

        return result
