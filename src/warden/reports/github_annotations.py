"""
GitHub Actions Annotations Generator for Warden.

Generates GitHub Actions workflow commands for inline code feedback:
- ::error - Critical and high severity issues
- ::warning - Medium severity issues
- ::notice - Low severity issues and informational messages
- ::group - Collapsible output sections

Reference: https://docs.github.com/en/actions/using-workflows/workflow-commands-for-github-actions
"""

from typing import List, Optional
from pathlib import Path

from warden.issues.domain.models import WardenIssue
from warden.issues.domain.enums import IssueSeverity
from warden.pipeline.domain.models import PipelineResult, FrameExecution


class GitHubAnnotations:
    """Generate GitHub Actions workflow command annotations."""

    @staticmethod
    def generate_issue_annotation(issue: WardenIssue) -> str:
        """
        Generate GitHub Actions annotation for a single issue.

        Args:
            issue: Warden issue to annotate

        Returns:
            GitHub Actions workflow command string
        """
        # Map severity to annotation level
        level_map = {
            IssueSeverity.CRITICAL: "error",
            IssueSeverity.HIGH: "error",
            IssueSeverity.MEDIUM: "warning",
            IssueSeverity.LOW: "notice",
        }
        level = level_map.get(issue.severity, "notice")

        # Build annotation parameters
        params = []
        if hasattr(issue, "file_path") and issue.file_path:
            params.append(f"file={issue.file_path}")

        if hasattr(issue, "line") and issue.line:
            params.append(f"line={issue.line}")

            # Add end line if available
            if hasattr(issue, "end_line") and issue.end_line:
                params.append(f"endLine={issue.end_line}")

        if hasattr(issue, "column") and issue.column:
            params.append(f"col={issue.column}")

            # Add end column if available
            if hasattr(issue, "end_column") and issue.end_column:
                params.append(f"endColumn={issue.end_column}")

        # Build message
        title_prefix = {
            IssueSeverity.CRITICAL: "🔴 CRITICAL",
            IssueSeverity.HIGH: "🟠 HIGH",
            IssueSeverity.MEDIUM: "🟡 MEDIUM",
            IssueSeverity.LOW: "🔵 LOW",
        }.get(issue.severity, "INFO")

        message = f"{title_prefix}: {issue.message}"
        if hasattr(issue, "rule_id") and issue.rule_id:
            message = f"[{issue.rule_id}] {message}"

        # Format annotation
        params_str = ",".join(params) if params else ""
        if params_str:
            return f"::{level} {params_str}::{message}"
        else:
            return f"::{level}::{message}"

    @staticmethod
    def generate_all_annotations(issues: List[WardenIssue]) -> List[str]:
        """
        Generate annotations for all issues.

        Args:
            issues: List of Warden issues

        Returns:
            List of GitHub Actions annotation strings
        """
        return [
            GitHubAnnotations.generate_issue_annotation(issue) for issue in issues
        ]

    @staticmethod
    def generate_summary_annotation(result: PipelineResult) -> List[str]:
        """
        Generate summary annotations for pipeline result.

        Args:
            result: Pipeline execution result

        Returns:
            List of summary annotation strings
        """
        annotations = []

        # Count issues by severity
        critical_count = sum(
            1 for i in result.all_issues if i.severity == IssueSeverity.CRITICAL
        )
        high_count = sum(
            1 for i in result.all_issues if i.severity == IssueSeverity.HIGH
        )
        medium_count = sum(
            1 for i in result.all_issues if i.severity == IssueSeverity.MEDIUM
        )
        low_count = sum(
            1 for i in result.all_issues if i.severity == IssueSeverity.LOW
        )
        total_issues = len(result.all_issues)

        # Critical blocker message
        if critical_count > 0:
            annotations.append(
                f"::error::❌ BLOCKER: {critical_count} critical security issues found! Review before merging."
            )

        # High severity warning
        if high_count > 0:
            annotations.append(
                f"::warning::⚠️  {high_count} high severity issues require attention"
            )

        # Overall summary
        if total_issues == 0:
            annotations.append("::notice::✅ No issues found! Code is clean.")
        else:
            summary = f"Total: {total_issues} issues (Critical: {critical_count}, High: {high_count}, Medium: {medium_count}, Low: {low_count})"
            annotations.append(f"::notice::{summary}")

        return annotations

    @staticmethod
    def generate_group_annotations(
        frame_executions: List[FrameExecution],
    ) -> List[str]:
        """
        Generate grouped annotations by validation frame.

        Args:
            frame_executions: List of frame execution results

        Returns:
            List of grouped annotation strings
        """
        annotations = []

        for frame in frame_executions:
            frame_name = frame.frame_name
            frame_status = "✅" if frame.status == "completed" else "❌"

            # Start group
            annotations.append(f"::group::{frame_status} {frame_name}")

            # Frame-specific issues
            frame_issues = getattr(frame, "issues", [])
            if frame_issues:
                for issue in frame_issues:
                    annotations.append(
                        GitHubAnnotations.generate_issue_annotation(issue)
                    )
            else:
                annotations.append("::notice::No issues found in this frame")

            # End group
            annotations.append("::endgroup::")

        return annotations

    @staticmethod
    def print_annotations(
        issues: Optional[List[WardenIssue]] = None,
        result: Optional[PipelineResult] = None,
        grouped: bool = False,
    ) -> None:
        """
        Print annotations to stdout (for GitHub Actions).

        Args:
            issues: List of issues to annotate (if not using full result)
            result: Full pipeline result (includes summary and grouping)
            grouped: Whether to group by validation frame
        """
        if result:
            # Print summary first
            for annotation in GitHubAnnotations.generate_summary_annotation(result):
                print(annotation, flush=True)

            # Print grouped or flat annotations
            if grouped and hasattr(result, "frame_executions"):
                for annotation in GitHubAnnotations.generate_group_annotations(
                    result.frame_executions
                ):
                    print(annotation, flush=True)
            else:
                for annotation in GitHubAnnotations.generate_all_annotations(
                    result.all_issues
                ):
                    print(annotation, flush=True)

        elif issues:
            # Print individual issue annotations
            for annotation in GitHubAnnotations.generate_all_annotations(issues):
                print(annotation, flush=True)

    @staticmethod
    def set_output(name: str, value: str) -> None:
        """
        Set GitHub Actions output variable.

        Args:
            name: Output variable name
            value: Output value
        """
        print(f"::set-output name={name}::{value}", flush=True)

    @staticmethod
    def set_environment_variable(name: str, value: str) -> None:
        """
        Set GitHub Actions environment variable.

        Args:
            name: Environment variable name
            value: Variable value
        """
        # Modern syntax (GitHub Actions)
        github_env_path = os.getenv("GITHUB_ENV")
        if github_env_path and Path(github_env_path).exists():
            with open(github_env_path, "a") as f:
                f.write(f"{name}={value}\n")
        else:
            # Fallback to old syntax
            print(f"::set-env name={name}::{value}", flush=True)

    @staticmethod
    def add_mask(value: str) -> None:
        """
        Mask a value in GitHub Actions logs.

        Args:
            value: Value to mask (e.g., secret, token)
        """
        print(f"::add-mask::{value}", flush=True)

    @staticmethod
    def stop_commands(token: str) -> None:
        """
        Stop processing workflow commands.

        Args:
            token: Stop token
        """
        print(f"::stop-commands::{token}", flush=True)

    @staticmethod
    def resume_commands(token: str) -> None:
        """
        Resume processing workflow commands.

        Args:
            token: Resume token (must match stop token)
        """
        print(f"::{token}::", flush=True)


# Import os for environment variables
import os
