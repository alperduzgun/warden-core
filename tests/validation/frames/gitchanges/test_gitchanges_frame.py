"""
Unit tests for GitChangesFrame.

Tests:
- Git diff parsing
- Changed line detection
- Frame execution
- Error handling
- Different compare modes
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path
from warden.validation.domain.frame import CodeFile, FrameResult
import sys

@pytest.fixture(scope="module")
def gitchanges_components():
    from warden.validation.infrastructure.frame_registry import FrameRegistry
    registry = FrameRegistry()
    registry.discover_all()
    frame_cls = registry.get_frame_by_id("gitchanges")
    if not frame_cls:
        pytest.skip("GitChangesFrame not found")
    
    # Extract helper classes from the module where GitChangesFrame is defined
    # or from the git_diff_parser module directly (since we used absolute import)
    
    import sys
    if "git_diff_parser" in sys.modules:
        parser_module = sys.modules["git_diff_parser"]
        return {
            "GitChangesFrame": frame_cls,
            "GitDiffParser": getattr(parser_module, "GitDiffParser"),
            "FileDiff": getattr(parser_module, "FileDiff"),
            "DiffHunk": getattr(parser_module, "DiffHunk"),
        }
    
    # Fallback to frame module if strict isolation used
    module = sys.modules[frame_cls.__module__]
    return {
        "GitChangesFrame": frame_cls,
        "GitDiffParser": getattr(module, "GitDiffParser"),
        "FileDiff": getattr(module, "FileDiff"),
        "DiffHunk": getattr(module, "DiffHunk"),
    }


# Sample git diff output for testing
SAMPLE_DIFF = """diff --git a/test_file.py b/test_file.py
index abc123..def456 100644
--- a/test_file.py
+++ b/test_file.py
@@ -10,7 +10,8 @@ def foo():
     context line 1
     context line 2
-    old line
+    new line
+    another new line
     context line 3
"""

SAMPLE_DIFF_NEW_FILE = """diff --git a/new_file.py b/new_file.py
new file mode 100644
index 0000000..abc123
--- /dev/null
+++ b/new_file.py
@@ -0,0 +1,3 @@
+def new_function():
+    return True
+
"""

SAMPLE_DIFF_MULTIPLE_HUNKS = """diff --git a/multi.py b/multi.py
index abc123..def456 100644
--- a/multi.py
+++ b/multi.py
@@ -5,3 +5,4 @@ def first():
     line 1
     line 2
+    added line 3
@@ -20,2 +21,3 @@ def second():
     another line
