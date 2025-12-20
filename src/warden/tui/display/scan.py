"""Scan result display formatters for pipeline scan results."""

from pathlib import Path
from typing import Callable, List, Dict, Any


async def display_scan_summary(
    scan_path: Path,
    results: List[Dict[str, Any]],
    add_message: Callable[[str, str, bool], None],
) -> None:
    """
    Display aggregated scan results from multiple pipeline executions.

    Args:
        scan_path: Path that was scanned
        results: List of {path, pipeline_result} dictionaries
        add_message: Function to add messages to chat
    """
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

    message = f"""
{status_emoji} **Scan Complete**

**Path:** `{scan_path}`
**Files Analyzed:** {files_analyzed}
**Total Duration:** {total_duration:.0f}ms
**Pipeline Status:**
- Completed: {files_analyzed - failed_pipelines - stopped_pipelines}
- Stopped (Blocker): {stopped_pipelines}
- Failed: {failed_pipelines}

**Issues Found:** {total_issues}
"""

    if total_issues > 0:
        message += f"""
**Breakdown:**
- 🔴 Critical: {critical}
- 🟡 High: {high}
- 🟠 Medium: {medium}
- ⚪ Low: {low}
"""

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
            message += "\n**Top Files with Issues:**\n\n"
            for idx, file_info in enumerate(files_with_issues[:5], 1):
                file_name = Path(file_info["path"]).name
                issue_count = file_info["issues"]
                message += f"{idx}. `{file_name}`: {issue_count} issues\n"

        if total_issues > 5:
            message += f"\n💡 Use `/analyze <file>` to see detailed analysis for specific files.\n"
    else:
        message += "\n✅ **No issues found!** All files look good.\n"

    add_message(message.strip(), "assistant-message", True)


async def show_mock_scan_result(
    scan_path: Path,
    add_message: Callable[[str, str, bool], None],
) -> None:
    """
    Show mock scan result (placeholder).

    Args:
        scan_path: Path that was scanned
        add_message: Function to add messages to chat
    """
    result = f"""
✅ **Scan Complete**

**Path:** `{scan_path}`
**Files Scanned:** 42
**Total Lines:** 5,240
**Issues Found:** 3

**Summary:**
- 🔴 Critical: 0
- 🟡 High: 1
- 🟢 Medium: 2
- ⚪ Low: 0

**Top Issues:**
1. Missing error handling in `api/client.py:145`
2. Potential SQL injection in `db/query.py:87`
3. Unused import in `utils/helper.py:12`

Run `/fix` to auto-repair these issues.
    """
    add_message(result.strip(), "assistant-message", True)
