"""Scan command handler for Warden TUI."""

from pathlib import Path
from typing import TYPE_CHECKING, Callable
import time

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
    app = None,
) -> None:
    """
    Handle /scan command using full Warden pipeline.

    Args:
        args: Command arguments (path to scan)
        project_root: Project root directory
        orchestrator: PipelineOrchestrator instance
        add_message: Function to add messages to chat
        app: Textual App instance for UI updates
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
        await _run_pipeline_scan(scan_path, orchestrator, add_message, app)
    else:
        add_message(
            "⚠️ **Pipeline not available**\n\n"
            "Pipeline initialization failed. Possible causes:\n"
            "- Missing validation frames in config\n"
            "- Config file loading error\n"
            "- Import errors in frame modules\n\n"
            "Check console output for details. Showing mock result instead.",
            "error-message",
            True
        )
        await show_mock_scan_result(scan_path, add_message)


async def _run_pipeline_scan(
    scan_path: Path,
    orchestrator: "PipelineOrchestrator",
    add_message: Callable[[str, str, bool], None],
    app = None,
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

        # Create CodeFile objects from discovered files
        from warden.validation.domain.frame import CodeFile

        code_files = []
        for file_path in py_files:
            try:
                with open(file_path) as f:
                    content = f.read()

                code_file = CodeFile(
                    path=str(file_path),
                    content=content,
                    language="python",
                    framework=None,
                    size_bytes=len(content.encode('utf-8')),
                )
                code_files.append(code_file)
            except Exception:
                # Skip files that can't be read
                continue

        if not code_files:
            add_message(
                "❌ **No files could be loaded**",
                "error-message",
                True
            )
            return

        # Import asyncio for sleep to yield control
        import asyncio
        from textual.widgets import Static

        # Track progress state
        pipeline_start_time = [0.0]
        current_frame = [""]
        frame_start_time = [0.0]
        progress_widget = [None]  # Reference to progress widget

        # Create progress callback for UI updates
        def progress_callback(event: str, data: dict) -> None:
            """Handle progress updates from pipeline."""
            if event == "pipeline_started":
                pipeline_start_time[0] = time.time()
                add_message(
                    f"🚀 **Pipeline started**\n\n"
                    f"Running {data['total_frames']} frames on {data['total_files']} files...",
                    "system-message",
                    True
                )

                # Create live progress widget
                if app:
                    try:
                        chat_area = app.query_one("#chat-area")
                        widget = Static("⏳ Starting...", classes="system-message", id="scan-progress")
                        chat_area.mount(widget)
                        progress_widget[0] = widget
                        chat_area.scroll_end(animate=False)
                    except Exception:
                        pass

            elif event == "frame_started":
                # Update current frame name
                current_frame[0] = data['frame_name']
                frame_start_time[0] = time.time()

            elif event == "frame_completed":
                # Update completed frame message
                progress = f"{data['frames_completed']}/{data['total_frames']}"
                status_emoji = "✅" if data['frame_status'] == "completed" else "⚠️"
                add_message(
                    f"{status_emoji} **{data['frame_name']}** [{progress}] "
                    f"Issues: {data['issues_found']} | {data['duration']:.2f}s",
                    "system-message",
                    True
                )

                # Update progress widget for next frame (if not last)
                if data['frames_completed'] < data['total_frames']:
                    # We don't know the next frame name yet, so just show progress
                    current_frame[0] = f"[{data['frames_completed'] + 1}/{data['total_frames']}]"
                    frame_start_time[0] = time.time()
                elif progress_widget[0]:
                    # Remove progress widget when done
                    try:
                        progress_widget[0].remove()
                        progress_widget[0] = None
                    except Exception:
                        pass

            # Update live progress widget
            if progress_widget[0]:
                try:
                    elapsed = time.time() - pipeline_start_time[0]
                    frame_elapsed = time.time() - frame_start_time[0] if frame_start_time[0] > 0 else 0

                    progress_text = f"⏳ Running {current_frame[0]} | Total: {elapsed:.1f}s"
                    if frame_elapsed > 0:
                        progress_text += f" | Frame: {frame_elapsed:.1f}s"

                    progress_widget[0].update(progress_text)
                except Exception:
                    pass

            # Force UI refresh if app is available
            if app:
                try:
                    app.refresh()
                except Exception:
                    pass  # Ignore refresh errors

        # Set callback on orchestrator temporarily
        original_callback = orchestrator.progress_callback
        orchestrator.progress_callback = progress_callback

        # Create background task to update progress widget continuously
        update_running = [True]

        async def update_progress_continuously():
            """Update progress widget every 100ms."""
            spinner_chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
            spinner_idx = [0]

            while update_running[0]:
                if progress_widget[0]:
                    try:
                        elapsed = time.time() - pipeline_start_time[0]
                        frame_elapsed = time.time() - frame_start_time[0] if frame_start_time[0] > 0 else 0

                        # Animated spinner
                        spinner = spinner_chars[spinner_idx[0] % len(spinner_chars)]
                        spinner_idx[0] += 1

                        # Build progress text
                        if current_frame[0]:
                            progress_text = f"{spinner} **Running:** {current_frame[0]}"
                            if frame_elapsed > 0:
                                progress_text += f" | ⏱️  {frame_elapsed:.1f}s"
                            progress_text += f" | Total: {elapsed:.0f}s"
                        else:
                            progress_text = f"{spinner} Starting... | {elapsed:.1f}s"

                        progress_widget[0].update(progress_text)
                        if app:
                            app.refresh()
                    except Exception:
                        pass

                await asyncio.sleep(0.1)  # Update every 100ms

        # Start background update task
        update_task = asyncio.create_task(update_progress_continuously())

        try:
            # Execute pipeline on all files at once
            pipeline_result = await orchestrator.execute(code_files)

            # Display aggregated scan summary
            await display_scan_summary(scan_path, pipeline_result, add_message)
        finally:
            # Stop background update task
            update_running[0] = False
            try:
                await update_task
            except Exception:
                pass

            # Remove progress widget if still exists
            if progress_widget[0]:
                try:
                    progress_widget[0].remove()
                except Exception:
                    pass

            # Restore original callback
            orchestrator.progress_callback = original_callback

    except Exception as e:
        add_message(
            f"❌ **Scan failed**\n\n"
            f"Error: `{str(e)}`",
            "error-message",
            True
        )
