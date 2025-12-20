"""Analysis result display formatters for pipeline results."""

from pathlib import Path
from typing import Callable, Any, Dict


async def display_pipeline_result(
    file_path: Path,
    pipeline_result: Any,  # PipelineResult object
    add_message: Callable[[str, str, bool], None],
) -> None:
    """
    Display full pipeline execution results with visual hierarchy.

    Args:
        file_path: Path to analyzed file
        pipeline_result: PipelineResult object from orchestrator
        add_message: Function to add messages to chat
    """
    from ..utils.formatter import TreeFormatter

    # Extract data from PipelineResult object
    status = "success" if pipeline_result.success else "failed"
    duration_ms = pipeline_result.duration_ms
    analysis_result = pipeline_result.analysis_result or {}
    validation_summary = pipeline_result.validation_summary or {}

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

    # Analysis stage
    if analysis_result:
        score = analysis_result.get("score", 0)
        issue_count = len(analysis_result.get("issues", []))
        lines.append(TreeFormatter.item(f"Stage 1/5: **Analysis** ✅ (Score: {score:.1f}, Issues: {issue_count})"))

    # Classification stage
    if pipeline_result.classification_result:
        recommended_frames = pipeline_result.classification_result.get("recommendedFrames", [])
        lines.append(TreeFormatter.item(f"Stage 2/5: **Classification** ✅ (Recommended: {len(recommended_frames)} frames)"))

    # Validation stage
    if validation_summary:
        total_frames = validation_summary.get("totalFrames", 0)
        passed_frames = validation_summary.get("passedFrames", 0)
        failed_frames = validation_summary.get("failedFrames", 0)

        stage_emoji = "✅" if failed_frames == 0 else "⚠️"
        lines.append(
            TreeFormatter.item(
                f"Stage 3/5: **Validation** {stage_emoji} ({passed_frames}/{total_frames} passed)"
            )
        )

        # Show validation frame details
        frame_results = validation_summary.get("results", [])
        for frame_result in frame_results:
            frame_name = frame_result.get("name", "Unknown")
            frame_passed = frame_result.get("passed", False)
            is_blocker = frame_result.get("isBlocker", False)
            frame_duration = frame_result.get("executionTimeMs", 0)

            frame_emoji = "✅" if frame_passed else "❌"
            blocker_text = " **(BLOCKER)**" if is_blocker else ""

            lines.append(
                TreeFormatter.item(
                    f"{frame_emoji} {frame_name}{blocker_text} ({frame_duration:.0f}ms)",
                    level=2
                )
            )

    # Issues from analysis
    issues = analysis_result.get("issues", [])
    if len(issues) > 0:
        lines.append("")
        lines.append(TreeFormatter.header("Issues Found"))
        lines.append(TreeFormatter.item(f"Total: **{len(issues)}**"))

        # Count by severity
        severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for issue in issues:
            severity = issue.get("severity", "medium").lower()
            if severity in severity_counts:
                severity_counts[severity] += 1

        if severity_counts["critical"] > 0:
            lines.append(TreeFormatter.item(f"🔴 Critical: {severity_counts['critical']}"))
        if severity_counts["high"] > 0:
            lines.append(TreeFormatter.item(f"🟡 High: {severity_counts['high']}"))
        if severity_counts["medium"] > 0:
            lines.append(TreeFormatter.item(f"🟠 Medium: {severity_counts['medium']}"))
        if severity_counts["low"] > 0:
            lines.append(TreeFormatter.item(f"⚪ Low: {severity_counts['low']}"))
    else:
        lines.append("")
        lines.append("✅ **No issues found!** Code looks good.")

    # Blocker failures
    blocker_failures = pipeline_result.blocker_failures
    if blocker_failures:
        lines.append("")
        lines.append(TreeFormatter.header("⚠️ Blocker Failures"))
        for blocker in blocker_failures:
            lines.append(TreeFormatter.item(f"❌ {blocker}"))

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
