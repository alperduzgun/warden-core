"""Built-in slash command handlers."""

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .types import (
    Command,
    CommandActionReturn,
    CommandContext,
    CommandKind,
    ICommandLoader,
    SubmitPromptReturn,
    TextContent,
)

if TYPE_CHECKING:
    from textual.app import App


@dataclass
class SlashCommand:
    """A slash command definition."""

    name: str
    description: str
    kind: CommandKind
    extension_name: str | None
    action: callable


class BuiltinCommandLoader(ICommandLoader):
    """Loads built-in slash commands."""

    async def load_commands(self) -> list[Command]:
        """Load all built-in commands."""
        return [
            SlashCommand(
                name="help",
                description="Show available commands and usage information",
                kind=CommandKind.BUILTIN,
                extension_name=None,
                action=self._help_action,
            ),
            SlashCommand(
                name="h",
                description="Alias for /help",
                kind=CommandKind.BUILTIN,
                extension_name=None,
                action=self._help_action,
            ),
            SlashCommand(
                name="?",
                description="Alias for /help",
                kind=CommandKind.BUILTIN,
                extension_name=None,
                action=self._help_action,
            ),
            SlashCommand(
                name="analyze",
                description="Run pipeline analysis on a file or directory",
                kind=CommandKind.BUILTIN,
                extension_name=None,
                action=self._analyze_action,
            ),
            SlashCommand(
                name="a",
                description="Alias for /analyze",
                kind=CommandKind.BUILTIN,
                extension_name=None,
                action=self._analyze_action,
            ),
            SlashCommand(
                name="check",
                description="Alias for /analyze",
                kind=CommandKind.BUILTIN,
                extension_name=None,
                action=self._analyze_action,
            ),
            SlashCommand(
                name="scan",
                description="Scan infrastructure for vulnerabilities",
                kind=CommandKind.BUILTIN,
                extension_name=None,
                action=self._scan_action,
            ),
            SlashCommand(
                name="s",
                description="Alias for /scan",
                kind=CommandKind.BUILTIN,
                extension_name=None,
                action=self._scan_action,
            ),
            SlashCommand(
                name="config",
                description="Show current configuration",
                kind=CommandKind.BUILTIN,
                extension_name=None,
                action=self._config_action,
            ),
            SlashCommand(
                name="status",
                description="Show system status",
                kind=CommandKind.BUILTIN,
                extension_name=None,
                action=self._status_action,
            ),
            SlashCommand(
                name="info",
                description="Alias for /status",
                kind=CommandKind.BUILTIN,
                extension_name=None,
                action=self._status_action,
            ),
            SlashCommand(
                name="rules",
                description="Manage validation rules",
                kind=CommandKind.BUILTIN,
                extension_name=None,
                action=self._rules_action,
            ),
            SlashCommand(
                name="r",
                description="Alias for /rules",
                kind=CommandKind.BUILTIN,
                extension_name=None,
                action=self._rules_action,
            ),
            SlashCommand(
                name="clear",
                description="Clear chat history",
                kind=CommandKind.BUILTIN,
                extension_name=None,
                action=self._clear_action,
            ),
            SlashCommand(
                name="cls",
                description="Alias for /clear",
                kind=CommandKind.BUILTIN,
                extension_name=None,
                action=self._clear_action,
            ),
            SlashCommand(
                name="quit",
                description="Exit the application",
                kind=CommandKind.BUILTIN,
                extension_name=None,
                action=self._quit_action,
            ),
            SlashCommand(
                name="exit",
                description="Alias for /quit",
                kind=CommandKind.BUILTIN,
                extension_name=None,
                action=self._quit_action,
            ),
            SlashCommand(
                name="q",
                description="Alias for /quit",
                kind=CommandKind.BUILTIN,
                extension_name=None,
                action=self._quit_action,
            ),
        ]

    async def _help_action(
        self, context: CommandContext, args: str
    ) -> CommandActionReturn:
        """Show help information."""
        help_text = """**Available Commands:**

**Analysis & Scanning:**
- `/analyze <path>` or `/a <path>` - Run pipeline analysis on a file or directory
- `/scan <path>` or `/s <path>` - Scan infrastructure for vulnerabilities
- `/rules` or `/r` - Manage validation rules

**Information:**
- `/help` or `/h` or `/?` - Show this help message
- `/config` - Show current configuration
- `/status` or `/info` - Show system status

**Navigation:**
- `/clear` or `/cls` - Clear chat history
- `/quit` or `/exit` or `/q` - Exit the application

**File Injection:**
- `@<path>` - Read and inject file content into the prompt
- `@<dir>` - Recursively read directory contents

**Shell Execution:**
- `!<command>` - Execute shell command (with approval prompt)

**Custom Commands:**
Custom commands can be defined in `~/.warden/commands/*.toml` files.
See documentation for TOML command format.
"""
        context.add_message(help_text, "info-message", True)
        return None

    async def _analyze_action(
        self, context: CommandContext, args: str
    ) -> CommandActionReturn:
        """Run analysis command."""
        from ...tui.commands import handle_analyze_command

        await handle_analyze_command(args, context.orchestrator, context.add_message)
        return None

    async def _scan_action(
        self, context: CommandContext, args: str
    ) -> CommandActionReturn:
        """Run scan command."""
        from ...tui.commands import handle_scan_command

        await handle_scan_command(
            args,
            context.project_root,
            context.orchestrator,
            context.add_message,
            context.app,
        )
        return None

    async def _config_action(
        self, context: CommandContext, args: str
    ) -> CommandActionReturn:
        """Show configuration."""
        from ...config.yaml_parser import load_pipeline_config

        try:
            config_path = context.project_root / ".warden" / "config.yaml"
            if config_path.exists():
                config = load_pipeline_config(str(config_path))
                config_text = f"""**Current Configuration:**

**Project Root:** `{context.project_root}`
**Config File:** `{config_path}`
**LLM Available:** {'Yes' if context.llm_available else 'No'}
**Session ID:** `{context.session_id or 'None'}`

**Pipeline Configuration:**
```yaml
{config_path.read_text()}
```
"""
            else:
                config_text = f"""**Configuration:**

**Project Root:** `{context.project_root}`
**Config File:** Not found (expected at `{config_path}`)
**LLM Available:** {'Yes' if context.llm_available else 'No'}
**Session ID:** `{context.session_id or 'None'}`
"""
            context.add_message(config_text, "info-message", True)
        except Exception as e:
            context.add_message(
                f"Error loading configuration: {str(e)}", "error-message", True
            )
        return None

    async def _status_action(
        self, context: CommandContext, args: str
    ) -> CommandActionReturn:
        """Show status information."""
        from ...tui.commands import handle_status_command

        handle_status_command(
            context.project_root,
            context.session_id,
            context.llm_available,
            context.add_message,
        )
        return None

    async def _rules_action(
        self, context: CommandContext, args: str
    ) -> CommandActionReturn:
        """Manage rules."""
        from ...tui.commands import rules as rules_command

        await rules_command.execute(context.app, args)
        return None

    async def _clear_action(
        self, context: CommandContext, args: str
    ) -> CommandActionReturn:
        """Clear chat history."""
        await context.app.action_clear_chat()
        return None

    async def _quit_action(
        self, context: CommandContext, args: str
    ) -> CommandActionReturn:
        """Quit application."""
        await context.app.action_quit()
        return None


def get_autocomplete_suggestions(prefix: str, commands: list[Command]) -> list[str]:
    """
    Get autocomplete suggestions for a command prefix.

    Args:
        prefix: The partial command name (without /)
        commands: Available commands

    Returns:
        List of matching command names
    """
    prefix_lower = prefix.lower()
    suggestions = []

    for cmd in commands:
        if cmd.name.startswith(prefix_lower):
            suggestions.append(cmd.name)

    return sorted(suggestions)
