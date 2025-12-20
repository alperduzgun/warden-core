"""Analysis result display formatters for pipeline results."""

from pathlib import Path
from typing import Callable, Any, Dict


async def display_pipeline_result(
    file_path: Path,
    pipeline_result: Dict[str, Any],
    add_message: Callable[[str, str, bool], None],
) -> None:
    """
    Display full pipeline execution results with visual hierarchy.

    Args:
        file_path: Path to analyzed file
        pipeline_result: PipelineRun result from orchestrator
        add_message: Function to add messages to chat
    """
    from ..utils.formatter import TreeFormatter

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

    # Count lines
    try:
        with open(file_path) as f:
            line_count = len(f.readlines())
    except Exception:
        line_count = 0

    # Build visual tree
    lines = []

    # Header
    lines.append(f"{status_emoji} **Pipeline Complete**\n")
    lines.append(TreeFormatter.header(f"{file_path.name} ({line_count} lines)"))
    lines.append(TreeFormatter.item(f"Status: **{status.upper()}**"))
    lines.append(TreeFormatter.item(f"Duration: {duration_ms:.0f}ms"))
    lines.append("")

    # Pipeline stages
    lines.append(TreeFormatter.header("Pipeline Stages"))
    for idx, step in enumerate(steps, 1):
        step_type = step.get("stepType", "unknown")
        step_status = step.get("status", "unknown")
        step_duration = step.get("durationMs", 0)

        step_emoji = "✅" if step_status == "success" else "❌"
        lines.append(
            TreeFormatter.item(
                f"Stage {idx}/5: **{step_type.title()}** {step_emoji} ({step_duration:.0f}ms)"
            )
        )

        # Show validation frames details
        if step_type == "validation":
            sub_steps = step.get("subSteps", [])
            for sub_step in sub_steps:
                frame_name = sub_step.get("frameName", "Unknown")
                frame_status = sub_step.get("status", "unknown")
                is_blocker = sub_step.get("isBlocker", False)
                issue_count = sub_step.get("issuesFound", 0)
                frame_duration = sub_step.get("durationMs", 0)

                frame_emoji = "✅" if frame_status == "passed" else "❌"
                blocker_text = " **(BLOCKER)**" if is_blocker else ""

                lines.append(
                    TreeFormatter.item(
                        f"{frame_emoji} {frame_name}{blocker_text}: {issue_count} issues ({frame_duration:.0f}ms)",
                        level=2
                    )
                )

    # Summary
    if summary:
        total_issues = summary.get("totalIssues", 0)
        if total_issues > 0:
            lines.append("")
            lines.append(TreeFormatter.header("Issues Found"))
            lines.append(TreeFormatter.item(f"Total: **{total_issues}**"))
            lines.append(TreeFormatter.item(f"🔴 Critical: {summary.get('critical', 0)}"))
            lines.append(TreeFormatter.item(f"🟡 High: {summary.get('high', 0)}"))
            lines.append(TreeFormatter.item(f"🟠 Medium: {summary.get('medium', 0)}"))
            lines.append(TreeFormatter.item(f"⚪ Low: {summary.get('low', 0)}"))
        else:
            lines.append("")
            lines.append("✅ **No issues found!** Code looks good.")

    # Recommendations
    recommendations = pipeline_result.get("recommendations", [])
    if recommendations:
        lines.append("")
        lines.append(TreeFormatter.header("Recommendations"))
        for rec in recommendations[:3]:
            lines.append(TreeFormatter.item(rec))

    add_message("\n".join(lines), "assistant-message", True)


async def show_mock_analysis_result(
    file_path: Path,
    add_message: Callable[[str, str, bool], None],
) -> None:
    """
    Show mock analysis result with visual hierarchy.

    Args:
        file_path: Path to analyzed file
        add_message: Function to add messages to chat
    """
    from ..utils.formatter import TreeFormatter

    lines = []
    lines.append("✅ **Analysis Complete**\n")
    lines.append(TreeFormatter.header(f"{file_path.name} (150 lines)"))
    lines.append(TreeFormatter.item("Issues Found: **0**"))
    lines.append("")
    lines.append(TreeFormatter.header("Validation Frames"))
    lines.append(TreeFormatter.item("🔐 Security Analysis: ✅ Pass"))
    lines.append(TreeFormatter.item("⚡ Chaos Engineering: ✅ Pass"))
    lines.append(TreeFormatter.item("🎲 Fuzz Testing: ✅ Pass"))
    lines.append(TreeFormatter.item("📐 Property Testing: ✅ Pass"))
    lines.append(TreeFormatter.item("💪 Stress Testing: ✅ Pass"))
    lines.append("")
    lines.append("**Status:** Ready for production! 🎉")

    add_message("\n".join(lines), "assistant-message", True)
