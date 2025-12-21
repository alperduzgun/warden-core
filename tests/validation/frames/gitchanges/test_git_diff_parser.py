"""Tests for GitDiffParser - git diff parsing utility."""

import pytest
from warden.validation.frames.gitchanges.git_diff_parser import (
    GitDiffParser,
    FileDiff,
    DiffHunk,
)


class TestDiffHunk:
    """Tests for DiffHunk dataclass."""

    def test_get_changed_line_range_with_additions(self):
        """Test getting changed line range when lines are added."""
        hunk = DiffHunk(
            old_start=10,
            old_count=5,
            new_start=10,
            new_count=7,
            added_lines={11, 12, 15},
            deleted_lines=set(),
            context_lines={10, 13, 14},
        )

        start, end = hunk.get_changed_line_range()
        assert start == 11
        assert end == 15

    def test_get_changed_line_range_no_additions(self):
        """Test getting changed line range when no lines added."""
        hunk = DiffHunk(
            old_start=10,
            old_count=5,
            new_start=10,
            new_count=3,
            added_lines=set(),
            deleted_lines={11, 12},
            context_lines={10, 13},
        )

        start, end = hunk.get_changed_line_range()
        assert start == 10
        assert end == 10

    def test_to_json(self):
        """Test JSON serialization."""
        hunk = DiffHunk(
            old_start=10,
            old_count=5,
            new_start=10,
            new_count=6,
            added_lines={11, 12},
            deleted_lines={13},
            context_lines={10, 14},
        )

        json_data = hunk.to_json()

        assert json_data["oldStart"] == 10
        assert json_data["newStart"] == 10
        assert json_data["addedLines"] == [11, 12]
        assert json_data["deletedLines"] == [13]
        assert json_data["contextLines"] == [10, 14]


class TestFileDiff:
    """Tests for FileDiff dataclass."""

    def test_init_defaults(self):
        """Test FileDiff initialization with defaults."""
        diff = FileDiff(file_path="test.py")

        assert diff.file_path == "test.py"
        assert diff.hunks == []
        assert diff.is_new is False
        assert diff.is_deleted is False
        assert diff.is_renamed is False

    def test_get_all_added_lines(self):
        """Test getting all added lines across hunks."""
        diff = FileDiff(file_path="test.py")
        diff.hunks = [
            DiffHunk(10, 5, 10, 6, {11, 12}, set(), set()),
            DiffHunk(20, 3, 22, 4, {23}, set(), set()),
        ]

        added_lines = diff.get_all_added_lines()
        assert added_lines == {11, 12, 23}

    def test_get_all_deleted_lines(self):
        """Test getting all deleted lines across hunks."""
        diff = FileDiff(file_path="test.py")
        diff.hunks = [
            DiffHunk(10, 5, 10, 4, set(), {11}, set()),
            DiffHunk(20, 3, 20, 2, set(), {21, 22}, set()),
        ]

        deleted_lines = diff.get_all_deleted_lines()
        assert deleted_lines == {11, 21, 22}

    def test_to_json(self):
        """Test JSON serialization."""
        diff = FileDiff(
            file_path="new.py",
            old_path="old.py",
            is_renamed=True,
        )
        diff.hunks = [
            DiffHunk(10, 5, 10, 6, {11}, set(), set()),
        ]

        json_data = diff.to_json()

        assert json_data["filePath"] == "new.py"
        assert json_data["oldPath"] == "old.py"
        assert json_data["isRenamed"] is True
        assert len(json_data["hunks"]) == 1


