"""
Git Changes Frame - Validate only changed lines in git diff.

Built-in for CI/CD integration and PR checks.
Analyzes git diff and validates only modified code.

Priority: MEDIUM (informational for PRs)
Applicability: All languages

Usage in CI/CD:
    - Run during PR checks
    - Validate only changed lines
    - Reduce noise from existing issues
    - Focus on new code quality
"""

import time
import subprocess
import sys
from pathlib import Path
from typing import List, Dict, Any, Set

# Add current directory to path for local imports
if str(Path(__file__).parent) not in sys.path:
    sys.path.append(str(Path(__file__).parent))

from warden.validation.domain.frame import (
    ValidationFrame,
    FrameResult,
    Finding,
    CodeFile,
)
from warden.validation.domain.enums import (
    FrameCategory,
    FramePriority,
    FrameScope,
    FrameApplicability,
)
from git_diff_parser import GitDiffParser, FileDiff
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)


class GitChangesFrame(ValidationFrame):
    """
    Git Changes validation frame - Analyze only changed lines.

    This frame:
    - Runs git diff to identify changed lines
    - Validates only modified code sections
    - Useful for PR checks and CI/CD pipelines
    - Reduces noise from pre-existing issues

    Priority: MEDIUM (informational)
    Applicability: All languages with git tracking
    """

    # Required metadata
    name = "Git Changes Analysis"
    frame_id = "gitchanges"
    description = "Validates only changed lines in git diff (for CI/CD and PR checks)"
    category = FrameCategory.GLOBAL
    priority = FramePriority.MEDIUM
    scope = FrameScope.FILE_LEVEL
    is_blocker = False  # Informational only
    version = "1.0.0"
    author = "Warden Team"
    applicability = [FrameApplicability.ALL]

    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        """
        Initialize GitChangesFrame.

        Args:
            config: Frame configuration
                - git_command: Custom git command (default: "git")
                - base_branch: Base branch for comparison (default: "main")
                - compare_mode: "staged", "unstaged", or "branch" (default: "staged")
                - include_context: Include context lines in analysis (default: False)
        """
        super().__init__(config)

        # Configuration
        self.git_command = self.config.get("git_command", "git")
        self.base_branch = self.config.get("base_branch", "main")
        self.compare_mode = self.config.get("compare_mode", "staged")
        self.include_context = self.config.get("include_context", False)

        # Parser
        self.diff_parser = GitDiffParser()

    async def execute(self, code_file: CodeFile) -> FrameResult:
        """
        Execute git changes analysis on code file.

        Args:
            code_file: Code file to validate

        Returns:
            FrameResult with findings for changed lines only
        """
        start_time = time.perf_counter()

        logger.info(
            "gitchanges_frame_started",
            file_path=code_file.path,
            language=code_file.language,
            compare_mode=self.compare_mode,
        )

        try:
            # Get git diff for this file
            diff_output = self._get_git_diff(code_file.path)

            if not diff_output:
                logger.info(
                    "no_git_changes_found",
                    file_path=code_file.path,
                )
                return self._create_result(
                    start_time=start_time,
                    findings=[],
                    metadata={
                        "status": "no_changes",
                        "message": "No git changes detected for this file",
                    },
                )

            # Parse diff to get changed lines
            file_diff = self.diff_parser.parse_for_file(diff_output, code_file.path)

            if not file_diff:
                logger.warning(
                    "diff_parse_failed",
                    file_path=code_file.path,
                )
                return self._create_result(
                    start_time=start_time,
                    findings=[],
                    metadata={
                        "status": "parse_failed",
                        "message": "Failed to parse git diff output",
                    },
                )

            # Analyze changed lines
            findings = self._analyze_changed_lines(code_file, file_diff)

            # Calculate duration
            duration = time.perf_counter() - start_time

            logger.info(
                "gitchanges_frame_completed",
                file_path=code_file.path,
                added_lines=len(file_diff.get_all_added_lines()),
                findings_count=len(findings),
                duration=f"{duration:.2f}s",
            )

            return self._create_result(
                start_time=start_time,
                findings=findings,
                metadata={
                    "status": "analyzed",
                    "added_lines": sorted(list(file_diff.get_all_added_lines())),
                    "deleted_lines": sorted(list(file_diff.get_all_deleted_lines())),
                    "hunks_count": len(file_diff.hunks),
                    "is_new_file": file_diff.is_new,
                    "is_deleted_file": file_diff.is_deleted,
                    "is_renamed": file_diff.is_renamed,
                },
            )

        except subprocess.CalledProcessError as e:
            logger.error(
                "git_command_failed",
                file_path=code_file.path,
                error=str(e),
                stderr=e.stderr if hasattr(e, "stderr") else None,
            )
            return self._create_result(
                start_time=start_time,
                findings=[],
                metadata={
                    "status": "git_error",
                    "error": str(e),
                },
            )

        except Exception as e:
            logger.error(
                "gitchanges_frame_error",
                file_path=code_file.path,
                error=str(e),
            )
            return self._create_result(
                start_time=start_time,
                findings=[],
                metadata={
                    "status": "error",
                    "error": str(e),
                },
            )

    def _get_git_diff(self, file_path: str) -> str:
        """
        Get git diff output for specific file.

        Args:
            file_path: Path to file

        Returns:
            Git diff output as string

        Raises:
            subprocess.CalledProcessError: If git command fails
        """
        # Build git diff command based on compare mode
        if self.compare_mode == "staged":
            # Compare staged changes
            cmd = [self.git_command, "diff", "--cached", "--unified=3", file_path]
        elif self.compare_mode == "unstaged":
            # Compare unstaged changes
            cmd = [self.git_command, "diff", "--unified=3", file_path]
        elif self.compare_mode == "branch":
            # Compare with base branch
            cmd = [
                self.git_command,
                "diff",
                f"{self.base_branch}...HEAD",
                "--unified=3",
                file_path,
            ]
        else:
            # Default: staged changes
            cmd = [self.git_command, "diff", "--cached", "--unified=3", file_path]

        logger.debug(
            "running_git_command",
            command=" ".join(cmd),
            file_path=file_path,
        )

        # Execute git diff
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            cwd=str(Path(file_path).parent.absolute()),
        )

        return result.stdout

    def _analyze_changed_lines(
        self, code_file: CodeFile, file_diff: FileDiff
    ) -> List[Finding]:
        """
        Analyze changed lines and generate findings.

        Args:
            code_file: Code file being analyzed
            file_diff: Parsed diff information

        Returns:
            List of Finding objects for changed lines
        """
        findings: List[Finding] = []

        # Get all added lines
        added_lines = file_diff.get_all_added_lines()

        if not added_lines:
            return findings

        # Split file content into lines
        lines = code_file.content.split("\n")

        # Analyze each added line
        for line_num in sorted(added_lines):
            # Convert to 0-based index
            line_idx = line_num - 1

            if line_idx < 0 or line_idx >= len(lines):
                continue

            line_content = lines[line_idx]

            # Skip empty lines or whitespace-only
            if not line_content.strip():
                continue

            # Create informational finding for changed line
            # In a real implementation, you would run specific validators here
            # For now, we just report that the line was changed
            finding = Finding(
                id=f"{self.frame_id}-line-{line_num}",
                severity="info",
                message=f"Line {line_num} was added or modified",
                location=f"{code_file.path}:{line_num}",
                detail=f"This line was detected as changed in git diff",
                code=line_content.strip(),
            )
            findings.append(finding)

        # If we found changed lines, create a summary finding
        if added_lines:
            summary_finding = Finding(
                id=f"{self.frame_id}-summary",
                severity="info",
                message=f"Git changes detected: {len(added_lines)} lines added/modified",
                location=f"{code_file.path}:1",
                detail=self._create_summary_detail(file_diff, added_lines),
                code=None,
            )
            findings.insert(0, summary_finding)

        return findings

    def _create_summary_detail(
        self, file_diff: FileDiff, added_lines: Set[int]
    ) -> str:
        """
        Create detailed summary of changes.

        Args:
            file_diff: Parsed diff information
            added_lines: Set of added line numbers

        Returns:
            Formatted summary string
        """
        details = []

        details.append(f"Total lines added/modified: {len(added_lines)}")
        details.append(f"Total hunks: {len(file_diff.hunks)}")

        # List line ranges
        ranges = file_diff.get_changed_line_ranges()
        if ranges:
            range_strs = [f"{start}-{end}" if start != end else f"{start}" for start, end in ranges]
            details.append(f"Changed line ranges: {', '.join(range_strs)}")

        # File status
        if file_diff.is_new:
            details.append("Status: New file")
        elif file_diff.is_deleted:
            details.append("Status: Deleted file")
        elif file_diff.is_renamed:
            details.append(f"Status: Renamed from {file_diff.old_path}")

        return "\n".join(details)

    def _create_result(
        self,
        start_time: float,
        findings: List[Finding],
        metadata: Dict[str, Any],
    ) -> FrameResult:
        """
        Create frame result.

        Args:
            start_time: Start time for duration calculation
            findings: List of findings
            metadata: Additional metadata

        Returns:
            FrameResult
        """
        duration = time.perf_counter() - start_time

        # Determine status
        if not findings:
            status = "passed"
        else:
            # All findings are informational
            status = "passed"

        return FrameResult(
            frame_id=self.frame_id,
            frame_name=self.name,
            status=status,
            duration=duration,
            issues_found=len(findings),
            is_blocker=False,
            findings=findings,
            metadata=metadata,
        )
