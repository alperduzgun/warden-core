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
        pipeline_result = result.get("pipeline_result")
        if not pipeline_result:
            continue

        total_duration += pipeline_result.duration_ms

        # Count issues from analysis_result
        analysis_result = pipeline_result.analysis_result or {}
        issues = analysis_result.get("issues", [])
        total_issues += len(issues)

        # Count by severity
        for issue in issues:
            severity = issue.get("severity", "medium").lower()
            if severity == "critical":
                critical += 1
            elif severity == "high":
                high += 1
            elif severity == "medium":
                medium += 1
            elif severity == "low":
                low += 1

        # Check pipeline status
        if not pipeline_result.success:
            failed_pipelines += 1
        elif pipeline_result.blocker_failures:
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
        files_with_issues = []
        for r in results:
            pipeline_result = r.get("pipeline_result")
            if not pipeline_result or not pipeline_result.analysis_result:
                continue
            issue_count = len(pipeline_result.analysis_result.get("issues", []))
            if issue_count > 0:
                files_with_issues.append({
                    "path": r["path"],
                    "issues": issue_count
                })
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
