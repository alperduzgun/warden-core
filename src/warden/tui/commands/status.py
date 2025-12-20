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
    Handle /status command with visual hierarchy.

    Args:
        project_root: Project root directory
        session_id: Current session ID
        llm_available: Whether LLM is available
        add_message: Function to add messages to chat
    """
    from ..utils.formatter import TreeFormatter

    lines = []

    lines.append("📊 **Warden Status**\n")

    # Project info
    lines.append(TreeFormatter.header("Project"))
    lines.append(TreeFormatter.item(f"Name: **{project_root.name}**"))
    lines.append(TreeFormatter.item(f"Path: `{project_root}`"))

    # Count Python files
    try:
        py_files = list(project_root.rglob("*.py"))
        file_count = len(py_files)
    except Exception:
        file_count = 0

    lines.append(TreeFormatter.item(f"Python Files: {file_count}"))
    lines.append("")

    # Session info
    lines.append(TreeFormatter.header("Session"))
    if session_id:
        lines.append(TreeFormatter.item(f"ID: `{session_id[:8]}...`"))
    else:
        lines.append(TreeFormatter.item("ID: Not initialized"))

    llm_status = "✅ Ready" if llm_available else "⚠️ AST-only mode"
    lines.append(TreeFormatter.item(f"LLM: {llm_status}"))
    lines.append("")

    # Pipeline configuration
    lines.append(TreeFormatter.header("Pipeline Configuration"))
    lines.append(TreeFormatter.item("Active config: **quick-scan**"))
    lines.append(TreeFormatter.item("Frames enabled: **6**"))
    lines.append(TreeFormatter.item("🔐 SecurityFrame (blocker)", level=2))
    lines.append(TreeFormatter.item("⚡ ChaosFrame", level=2))
    lines.append(TreeFormatter.item("🎲 FuzzFrame", level=2))
    lines.append(TreeFormatter.item("📐 PropertyFrame", level=2))
    lines.append(TreeFormatter.item("🏗️  ArchitecturalFrame", level=2))
    lines.append(TreeFormatter.item("💪 StressFrame", level=2))
    lines.append("")

    # Statistics
    lines.append(TreeFormatter.header("Statistics (Session)"))
    lines.append(TreeFormatter.item("Files Analyzed: 0"))
    lines.append(TreeFormatter.item("Issues Found: 0"))
    lines.append(TreeFormatter.item("Frames Executed: 0"))

    add_message("\n".join(lines), "system-message", True)
