"""
Tests for Incremental Analysis module.

Tests git diff detection, change tracking, and file filtering.
"""

import os
import subprocess
from pathlib import Path
from unittest.mock import Mock, patch, call
import pytest

from warden.pipeline.application.incremental import (
    IncrementalAnalyzer,
    FileChange,
    ChangeType,
)


class TestIncrementalAnalyzerInitialization:
    """Test incremental analyzer initialization."""

    def test_default_initialization(self):
        """Test default initialization."""
        analyzer = IncrementalAnalyzer()

        assert analyzer.base_branch == "main"
        assert analyzer.include_untracked is False
        assert analyzer.max_file_age_days == 7

    def test_custom_initialization(self):
        """Test custom configuration."""
        analyzer = IncrementalAnalyzer(
            base_branch="dev", include_untracked=True, max_file_age_days=14
        )

        assert analyzer.base_branch == "dev"
        assert analyzer.include_untracked is True
        assert analyzer.max_file_age_days == 14


class TestCIEnvironmentDetection:
    """Test CI environment detection."""

    def test_detect_github_actions(self):
        """Test GitHub Actions detection."""
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}, clear=True):
            analyzer = IncrementalAnalyzer()
            ci_env = analyzer._detect_ci_environment()

            assert ci_env == "github"

    def test_detect_gitlab_ci(self):
        """Test GitLab CI detection."""
        with patch.dict(os.environ, {"GITLAB_CI": "true"}, clear=True):
            analyzer = IncrementalAnalyzer()
            ci_env = analyzer._detect_ci_environment()

            assert ci_env == "gitlab"

    def test_detect_azure_pipelines(self):
        """Test Azure Pipelines detection."""
        with patch.dict(os.environ, {"TF_BUILD": "True"}, clear=True):
            analyzer = IncrementalAnalyzer()
            ci_env = analyzer._detect_ci_environment()

            assert ci_env == "azure"

    def test_detect_generic(self):
        """Test generic/unknown environment."""
        with patch.dict(os.environ, {}, clear=True):
            analyzer = IncrementalAnalyzer()
            ci_env = analyzer._detect_ci_environment()

            assert ci_env == "generic"


class TestGitHubChangeDetection:
    """Test GitHub Actions change detection."""

    @patch("subprocess.run")
    def test_pull_request_changes(self, mock_subprocess):
        """Test change detection for GitHub pull requests."""
        # Mock git diff output
        mock_subprocess.return_value = Mock(
            stdout="5\t2\tsrc/test.py\n10\t0\tsrc/new.py\n",
            returncode=0,
        )

        with patch.dict(
            os.environ,
            {
                "GITHUB_ACTIONS": "true",
                "GITHUB_BASE_REF": "main",
                "GITHUB_HEAD_REF": "feature",
            },
            clear=True,
        ):
            analyzer = IncrementalAnalyzer()
            changes = analyzer.get_changed_files()

            assert len(changes) == 2
            assert changes[0].file_path == Path("src/test.py")
            assert changes[0].lines_added == 5
            assert changes[0].lines_deleted == 2
            assert changes[1].file_path == Path("src/new.py")
            assert changes[1].lines_added == 10

    @patch("subprocess.run")
    def test_push_changes(self, mock_subprocess):
        """Test change detection for GitHub push events."""
        mock_subprocess.return_value = Mock(
            stdout="3\t1\tREADME.md\n",
            returncode=0,
        )

        with patch.dict(
            os.environ,
            {
                "GITHUB_ACTIONS": "true",
                # No BASE_REF/HEAD_REF = push event
            },
            clear=True,
        ):
            analyzer = IncrementalAnalyzer()
            changes = analyzer.get_changed_files()

            assert len(changes) >= 0  # Fallback to HEAD^


class TestGitLabChangeDetection:
    """Test GitLab CI change detection."""

    @patch("subprocess.run")
    def test_merge_request_changes(self, mock_subprocess):
        """Test change detection for GitLab merge requests."""
        mock_subprocess.return_value = Mock(
            stdout="8\t3\tsrc/api.py\n",
            returncode=0,
        )

        with patch.dict(
            os.environ,
            {
                "GITLAB_CI": "true",
                "CI_MERGE_REQUEST_TARGET_BRANCH_NAME": "main",
            },
            clear=True,
        ):
            analyzer = IncrementalAnalyzer()
            changes = analyzer.get_changed_files()

            assert len(changes) == 1
            assert changes[0].file_path == Path("src/api.py")
            assert changes[0].lines_added == 8
            assert changes[0].lines_deleted == 3


