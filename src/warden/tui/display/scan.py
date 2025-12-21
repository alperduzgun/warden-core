"""Scan result display formatters for pipeline scan results."""

from pathlib import Path
from typing import Callable, List, Dict, Any


async def display_scan_summary(
    scan_path: Path,
    pipeline_result: Any,  # PipelineResult from orchestrator
    add_message: Callable[[str, str, bool], None],
) -> None:
    """
    Display aggregated scan results with visual hierarchy.

    Args:
        scan_path: Path that was scanned
        pipeline_result: PipelineResult from orchestrator.execute()
        add_message: Function to add messages to chat
    """
    from ..utils.formatter import TreeFormatter, ProgressBar

    # Extract statistics from PipelineResult
    total_issues = pipeline_result.total_findings
    critical = pipeline_result.critical_findings
    high = pipeline_result.high_findings
    medium = pipeline_result.medium_findings
    low = pipeline_result.low_findings

    files_analyzed = len(pipeline_result.frame_results)  # Approximate
    failed_frames = pipeline_result.frames_failed
    passed_frames = pipeline_result.frames_passed
    total_duration = pipeline_result.duration * 1000  # Convert to ms

    # Status emoji
    if failed_frames > 0:
        status_emoji = "⚠️"
    elif total_issues > 0:
        status_emoji = "🟡"
    else:
        status_emoji = "✅"

    # Build visual tree
    lines = []

    lines.append(f"{status_emoji} **Scan Complete**\n")
    lines.append(TreeFormatter.header(f"Scanned: {scan_path.name}"))
    lines.append(TreeFormatter.item(f"Frames Executed: **{pipeline_result.total_frames}**"))
    lines.append(TreeFormatter.item(f"Total Duration: {total_duration:.0f}ms"))
    lines.append("")

    # Pipeline status
    lines.append(TreeFormatter.header("Pipeline Status"))
    lines.append(TreeFormatter.item(f"✅ Passed: {passed_frames}"))
    if failed_frames > 0:
        lines.append(TreeFormatter.item(f"❌ Failed: {failed_frames}"))
    lines.append("")

    # Progress bar
    progress = ProgressBar.create(passed_frames, pipeline_result.total_frames)
    lines.append(TreeFormatter.item(progress))
    lines.append("")

    # Issues breakdown
    lines.append(TreeFormatter.header(f"Issues Found: {total_issues}"))

    if total_issues > 0:
        lines.append(TreeFormatter.item(f"🔴 Critical: {critical}"))
        lines.append(TreeFormatter.item(f"🟡 High: {high}"))
        lines.append(TreeFormatter.item(f"🟠 Medium: {medium}"))
        lines.append(TreeFormatter.item(f"⚪ Low: {low}"))
        lines.append("")

        # Show frames with most issues
        if pipeline_result.frame_results:
            lines.append(TreeFormatter.header("Frames with Issues"))
            for idx, frame_result in enumerate(pipeline_result.frame_results[:5], 1):
                if frame_result.issues_found > 0:
                    lines.append(TreeFormatter.item(
                        f"{idx}. `{frame_result.frame_name}`: {frame_result.issues_found} issues"
                    ))

            lines.append("")
            lines.append("💡 Use `/analyze <file>` for detailed frame-level analysis")
    else:
        lines.append(TreeFormatter.item("✅ No issues detected!"))
        lines.append("")
        lines.append("**All frames passed!**")

    add_message("\n".join(lines), "assistant-message", True)


async def show_mock_scan_result(
    scan_path: Path,
    add_message: Callable[[str, str, bool], None],
) -> None:
    """
    Show mock scan result with visual hierarchy.

    Args:
        scan_path: Path that was scanned
        add_message: Function to add messages to chat
    """
    from ..utils.formatter import TreeFormatter, ProgressBar

    lines = []
    lines.append("✅ **Scan Complete**\n")
    lines.append(TreeFormatter.header(f"Scanned: {scan_path.name}"))
    lines.append(TreeFormatter.item("Files Scanned: **42**"))
    lines.append(TreeFormatter.item("Total Lines: 5,240"))
    lines.append("")

    lines.append(TreeFormatter.header("Progress"))
    progress = ProgressBar.create(42, 42)
    lines.append(TreeFormatter.item(progress))
    lines.append("")

    lines.append(TreeFormatter.header("Issues Found: 3"))
    lines.append(TreeFormatter.item("🔴 Critical: 0"))
    lines.append(TreeFormatter.item("🟡 High: 1"))
    lines.append(TreeFormatter.item("🟠 Medium: 2"))
    lines.append(TreeFormatter.item("⚪ Low: 0"))
    lines.append("")

    lines.append(TreeFormatter.header("Top Issues"))
    lines.append(TreeFormatter.item("1. Missing error handling in `api/client.py:145`"))
    lines.append(TreeFormatter.item("2. Potential SQL injection in `db/query.py:87`"))
    lines.append(TreeFormatter.item("3. Unused import in `utils/helper.py:12`"))

    add_message("\n".join(lines), "assistant-message", True)
