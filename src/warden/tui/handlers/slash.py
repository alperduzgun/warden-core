"""Slash command router and handler."""

from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from textual.app import App
    from warden.analyzers.discovery.analyzer import CodeAnalyzer


async def handle_slash_command(
    command: str,
    app: "App",
    project_root: Path,
    session_id: str | None,
    llm_available: bool,
    orchestrator: "CodeAnalyzer | None",
    add_message: Callable[[str, str, bool], None],
) -> None:
    """
    Route and handle slash commands.

    Args:
        command: Full command string (including /)
        app: Textual App instance
        project_root: Project root directory
        session_id: Current session ID
        llm_available: Whether LLM is available
        orchestrator: PipelineOrchestrator instance
        add_message: Function to add messages to chat
    """
    from ..commands import (
        handle_analyze_command,
        handle_scan_command,
        handle_status_command,
        handle_help_command,
    )
    from ..commands import rules as rules_command

    # Parse command
    parts = command.split(maxsplit=1)
    cmd = parts[0][1:]  # Remove /
    args = parts[1] if len(parts) > 1 else ""

    # Handle commands
    if cmd in ["help", "h", "?"]:
        handle_help_command(add_message)
    elif cmd in ["analyze", "a", "check"]:
        await handle_analyze_command(args, orchestrator, add_message)
    elif cmd in ["scan", "s"]:
        await handle_scan_command(args, project_root, orchestrator, add_message, app)
    elif cmd in ["status", "info"]:
        handle_status_command(project_root, session_id, llm_available, add_message)
    elif cmd in ["rules", "r"]:
        await rules_command.execute(app, args)
    elif cmd in ["clear", "cls"]:
        await app.action_clear_chat()
    elif cmd in ["quit", "exit", "q"]:
        await app.action_quit()
    else:
        add_message(
            f"❌ **Unknown command:** `/{cmd}`\n\nType `/help` for available commands",
            "error-message",
            True
        )
