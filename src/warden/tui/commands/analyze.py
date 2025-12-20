"""Analyze command handler for Warden TUI."""

from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from warden.core.pipeline.orchestrator import PipelineOrchestrator


async def handle_analyze_command(
    args: str,
    orchestrator: "PipelineOrchestrator | None",
    add_message: Callable[[str, str, bool], None],
) -> None:
    """
    Handle /analyze command using full Warden pipeline.

    Args:
        args: Command arguments (file path)
        orchestrator: PipelineOrchestrator instance
        add_message: Function to add messages to chat
    """
    from ..display.analysis import (
        display_pipeline_result,
        show_mock_analysis_result
    )

    if not args:
        add_message(
            "❌ **Missing file path**\n\nUsage: `/analyze <file>`",
            "error-message",
            True
        )
        return

    file_path = Path(args.strip())

    if not file_path.exists():
        add_message(
            f"❌ **File not found:** `{file_path}`",
            "error-message",
            True
        )
        return

    # Check if it's a Python file
    if file_path.suffix not in ['.py']:
        add_message(
            f"⚠️ **Warning:** Only Python files (`.py`) are currently supported.\n\n"
            f"File: `{file_path}`",
            "error-message",
            True
        )
        return

    add_message(
        f"🔍 **Analyzing:** `{file_path.name}`\n\n"
        f"Running full Warden pipeline (Analyze → Classify → Validate → Fortify → Clean)...",
        "system-message",
        True
    )

    # Use full pipeline if available
    if orchestrator:
        await _run_full_pipeline(file_path, orchestrator, add_message)
    else:
        add_message(
            "⚠️ **Pipeline not available**\n\n"
            "Full pipeline is not loaded. Showing mock result instead.",
            "error-message",
            True
        )
        await show_mock_analysis_result(file_path, add_message)


async def _run_full_pipeline(
    file_path: Path,
    orchestrator: "PipelineOrchestrator",
    add_message: Callable[[str, str, bool], None],
) -> None:
    """Run full Warden pipeline."""
    try:
        # Read file
        with open(file_path) as f:
            content = f.read()

        # Run full pipeline (5 stages + validation frames)
        result = await orchestrator.execute(
            file_path=str(file_path),
            file_content=content,
            language="python"
        )

        # Display pipeline results
        await display_pipeline_result(file_path, result, add_message)

    except Exception as e:
        add_message(
            f"❌ **Pipeline execution failed**\n\n"
            f"Error: `{str(e)}`",
            "error-message",
            True
        )
