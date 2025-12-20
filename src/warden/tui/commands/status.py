"""Status command handler for Warden TUI."""

from pathlib import Path
from typing import Callable


def handle_status_command(
    project_root: Path,
    session_id: str | None,
    llm_available: bool,
    add_message: Callable[[str, str, bool], None],
) -> None:
    """
    Handle /status command.

    Args:
        project_root: Project root directory
        session_id: Current session ID
        llm_available: Whether LLM is available
        add_message: Function to add messages to chat
    """
    status = f"""
📊 **Warden Status**

**Project:** `{project_root.name}`
**Session ID:** `{session_id[:8] if session_id else 'N/A'}`
**LLM Status:** {'✅ Ready' if llm_available else '⚠️ AST-only mode'}

**Configuration:**
- Validation Frames: 5 enabled
- Auto-fix: Disabled
- Memory: Enabled (Qdrant)

**Statistics:**
- Files Analyzed: 0
- Issues Found: 0
- Fixes Applied: 0
    """
    add_message(status.strip(), "system-message", True)
