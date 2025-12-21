"""Scan command handler for Warden TUI."""

from pathlib import Path
from typing import TYPE_CHECKING, Callable

from ..display.scan import (
    display_scan_summary,
    show_mock_scan_result
)

if TYPE_CHECKING:
    from warden.pipeline.application.orchestrator import PipelineOrchestrator


async def handle_scan_command(
    args: str,
    project_root: Path,
    orchestrator: "PipelineOrchestrator | None",
    add_message: Callable[[str, str, bool], None],
) -> None:
    """
    Handle /scan command using full Warden pipeline.

    Args:
        args: Command arguments (path to scan)
        project_root: Project root directory
        orchestrator: PipelineOrchestrator instance
        add_message: Function to add messages to chat
    """

    scan_path = Path(args.strip()) if args else project_root

    if not scan_path.exists():
        add_message(
            f"❌ **Path not found:** `{scan_path}`",
            "error-message",
            True
        )
        return

    if not scan_path.is_dir():
        add_message(
            f"❌ **Not a directory:** `{scan_path}`\n\n"
            f"Use `/analyze` for single files.",
            "error-message",
            True
        )
        return

    add_message(
        f"🔍 **Scanning:** `{scan_path}`\n\n"
        f"Finding Python files and running full pipeline...",
        "system-message",
        True
    )

    # Use full pipeline if available
    if orchestrator:
        await _run_pipeline_scan(scan_path, orchestrator, add_message)
    else:
        add_message(
            "⚠️ **Pipeline not available**\n\n"
            "Full pipeline is not loaded. Showing mock result instead.",
            "error-message",
            True
        )
        await show_mock_scan_result(scan_path, add_message)


async def _run_pipeline_scan(
    scan_path: Path,
    orchestrator: "PipelineOrchestrator",
    add_message: Callable[[str, str, bool], None],
) -> None:
    """Run full pipeline scan on directory."""
    try:
        # Find all Python files
        py_files = list(scan_path.rglob("*.py"))

        if not py_files:
            add_message(
                f"⚠️ **No Python files found** in `{scan_path}`",
                "error-message",
                True
            )
            return

        # Update progress
        add_message(
            f"📊 Found {len(py_files)} Python files. Running full pipeline...",
            "system-message",
            True
        )

        # Run pipeline for each file
        results = []
        for file_path in py_files:
            try:
                with open(file_path) as f:
                    content = f.read()

                # Execute full pipeline
                pipeline_result = await orchestrator.execute(
                    file_path=str(file_path),
                    file_content=content,
                    language="python"
                )

                results.append({
                    "path": file_path,
                    "pipeline_result": pipeline_result
                })

            except Exception:
                # Skip files that can't be analyzed
                continue

        # Display aggregated scan summary
        await display_scan_summary(scan_path, results, add_message)

    except Exception as e:
        add_message(
            f"❌ **Scan failed**\n\n"
            f"Error: `{str(e)}`",
            "error-message",
            True
        )