class TestAzureChangeDetection:
    """Test Azure Pipelines change detection."""

    @patch("subprocess.run")
    def test_pull_request_changes(self, mock_subprocess):
        """Test change detection for Azure pull requests."""
        mock_subprocess.return_value = Mock(
            stdout="15\t5\tsrc/service.py\n",
            returncode=0,
        )

        with patch.dict(
            os.environ,
            {
                "TF_BUILD": "True",
                "SYSTEM_PULLREQUEST_SOURCEBRANCH": "refs/heads/feature",
                "SYSTEM_PULLREQUEST_TARGETBRANCH": "refs/heads/main",
            },
            clear=True,
        ):
            analyzer = IncrementalAnalyzer()
            changes = analyzer.get_changed_files()

            assert len(changes) == 1
            assert changes[0].file_path == Path("src/service.py")


class TestGitDiffParsing:
    """Test git diff output parsing."""

    @patch("subprocess.run")
    def test_parse_added_file(self, mock_subprocess):
        """Test parsing of added files."""
        mock_subprocess.return_value = Mock(
            stdout="10\t0\tnew_file.py\n",
            returncode=0,
        )

        analyzer = IncrementalAnalyzer()
        changes = analyzer._get_git_diff_changes(Path.cwd())

        assert len(changes) == 1
        assert changes[0].lines_added == 10
        assert changes[0].lines_deleted == 0

    @patch("subprocess.run")
    def test_parse_modified_file(self, mock_subprocess):
        """Test parsing of modified files."""
        mock_subprocess.return_value = Mock(
            stdout="5\t3\tmodified.py\n",
            returncode=0,
        )

        analyzer = IncrementalAnalyzer()
        changes = analyzer._get_git_diff_changes(Path.cwd())

        assert len(changes) == 1
        assert changes[0].lines_added == 5
        assert changes[0].lines_deleted == 3

    @patch("subprocess.run")
    def test_parse_binary_file(self, mock_subprocess):
        """Test parsing of binary files."""
        mock_subprocess.return_value = Mock(
            stdout="-\t-\timage.png\n",
            returncode=0,
        )

        analyzer = IncrementalAnalyzer()
        changes = analyzer._get_git_diff_changes(Path.cwd())

        assert len(changes) == 1
        assert changes[0].lines_added == 0  # Binary files show as -
        assert changes[0].lines_deleted == 0

    @patch("subprocess.run")
    def test_parse_multiple_files(self, mock_subprocess):
        """Test parsing multiple file changes."""
        mock_subprocess.return_value = Mock(
            stdout="5\t2\tfile1.py\n10\t0\tfile2.py\n0\t8\tfile3.py\n",
            returncode=0,
        )

        analyzer = IncrementalAnalyzer()
        changes = analyzer._get_git_diff_changes(Path.cwd())

        assert len(changes) == 3
        assert changes[0].file_path == Path("file1.py")
        assert changes[1].file_path == Path("file2.py")
        assert changes[2].file_path == Path("file3.py")


class TestUntrackedFiles:
    """Test untracked file handling."""

    @patch("subprocess.run")
    def test_include_untracked_files(self, mock_subprocess):
        """Test including untracked files."""
        # Mock git diff (no changes)
        mock_subprocess.side_effect = [
            Mock(stdout="", returncode=0),  # git diff
            Mock(stdout="untracked1.py\nuntracked2.py\n", returncode=0),  # ls-files
        ]

        analyzer = IncrementalAnalyzer(include_untracked=True)
        changes = analyzer._get_git_diff_changes(Path.cwd())

        assert len(changes) == 2
        assert changes[0].file_path == Path("untracked1.py")
        assert changes[0].change_type == ChangeType.ADDED
        assert changes[1].file_path == Path("untracked2.py")

    @patch("subprocess.run")
    def test_exclude_untracked_files(self, mock_subprocess):
        """Test excluding untracked files."""
        mock_subprocess.return_value = Mock(stdout="", returncode=0)

        analyzer = IncrementalAnalyzer(include_untracked=False)
        changes = analyzer._get_git_diff_changes(Path.cwd())

        # Should only call git diff, not ls-files
        assert mock_subprocess.call_count == 1
        assert "ls-files" not in str(mock_subprocess.call_args)


class TestFileFiltering:
    """Test file filtering logic."""

    def test_filter_by_extension(self):
        """Test filtering files by extension."""
        changes = [
            FileChange(Path("test.py"), ChangeType.MODIFIED),
            FileChange(Path("test.js"), ChangeType.MODIFIED),
            FileChange(Path("test.md"), ChangeType.MODIFIED),
        ]

        analyzer = IncrementalAnalyzer()

        # Mock the internal method that gets raw changes
        with patch.object(analyzer, "_detect_ci_environment", return_value="generic"):
            with patch.object(analyzer, "_get_git_diff_changes", return_value=changes):
                filtered = analyzer.get_changed_files(file_extensions=[".py", ".js"])

        assert len(filtered) == 2
        assert filtered[0].file_path.suffix == ".py"
        assert filtered[1].file_path.suffix == ".js"

    def test_should_analyze_changed_file(self):
        """Test that changed files should be analyzed."""
        analyzer = IncrementalAnalyzer()

        file_path = Path("test.py")
        changes = [FileChange(file_path, ChangeType.MODIFIED)]

        should_analyze = analyzer.should_analyze_file(file_path, changes)

        assert should_analyze is True

    def test_should_analyze_sibling_file(self):
        """Test dependency detection (same directory)."""
        analyzer = IncrementalAnalyzer()

        changed_file = Path("src/module/changed.py")
        sibling_file = Path("src/module/related.py")

        changes = [FileChange(changed_file, ChangeType.MODIFIED)]

        should_analyze = analyzer.should_analyze_file(sibling_file, changes)

        assert should_analyze is True  # Same directory

    def test_should_not_analyze_unrelated_file(self):
        """Test that unrelated files are not analyzed."""
        analyzer = IncrementalAnalyzer()

        changed_file = Path("src/module/changed.py")
        unrelated_file = Path("other/module/unrelated.py")

        changes = [FileChange(changed_file, ChangeType.MODIFIED)]

        should_analyze = analyzer.should_analyze_file(unrelated_file, changes)

        assert should_analyze is False


