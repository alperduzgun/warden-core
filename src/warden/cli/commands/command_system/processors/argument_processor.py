"""Processor for {{args}} template variable expansion."""

from ..types import (
    CommandContext,
    IPromptProcessor,
    PromptContent,
    SHORTHAND_ARGS_PLACEHOLDER,
    TextContent,
)


class ArgumentProcessor(IPromptProcessor):
    """Processes {{args}} template variables in prompts."""

    async def process(
        self, content: list[PromptContent], context: CommandContext
    ) -> list[PromptContent]:
        """
        Replace {{args}} with actual command arguments.

        Args:
            content: Input content to process
            context: Command execution context

        Returns:
            Processed content with {{args}} replaced
        """
        if not context.invocation:
            return content

        args = context.invocation.args

        result: list[PromptContent] = []

        for item in content:
            if isinstance(item, TextContent):
                # Replace {{args}} with actual arguments
                processed_text = item.text.replace(SHORTHAND_ARGS_PLACEHOLDER, args)
                result.append(TextContent(text=processed_text))
            else:
                # Keep other content types as-is
                result.append(item)

        return result


class DefaultArgumentProcessor(IPromptProcessor):
    """Appends command arguments to the end if no {{args}} placeholder exists."""

    async def process(
        self, content: list[PromptContent], context: CommandContext
    ) -> list[PromptContent]:
        """
        Append command arguments to the end of the content.

        Args:
            content: Input content to process
            context: Command execution context

        Returns:
            Content with arguments appended
        """
        if not context.invocation or not context.invocation.args:
            return content

        # Add arguments as separate text content
        result = content.copy()
        result.append(TextContent(text=f"\n\n{context.invocation.args}"))

        return result
