"""Processor for @{path} file injection in prompts."""

import re
from pathlib import Path

from ..at_commands import AtCommandHandler
from ..types import (
    AT_FILE_INJECTION_TRIGGER,
    CommandContext,
    FileContent,
    IPromptProcessor,
    PromptContent,
    TextContent,
)


class AtFileProcessor(IPromptProcessor):
    """Processes @{path} file injection in prompts."""

    def __init__(self, command_name: str):
        """
        Initialize the processor.

        Args:
            command_name: Name of the command using this processor
        """
        self.command_name = command_name
        self.pattern = re.compile(r"@\{([^}]+)\}")

    async def process(
        self, content: list[PromptContent], context: CommandContext
    ) -> list[PromptContent]:
        """
        Replace @{path} with file content.

        Args:
            content: Input content to process
            context: Command execution context

        Returns:
            Processed content with files injected
        """
        handler = AtCommandHandler(context.project_root)
        result: list[PromptContent] = []

        for item in content:
            if isinstance(item, TextContent):
                # Find all @{path} patterns
                matches = list(self.pattern.finditer(item.text))

                if not matches:
                    # No matches, keep as-is
                    result.append(item)
                    continue

                # Process matches
                last_end = 0
                for match in matches:
                    # Add text before match
                    if match.start() > last_end:
                        result.append(
                            TextContent(text=item.text[last_end : match.start()])
                        )

                    # Load file
                    path_str = match.group(1)
                    path = Path(path_str)
                    if not path.is_absolute():
                        path = context.project_root / path

                    try:
                        path = path.resolve()
                        file_content = await handler.read_file(path)

                        if file_content:
                            result.append(file_content)
                        else:
                            # File couldn't be read, keep original text
                            result.append(
                                TextContent(
                                    text=f"[Error: Could not read file: {path_str}]"
                                )
                            )
                    except Exception as e:
                        result.append(
                            TextContent(
                                text=f"[Error loading file {path_str}: {str(e)}]"
                            )
                        )

                    last_end = match.end()

                # Add remaining text
                if last_end < len(item.text):
                    result.append(TextContent(text=item.text[last_end:]))
            else:
                # Keep other content types as-is
                result.append(item)

        return result