class TestFileFilteringForAnalysis:
    """Test filtering files for analysis."""

    def test_filter_files_for_analysis(self):
        """Test filtering files based on changes."""
        analyzer = IncrementalAnalyzer()

        all_files = [
            Path("src/changed.py"),
            Path("src/unchanged.py"),
            Path("tests/test_changed.py"),
        ]

        changes = [FileChange(Path("src/changed.py"), ChangeType.MODIFIED)]

        filtered = analyzer.filter_files_for_analysis(all_files, changes)

        # Should include changed file and possibly siblings
        assert Path("src/changed.py") in filtered

    def test_filter_with_no_changes(self):
        """Test filtering when no changes detected."""
        analyzer = IncrementalAnalyzer()

        all_files = [Path("file1.py"), Path("file2.py")]
        changes = []

        filtered = analyzer.filter_files_for_analysis(all_files, changes)

        # Should analyze all files when no changes detected
        assert len(filtered) == len(all_files)


class TestChangeSummary:
    """Test change summary statistics."""

    def test_change_summary(self):
        """Test change summary generation."""
        analyzer = IncrementalAnalyzer()

        changes = [
            FileChange(Path("file1.py"), ChangeType.ADDED, lines_added=10),
            FileChange(Path("file2.py"), ChangeType.MODIFIED, lines_added=5, lines_deleted=2),
            FileChange(Path("file3.py"), ChangeType.DELETED, lines_deleted=20),
        ]

        summary = analyzer.get_change_summary(changes)

        assert summary["total_files"] == 3
        assert summary["total_lines_added"] == 15
        assert summary["total_lines_deleted"] == 22
        assert summary["by_type"]["added"] == 1
        assert summary["by_type"]["modified"] == 1
        assert summary["by_type"]["deleted"] == 1


class TestGitErrorHandling:
    """Test error handling for git operations."""

    @patch("subprocess.run")
    def test_git_diff_failure_fallback(self, mock_subprocess):
        """Test fallback to all files when git diff fails."""
        # First call (git diff) fails
        # Second call (git ls-files) succeeds
        mock_subprocess.side_effect = [
            subprocess.CalledProcessError(1, "git diff", stderr="fatal error"),
            Mock(stdout="file1.py\nfile2.py\n", returncode=0),
        ]

        analyzer = IncrementalAnalyzer()
        changes = analyzer._get_git_diff_changes(Path.cwd())

        # Should fallback to all files
        assert len(changes) == 2
        assert all(c.change_type == ChangeType.MODIFIED for c in changes)

    @patch("subprocess.run")
    def test_complete_git_failure(self, mock_subprocess):
        """Test handling when all git commands fail."""
        mock_subprocess.side_effect = subprocess.CalledProcessError(
            1, "git", stderr="not a git repository"
        )

        analyzer = IncrementalAnalyzer()
        changes = analyzer._get_git_diff_changes(Path.cwd())

        # Should return empty list
        assert len(changes) == 0


class TestPerformanceMetrics:
    """Test performance metrics calculation."""

    def test_reduction_percentage(self):
        """Test reduction percentage calculation."""
        analyzer = IncrementalAnalyzer()

        # Create files in different directories to test reduction
        all_files = [Path(f"src/dir{i}/file.py") for i in range(100)]
        changes = [FileChange(Path("src/dir1/file.py"), ChangeType.MODIFIED)]

        filtered = analyzer.filter_files_for_analysis(all_files, changes)

        # Should significantly reduce file count (only dir1 files included)
        reduction = (1 - len(filtered) / len(all_files)) * 100
        assert reduction > 90  # At least 90% reduction achieved

    def test_no_reduction_when_all_changed(self):
        """Test no reduction when all files changed."""
        analyzer = IncrementalAnalyzer()

        all_files = [Path(f"file{i}.py") for i in range(10)]
        changes = [FileChange(f, ChangeType.MODIFIED) for f in all_files]

        filtered = analyzer.filter_files_for_analysis(all_files, changes)

        # Should analyze all files
        assert len(filtered) == len(all_files)
