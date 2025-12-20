"""Analysis result display formatters for pipeline results."""

from pathlib import Path
from typing import Callable, Any, Dict


async def display_pipeline_result(
    file_path: Path,
    pipeline_result: Dict[str, Any],
    add_message: Callable[[str, str, bool], None],
) -> None:
    """
    Display full pipeline execution results.

    Args:
        file_path: Path to analyzed file
        pipeline_result: PipelineRun result from orchestrator
        add_message: Function to add messages to chat
    """
    # Extract data from pipeline result
    status = pipeline_result.get("status", "unknown")
    duration_ms = pipeline_result.get("durationMs", 0)
    steps = pipeline_result.get("steps", [])
    summary = pipeline_result.get("summary", {})

    # Status emoji
    if status == "success":
        status_emoji = "✅"
    elif status == "failed":
        status_emoji = "❌"
    elif status == "stopped":
        status_emoji = "⚠️"
    else:
        status_emoji = "❓"

    # Build header
    message = f"""
{status_emoji} **Pipeline Complete**

**File:** `{file_path}`
**Status:** {status.upper()}
**Duration:** {duration_ms:.0f}ms
"""

    # Show validation frames execution
    validation_step = next((s for s in steps if s.get("stepType") == "validation"), None)
    if validation_step:
        message += "\n**Validation Frames:**\n"
        sub_steps = validation_step.get("subSteps", [])

        for sub_step in sub_steps:
            frame_name = sub_step.get("frameName", "Unknown")
            frame_status = sub_step.get("status", "unknown")
            is_blocker = sub_step.get("isBlocker", False)
            issue_count = sub_step.get("issuesFound", 0)

            # Frame emoji
            if frame_status == "passed":
                frame_emoji = "✅"
            elif frame_status == "failed":
                frame_emoji = "❌"
            else:
                frame_emoji = "⚠️"

            blocker_text = " (BLOCKER)" if is_blocker else ""
            message += f"  {frame_emoji} **{frame_name}**{blocker_text}: {issue_count} issues\n"

    # Show summary
    if summary:
        message += f"""
**Summary:**
- Total Issues: {summary.get('totalIssues', 0)}
- Critical: {summary.get('critical', 0)}
- High: {summary.get('high', 0)}
- Medium: {summary.get('medium', 0)}
- Low: {summary.get('low', 0)}
"""

    # Show recommendations if any
    recommendations = pipeline_result.get("recommendations", [])
    if recommendations:
        message += "\n**Recommendations:**\n"
        for idx, rec in enumerate(recommendations[:3], 1):
            message += f"{idx}. {rec}\n"

    add_message(message.strip(), "assistant-message", True)


async def show_mock_analysis_result(
    file_path: Path,
    add_message: Callable[[str, str, bool], None],
) -> None:
    """
    Show mock analysis result (placeholder).

    Args:
        file_path: Path to analyzed file
        add_message: Function to add messages to chat
    """
    result = f"""
✅ **Analysis Complete**

**File:** `{file_path}`
**Lines:** 150
**Issues Found:** 0

**Validation Frames:**
- 🔐 Security Analysis: ✅ Pass
- ⚡ Chaos Engineering: ✅ Pass
- 🎲 Fuzz Testing: ✅ Pass
- 📐 Property Testing: ✅ Pass
- 💪 Stress Testing: ✅ Pass

**Status:** Ready for production! 🎉
    """
    add_message(result.strip(), "assistant-message", True)
