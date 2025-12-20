"""Scan result display formatters for pipeline scan results."""

from pathlib import Path
from typing import Callable, List, Dict, Any


async def display_scan_summary(
    scan_path: Path,
    results: List[Dict[str, Any]],
    add_message: Callable[[str, str, bool], None],
) -> None:
    """
    Display aggregated scan results with visual hierarchy.

    Args:
        scan_path: Path that was scanned
        results: List of {path, pipeline_result} dictionaries
        add_message: Function to add messages to chat
    """
    from ..utils.formatter import TreeFormatter, ProgressBar

    files_analyzed = len(results)

    # Aggregate statistics
    total_issues = 0
    critical = 0
    high = 0
    medium = 0
    low = 0
    total_duration = 0

    failed_pipelines = 0
    stopped_pipelines = 0

    for result in results:
        pipeline_result = result.get("pipeline_result", {})
        summary = pipeline_result.get("summary", {})

        total_issues += summary.get("totalIssues", 0)
        critical += summary.get("critical", 0)
        high += summary.get("high", 0)
        medium += summary.get("medium", 0)
        low += summary.get("low", 0)
        total_duration += pipeline_result.get("durationMs", 0)

        status = pipeline_result.get("status", "unknown")
        if status == "failed":
            failed_pipelines += 1
        elif status == "stopped":
            stopped_pipelines += 1

    # Status emoji
    if failed_pipelines > 0 or stopped_pipelines > 0:
        status_emoji = "⚠️"
    elif total_issues > 0:
        status_emoji = "🟡"
    else:
        status_emoji = "✅"

    # Build visual tree
    lines = []

    lines.append(f"{status_emoji} **Scan Complete**\n")
    lines.append(TreeFormatter.header(f"Scanned: {scan_path.name}"))
    lines.append(TreeFormatter.item(f"Files Analyzed: **{files_analyzed}**"))
    lines.append(TreeFormatter.item(f"Total Duration: {total_duration:.0f}ms"))
    lines.append("")

    # Pipeline status
    completed = files_analyzed - failed_pipelines - stopped_pipelines
    lines.append(TreeFormatter.header("Pipeline Status"))
    lines.append(TreeFormatter.item(f"✅ Completed: {completed}"))
    if stopped_pipelines > 0:
        lines.append(TreeFormatter.item(f"⚠️  Stopped (Blocker): {stopped_pipelines}"))
    if failed_pipelines > 0:
        lines.append(TreeFormatter.item(f"❌ Failed: {failed_pipelines}"))
    lines.append("")

    # Progress bar
    progress = ProgressBar.create(completed, files_analyzed)
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

        # Show files with most issues
        files_with_issues = [
            {
                "path": r["path"],
                "issues": r["pipeline_result"].get("summary", {}).get("totalIssues", 0)
            }
            for r in results
            if r["pipeline_result"].get("summary", {}).get("totalIssues", 0) > 0
        ]
        files_with_issues.sort(key=lambda x: x["issues"], reverse=True)

        if files_with_issues:
            lines.append(TreeFormatter.header("Top Files with Issues"))
            for idx, file_info in enumerate(files_with_issues[:5], 1):
                file_name = Path(file_info["path"]).name
                issue_count = file_info["issues"]
                lines.append(TreeFormatter.item(f"{idx}. `{file_name}`: {issue_count} issues"))

            if total_issues > 5:
                lines.append("")
                lines.append("💡 Use `/analyze <file>` for detailed analysis")
    else:
        lines.append(TreeFormatter.item("✅ No issues detected!"))
        lines.append("")
        lines.append("**All files look good!**")

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