+    added here too
"""


class TestGitDiffParser:
    """Test suite for GitDiffParser."""

    @pytest.fixture(autouse=True)
    def setup(self, gitchanges_components):
        self.GitDiffParser = gitchanges_components["GitDiffParser"]
        self.FileDiff = gitchanges_components["FileDiff"]
        self.DiffHunk = gitchanges_components["DiffHunk"]

    def test_parse_empty_diff(self):
        """Test parsing empty diff output."""
        parser = self.GitDiffParser()
        result = parser.parse("")
        assert result == []

    def test_parse_single_file_diff(self):
        """Test parsing diff for single file."""
        parser = self.GitDiffParser()
        diffs = parser.parse(SAMPLE_DIFF)

        assert len(diffs) == 1
        file_diff = diffs[0]
        assert file_diff.file_path == "test_file.py"
        assert len(file_diff.hunks) == 1

    def test_parse_hunk_header(self):
        """Test parsing hunk header information."""
        parser = self.GitDiffParser()
        diffs = parser.parse(SAMPLE_DIFF)

        hunk = diffs[0].hunks[0]
        assert hunk.old_start == 10
        assert hunk.old_count == 7
        assert hunk.new_start == 10
        assert hunk.new_count == 8

    def test_parse_added_lines(self):
        """Test detection of added lines."""
        parser = self.GitDiffParser()
        diffs = parser.parse(SAMPLE_DIFF)

        added_lines = diffs[0].get_all_added_lines()
        # Lines 12 and 13 were added (new line + another new line)
        assert 12 in added_lines
        assert 13 in added_lines
        assert len(added_lines) == 2

    def test_parse_deleted_lines(self):
        """Test detection of deleted lines."""
        parser = self.GitDiffParser()
        diffs = parser.parse(SAMPLE_DIFF)

        deleted_lines = diffs[0].get_all_deleted_lines()
        # Line 12 was deleted (old line)
        assert 12 in deleted_lines
        assert len(deleted_lines) == 1

    def test_parse_new_file(self):
        """Test parsing new file diff."""
        parser = self.GitDiffParser()
        diffs = parser.parse(SAMPLE_DIFF_NEW_FILE)

        assert len(diffs) == 1
        file_diff = diffs[0]
        assert file_diff.is_new is True
        assert file_diff.file_path == "new_file.py"

    def test_parse_multiple_hunks(self):
        """Test parsing file with multiple hunks."""
        parser = self.GitDiffParser()
        diffs = parser.parse(SAMPLE_DIFF_MULTIPLE_HUNKS)

        assert len(diffs) == 1
        file_diff = diffs[0]
        assert len(file_diff.hunks) == 2

        # Check both hunks have changes
        assert len(file_diff.hunks[0].added_lines) > 0
        assert len(file_diff.hunks[1].added_lines) > 0

    def test_parse_for_file(self):
        """Test parsing diff for specific file."""
        parser = self.GitDiffParser()
        file_diff = parser.parse_for_file(SAMPLE_DIFF, "test_file.py")

        assert file_diff is not None
        assert file_diff.file_path == "test_file.py"

    def test_parse_for_file_not_found(self):
        """Test parsing diff when file not in diff."""
        parser = self.GitDiffParser()
        file_diff = parser.parse_for_file(SAMPLE_DIFF, "nonexistent.py")

        assert file_diff is None

    def test_get_changed_line_ranges(self):
        """Test getting changed line ranges."""
        parser = self.GitDiffParser()
        diffs = parser.parse(SAMPLE_DIFF)

        ranges = diffs[0].get_changed_line_ranges()
        assert len(ranges) == 1
        assert ranges[0] == (12, 13)  # Lines 12-13 were changed

    def test_to_json_serialization(self):
        """Test JSON serialization of diff objects."""
        parser = self.GitDiffParser()
        diffs = parser.parse(SAMPLE_DIFF)

        json_data = diffs[0].to_json()
        assert "filePath" in json_data
        assert "hunks" in json_data
        assert "addedLines" in json_data
        assert json_data["filePath"] == "test_file.py"


class TestDiffHunk:
    """Test suite for DiffHunk class."""

    @pytest.fixture(autouse=True)
    def setup(self, gitchanges_components):
        self.DiffHunk = gitchanges_components["DiffHunk"]

    def test_get_changed_line_range_with_additions(self):
        """Test line range calculation with additions."""
        hunk = self.DiffHunk(
            old_start=10,
            old_count=5,
            new_start=10,
            new_count=6,
            added_lines={13, 14, 15},
            deleted_lines=set(),
            context_lines={10, 11, 12},
        )

        start, end = hunk.get_changed_line_range()
        assert start == 13
        assert end == 15

    def test_get_changed_line_range_no_additions(self):
        """Test line range calculation with no additions."""
        hunk = self.DiffHunk(
            old_start=10,
            old_count=5,
            new_start=10,
            new_count=4,
            added_lines=set(),
            deleted_lines={12},
            context_lines={10, 11},
        )

        start, end = hunk.get_changed_line_range()
        assert start == 10
        assert end == 10


class TestFileDiff:
    """Test suite for FileDiff class."""

    @pytest.fixture(autouse=True)
    def setup(self, gitchanges_components):
        self.FileDiff = gitchanges_components["FileDiff"]
        self.DiffHunk = gitchanges_components["DiffHunk"]

    def test_get_all_added_lines(self):
        """Test aggregation of added lines across hunks."""
        hunk1 = self.DiffHunk(10, 5, 10, 6, {13}, set(), set())
        hunk2 = self.DiffHunk(20, 3, 21, 4, {23}, set(), set())

        file_diff = self.FileDiff(file_path="test.py", hunks=[hunk1, hunk2])
        added = file_diff.get_all_added_lines()

        assert 13 in added
        assert 23 in added
        assert len(added) == 2

    def test_get_all_deleted_lines(self):
        """Test aggregation of deleted lines across hunks."""
        hunk1 = self.DiffHunk(10, 5, 10, 4, set(), {12}, set())
        hunk2 = self.DiffHunk(20, 3, 19, 2, set(), {21}, set())

        file_diff = self.FileDiff(file_path="test.py", hunks=[hunk1, hunk2])
        deleted = file_diff.get_all_deleted_lines()

        assert 12 in deleted
        assert 21 in deleted
        assert len(deleted) == 2


class TestGitChangesFrame:
    """Test suite for GitChangesFrame."""

    @pytest.fixture(autouse=True)
    def setup(self, gitchanges_components):
        self.GitChangesFrame = gitchanges_components["GitChangesFrame"]
        self.FileDiff = gitchanges_components["FileDiff"]
        self.DiffHunk = gitchanges_components["DiffHunk"]

    def test_frame_metadata(self):
        """Test frame has correct metadata."""
        frame = self.GitChangesFrame()

        assert frame.name == "Git Changes Analysis"
        assert frame.is_blocker is False
        assert frame.priority.value == 3  # MEDIUM

    def test_frame_initialization_default_config(self):
        """Test frame initialization with default config."""
        frame = self.GitChangesFrame()

        assert frame.git_command == "git"
        assert frame.base_branch == "main"
        assert frame.compare_mode == "staged"
        assert frame.include_context is False

    def test_frame_initialization_custom_config(self):
        """Test frame initialization with custom config."""
        config = {
            "git_command": "custom-git",
            "base_branch": "develop",
            "compare_mode": "branch",
            "include_context": True,
        }
        frame = self.GitChangesFrame(config=config)

        assert frame.git_command == "custom-git"
        assert frame.base_branch == "develop"
        assert frame.compare_mode == "branch"
        assert frame.include_context is True

    @pytest.mark.asyncio
    async def test_execute_no_changes(self):
        """Test execution when no git changes detected."""
        frame = self.GitChangesFrame()
        code_file = CodeFile(
            path="test_file.py",
            content="def foo():\n    return True\n",
            language="python",
        )

        # Mock git diff to return empty output
        with patch.object(frame, "_get_git_diff", return_value=""):
            result = await frame.execute(code_file)

        assert result.status == "passed"
        assert result.issues_found == 0
        assert result.metadata["status"] == "no_changes"

    @pytest.mark.asyncio
    async def test_execute_with_changes(self):
        """Test execution with git changes detected."""
        frame = self.GitChangesFrame()
        code_file = CodeFile(
            path="test_file.py",
            content="def foo():\n    context line 1\n    context line 2\n    new line\n    another new line\n    context line 3\n",
            language="python",
        )

        # Mock git diff to return sample diff
        with patch.object(frame, "_get_git_diff", return_value=SAMPLE_DIFF):
            result = await frame.execute(code_file)

        assert result.status == "passed"
        assert result.issues_found > 0
        assert result.metadata["status"] == "analyzed"
        assert len(result.metadata["added_lines"]) == 2

    @pytest.mark.asyncio
    async def test_execute_git_error(self):
        """Test execution when git command fails."""
        frame = self.GitChangesFrame()
        code_file = CodeFile(
            path="test_file.py",
            content="def foo():\n    return True\n",
            language="python",
        )

        # Mock git diff to raise subprocess error
        import subprocess

        with patch.object(
            frame,
            "_get_git_diff",
            side_effect=subprocess.CalledProcessError(1, "git"),
        ):
            result = await frame.execute(code_file)

        assert result.status == "passed"
        assert result.metadata["status"] == "git_error"

    @pytest.mark.asyncio
    async def test_analyze_changed_lines(self):
        """Test analysis of changed lines."""
        frame = self.GitChangesFrame()
        code_file = CodeFile(
            path="test_file.py",
            content="line 1\nline 2\nline 3\nline 4\n",
            language="python",
        )

        # Create mock file diff
        hunk = self.DiffHunk(
            old_start=1,
            old_count=3,
            new_start=1,
            new_count=4,
            added_lines={3, 4},
            deleted_lines=set(),
            context_lines={1, 2},
        )
        file_diff = self.FileDiff(file_path="test_file.py", hunks=[hunk])

        findings = frame._analyze_changed_lines(code_file, file_diff)

        # Should have summary + individual line findings
        assert len(findings) > 0
        assert findings[0].severity == "info"

    def test_get_git_diff_staged_mode(self):
        """Test git diff command for staged mode."""
        frame = self.GitChangesFrame(config={"compare_mode": "staged"})

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(stdout="diff output")

            frame._get_git_diff("/path/to/file.py")

            # Verify correct command was called
            call_args = mock_run.call_args[0][0]
            assert "git" in call_args
            assert "diff" in call_args
            assert "--cached" in call_args

    def test_get_git_diff_unstaged_mode(self):
        """Test git diff command for unstaged mode."""
        frame = self.GitChangesFrame(config={"compare_mode": "unstaged"})

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(stdout="diff output")

            frame._get_git_diff("/path/to/file.py")

            # Verify correct command was called
            call_args = mock_run.call_args[0][0]
            assert "git" in call_args
            assert "diff" in call_args
            assert "--cached" not in call_args

    def test_get_git_diff_branch_mode(self):
        """Test git diff command for branch mode."""
        frame = self.GitChangesFrame(
            config={"compare_mode": "branch", "base_branch": "develop"}
        )

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(stdout="diff output")

            frame._get_git_diff("/path/to/file.py")

            # Verify correct command was called
            call_args = mock_run.call_args[0][0]
            assert "git" in call_args
            assert "diff" in call_args
            assert "develop...HEAD" in call_args

    def test_create_summary_detail(self):
        """Test summary detail creation."""
        frame = self.GitChangesFrame()

        hunk = self.DiffHunk(10, 5, 10, 6, {13, 14}, set(), set())
        file_diff = self.FileDiff(file_path="test.py", hunks=[hunk])
        added_lines = {13, 14}

        summary = frame._create_summary_detail(file_diff, added_lines)

        assert "Total lines added/modified: 2" in summary
        assert "Total hunks: 1" in summary
        assert "Changed line ranges:" in summary

    def test_create_summary_detail_new_file(self):
        """Test summary detail for new file."""
        frame = self.GitChangesFrame()

        hunk = self.DiffHunk(0, 0, 1, 3, {1, 2, 3}, set(), set())
        file_diff = self.FileDiff(file_path="new.py", is_new=True, hunks=[hunk])
        added_lines = {1, 2, 3}

        summary = frame._create_summary_detail(file_diff, added_lines)

        assert "Status: New file" in summary

    def test_frame_id_generation(self):
        """Test frame ID is generated correctly."""
        frame = self.GitChangesFrame()
        assert frame.frame_id == "gitchanges"


# Integration test with mocked subprocess
class TestGitChangesFrameIntegration:
    """Integration tests for GitChangesFrame."""

    @pytest.fixture(autouse=True)
    def setup(self, gitchanges_components):
        self.GitChangesFrame = gitchanges_components["GitChangesFrame"]


    @pytest.mark.asyncio
    async def test_full_workflow_with_real_diff(self):
        """Test full workflow with realistic git diff."""
        frame = self.GitChangesFrame()

        # Create realistic code file
        code_file = CodeFile(
            path="example.py",
            content="""def example():
    context line 1
    context line 2
    new line
    another new line
    context line 3
""",
            language="python",
        )

        # Mock subprocess to return sample diff
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(stdout=SAMPLE_DIFF)

            result = await frame.execute(code_file)

            # Verify result
            assert isinstance(result, FrameResult)
            assert result.frame_id == "gitchanges"
            assert result.frame_name == "Git Changes Analysis"
            assert result.status in ["passed", "warning", "failed"]
            assert result.duration >= 0
            assert result.is_blocker is False