class TestGitDiffParser:
    """Tests for GitDiffParser."""

    def test_parse_empty_diff(self):
        """Test parsing empty diff output."""
        parser = GitDiffParser()
        result = parser.parse("")

        assert result == []

    def test_parse_simple_addition(self):
        """Test parsing simple line addition."""
        diff = """diff --git a/test.py b/test.py
index abc123..def456 100644
--- a/test.py
+++ b/test.py
@@ -10,3 +10,4 @@ def foo():
     line 1
     line 2
+    new line
     line 3
"""
        parser = GitDiffParser()
        result = parser.parse(diff)

        assert len(result) == 1
        file_diff = result[0]
        assert file_diff.file_path == "test.py"
        assert len(file_diff.hunks) == 1
        assert 13 in file_diff.get_all_added_lines()

    def test_parse_simple_deletion(self):
        """Test parsing simple line deletion."""
        diff = """diff --git a/test.py b/test.py
index abc123..def456 100644
--- a/test.py
+++ b/test.py
@@ -10,4 +10,3 @@ def foo():
     line 1
-    deleted line
     line 2
     line 3
"""
        parser = GitDiffParser()
        result = parser.parse(diff)

        assert len(result) == 1
        file_diff = result[0]
        assert 11 in file_diff.get_all_deleted_lines()

    def test_parse_new_file(self):
        """Test parsing new file."""
        diff = """diff --git a/new.py b/new.py
new file mode 100644
index 0000000..abc123
--- /dev/null
+++ b/new.py
@@ -0,0 +1,3 @@
+def new_function():
+    pass
+
"""
        parser = GitDiffParser()
        result = parser.parse(diff)

        assert len(result) == 1
        file_diff = result[0]
        assert file_diff.is_new is True
        assert file_diff.file_path == "new.py"

    def test_parse_deleted_file(self):
        """Test parsing deleted file."""
        diff = """diff --git a/deleted.py b/deleted.py
deleted file mode 100644
index abc123..0000000
--- a/deleted.py
+++ /dev/null
@@ -1,3 +0,0 @@
-def old_function():
-    pass
-
"""
        parser = GitDiffParser()
        result = parser.parse(diff)

        assert len(result) == 1
        file_diff = result[0]
        assert file_diff.is_deleted is True

    def test_parse_renamed_file(self):
        """Test parsing renamed file."""
        diff = """diff --git a/old.py b/new.py
similarity index 100%
rename from old.py
rename to new.py
"""
        parser = GitDiffParser()
        result = parser.parse(diff)

        assert len(result) == 1
        file_diff = result[0]
        assert file_diff.is_renamed is True
        assert file_diff.old_path == "old.py"
        assert file_diff.file_path == "new.py"

    def test_parse_multiple_files(self):
        """Test parsing diff with multiple files."""
        diff = """diff --git a/file1.py b/file1.py
index abc123..def456 100644
--- a/file1.py
+++ b/file1.py
@@ -1,3 +1,4 @@
 line 1
+new line
 line 2
 line 3
diff --git a/file2.py b/file2.py
index abc123..def456 100644
--- a/file2.py
+++ b/file2.py
@@ -1,3 +1,2 @@
 line 1
-deleted line
 line 2
"""
        parser = GitDiffParser()
        result = parser.parse(diff)

        assert len(result) == 2
        assert result[0].file_path == "file1.py"
        assert result[1].file_path == "file2.py"

    def test_parse_for_file(self):
        """Test parsing diff for specific file."""
        diff = """diff --git a/file1.py b/file1.py
index abc123..def456 100644
--- a/file1.py
+++ b/file1.py
@@ -1,3 +1,4 @@
 line 1
+new line
 line 2
 line 3
diff --git a/file2.py b/file2.py
index abc123..def456 100644
--- a/file2.py
+++ b/file2.py
@@ -1,3 +1,2 @@
 line 1
-deleted line
 line 2
"""
        parser = GitDiffParser()
        file_diff = parser.parse_for_file(diff, "file2.py")

        assert file_diff is not None
        assert file_diff.file_path == "file2.py"

    def test_parse_for_file_not_found(self):
        """Test parsing for file not in diff."""
        diff = """diff --git a/file1.py b/file1.py
index abc123..def456 100644
--- a/file1.py
+++ b/file1.py
@@ -1,3 +1,4 @@
 line 1
+new line
 line 2
"""
        parser = GitDiffParser()
        file_diff = parser.parse_for_file(diff, "not_found.py")

        assert file_diff is None
