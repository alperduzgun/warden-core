"""
Incremental Analysis for Warden CI/CD.

Optimizes CI performance by analyzing only changed files:
- Git diff detection (PR, push to branch)
- File filtering based on changes
- Cache validation results for unchanged files
- Smart change detection (content, dependencies)

Benefits:
- Faster CI runs (analyze only what changed)
- Reduced resource usage
- Quicker feedback for developers
"""

import os
import subprocess
from typing import List, Set, Optional, Dict, Any
from pathlib import Path
from dataclasses import dataclass
from enum import Enum

import structlog

logger = structlog.get_logger(__name__)


class ChangeType(Enum):
    """Type of file change in git."""

    ADDED = "A"
    MODIFIED = "M"
    DELETED = "D"
    RENAMED = "R"
    COPIED = "C"
    UNMERGED = "U"


@dataclass
class FileChange:
    """Represents a file change in git."""

    file_path: Path
    change_type: ChangeType
    old_path: Optional[Path] = None  # For renames
    lines_added: int = 0
    lines_deleted: int = 0


class IncrementalAnalyzer:
    """
    Incremental analysis engine for CI/CD.

    Detects changed files and filters analysis scope.
    """

    def __init__(
        self,
        base_branch: str = "main",
        include_untracked: bool = False,
        max_file_age_days: int = 7,
    ):
        """
        Initialize incremental analyzer.

        Args:
            base_branch: Base branch to compare against (default: main)
            include_untracked: Include untracked files in analysis
            max_file_age_days: Maximum file age to consider (default: 7 days)
        """
        self.base_branch = base_branch
        self.include_untracked = include_untracked
        self.max_file_age_days = max_file_age_days

        logger.info(
            "incremental_analyzer_initialized",
            base_branch=base_branch,
            include_untracked=include_untracked,
        )

    def get_changed_files(
        self,
        repo_path: Optional[Path] = None,
        file_extensions: Optional[List[str]] = None,
    ) -> List[FileChange]:
        """
        Get list of changed files in the repository.

        Args:
            repo_path: Path to git repository (default: current directory)
            file_extensions: Filter by file extensions (e.g., ['.py', '.js'])

        Returns:
            List of file changes
        """
        repo_path = repo_path or Path.cwd()

        logger.info(
            "detecting_changed_files",
            repo_path=str(repo_path),
            base_branch=self.base_branch,
        )

        # Detect CI environment
        ci_env = self._detect_ci_environment()

        if ci_env == "github":
            changes = self._get_github_changes(repo_path)
        elif ci_env == "gitlab":
            changes = self._get_gitlab_changes(repo_path)
        elif ci_env == "azure":
            changes = self._get_azure_changes(repo_path)
        else:
            # Generic git diff
            changes = self._get_git_diff_changes(repo_path)

        # Filter by file extensions if specified
        if file_extensions:
            changes = [
                c
                for c in changes
                if c.file_path.suffix.lower() in file_extensions
            ]

        logger.info(
            "changed_files_detected",
            total_changes=len(changes),
            file_extensions=file_extensions,
        )

        return changes

    def _detect_ci_environment(self) -> str:
        """Detect CI/CD platform from environment variables."""
        if os.getenv("GITHUB_ACTIONS") == "true":
            return "github"
        elif os.getenv("GITLAB_CI") == "true":
            return "gitlab"
        elif os.getenv("TF_BUILD") == "True":
            return "azure"
        return "generic"

    def _get_github_changes(self, repo_path: Path) -> List[FileChange]:
        """Get changes in GitHub Actions context."""
        base_ref = os.getenv("GITHUB_BASE_REF")  # For PR
        head_ref = os.getenv("GITHUB_HEAD_REF")  # For PR

        if base_ref and head_ref:
            # Pull request - compare PR branch with base
            logger.info("github_pr_detected", base=base_ref, head=head_ref)
            return self._get_git_diff_changes(
                repo_path, base_ref=f"origin/{base_ref}"
            )
        else:
            # Push event - compare with previous commit
            logger.info("github_push_detected")
            return self._get_git_diff_changes(repo_path, base_ref="HEAD^")

    def _get_gitlab_changes(self, repo_path: Path) -> List[FileChange]:
        """Get changes in GitLab CI context."""
        merge_request_target = os.getenv("CI_MERGE_REQUEST_TARGET_BRANCH_NAME")

        if merge_request_target:
            # Merge request
            logger.info("gitlab_mr_detected", target=merge_request_target)
            return self._get_git_diff_changes(
                repo_path, base_ref=f"origin/{merge_request_target}"
            )
        else:
            # Pipeline on branch
            before_sha = os.getenv("CI_COMMIT_BEFORE_SHA")
            if before_sha and before_sha != "0000000000000000000000000000000000000000":
                return self._get_git_diff_changes(repo_path, base_ref=before_sha)
            return self._get_git_diff_changes(repo_path, base_ref="HEAD^")

    def _get_azure_changes(self, repo_path: Path) -> List[FileChange]:
        """Get changes in Azure Pipelines context."""
        pr_source_branch = os.getenv("SYSTEM_PULLREQUEST_SOURCEBRANCH")
        pr_target_branch = os.getenv("SYSTEM_PULLREQUEST_TARGETBRANCH")

        if pr_source_branch and pr_target_branch:
            # Pull request
            logger.info(
                "azure_pr_detected", source=pr_source_branch, target=pr_target_branch
            )
            return self._get_git_diff_changes(repo_path, base_ref=pr_target_branch)
        else:
            # Regular build
            return self._get_git_diff_changes(repo_path, base_ref="HEAD^")

    def _get_git_diff_changes(
        self, repo_path: Path, base_ref: Optional[str] = None
    ) -> List[FileChange]:
        """
        Get file changes using git diff.

        Args:
            repo_path: Path to repository
            base_ref: Base reference to compare against

        Returns:
            List of file changes
        """
        if not base_ref:
            base_ref = f"origin/{self.base_branch}"

        try:
            # Get diff with numstat for line counts
            result = subprocess.run(
                ["git", "diff", "--numstat", "--diff-filter=AMDRC", base_ref, "HEAD"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=True,
            )

            changes = []
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue

                parts = line.split("\t")
                if len(parts) < 3:
                    continue

                added = int(parts[0]) if parts[0] != "-" else 0
                deleted = int(parts[1]) if parts[1] != "-" else 0
                file_path = Path(parts[2])

                # Detect change type
                if not file_path.exists():
                    change_type = ChangeType.DELETED
                elif added > 0 and deleted == 0:
                    change_type = ChangeType.ADDED
                else:
                    change_type = ChangeType.MODIFIED

                changes.append(
                    FileChange(
                        file_path=file_path,
                        change_type=change_type,
                        lines_added=added,
                        lines_deleted=deleted,
                    )
                )

            # Include untracked files if enabled
            if self.include_untracked:
                untracked_result = subprocess.run(
                    ["git", "ls-files", "--others", "--exclude-standard"],
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                    check=True,
                )

                for line in untracked_result.stdout.strip().split("\n"):
                    if line:
                        changes.append(
                            FileChange(
                                file_path=Path(line),
                                change_type=ChangeType.ADDED,
                            )
                        )

            return changes

        except subprocess.CalledProcessError as e:
            logger.error(
                "git_diff_failed",
                error=str(e),
                stderr=e.stderr,
            )
            # Fallback: return all files
            return self._get_all_files(repo_path)

    def _get_all_files(self, repo_path: Path) -> List[FileChange]:
        """
        Fallback: Get all tracked files.

        Args:
            repo_path: Repository path

        Returns:
            List of all files as changes
        """
        try:
            result = subprocess.run(
                ["git", "ls-files"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=True,
            )

            return [
                FileChange(
                    file_path=Path(line),
                    change_type=ChangeType.MODIFIED,
                )
                for line in result.stdout.strip().split("\n")
                if line
            ]
        except subprocess.CalledProcessError:
            logger.error("git_ls_files_failed")
            return []

    def should_analyze_file(self, file_path: Path, changes: List[FileChange]) -> bool:
        """
        Determine if a file should be analyzed.

        Args:
            file_path: File to check
            changes: List of detected changes

        Returns:
            True if file should be analyzed
        """
        # Check if file is in changes
        changed_files = {c.file_path for c in changes}

        if file_path in changed_files:
            return True

        # Check if file is in the same directory as a changed file
        # (dependency detection)
        for change in changes:
            if file_path.parent == change.file_path.parent:
                logger.debug(
                    "file_in_changed_directory",
                    file=str(file_path),
                    changed_sibling=str(change.file_path),
                )
                return True

        return False

    def filter_files_for_analysis(
        self,
        all_files: List[Path],
        changes: Optional[List[FileChange]] = None,
    ) -> List[Path]:
        """
        Filter files to analyze based on changes.

        Args:
            all_files: All files in the project
            changes: Detected file changes (auto-detected if None)

        Returns:
            Filtered list of files to analyze
        """
        if changes is None:
            changes = self.get_changed_files()

        if not changes:
            logger.warning("no_changes_detected_analyzing_all")
            return all_files

        # Filter files
        filtered = [f for f in all_files if self.should_analyze_file(f, changes)]

        logger.info(
            "files_filtered_for_analysis",
            total_files=len(all_files),
            filtered_files=len(filtered),
            reduction_percent=round(
                (1 - len(filtered) / len(all_files)) * 100 if all_files else 0, 2
            ),
        )

        return filtered

    def get_change_summary(self, changes: List[FileChange]) -> Dict[str, Any]:
        """
        Get summary statistics for changes.

        Args:
            changes: List of file changes

        Returns:
            Summary dictionary
        """
        total_added = sum(c.lines_added for c in changes)
        total_deleted = sum(c.lines_deleted for c in changes)

        by_type = {}
        for change_type in ChangeType:
            count = sum(1 for c in changes if c.change_type == change_type)
            if count > 0:
                by_type[change_type.name.lower()] = count

        return {
            "total_files": len(changes),
            "total_lines_added": total_added,
            "total_lines_deleted": total_deleted,
            "by_type": by_type,
        }
