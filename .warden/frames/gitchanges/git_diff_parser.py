"""
Git diff parser - Extract changed lines from git diff output.

Parses unified diff format and extracts:
- File paths
- Changed line numbers (additions and deletions)
- Line ranges for each hunk

Supports standard unified diff format from git diff.
"""

import re
from dataclasses import dataclass
from typing import List, Set, Dict, Any


@dataclass
class DiffHunk:
    """
    A single hunk in a diff (a continuous block of changes).

    Represents a @@ -old_start,old_count +new_start,new_count @@ block.
    """

    old_start: int  # Starting line in old file
    old_count: int  # Number of lines in old file
    new_start: int  # Starting line in new file
    new_count: int  # Number of lines in new file
    added_lines: Set[int]  # Line numbers that were added
    deleted_lines: Set[int]  # Line numbers that were deleted (in old file)
    context_lines: Set[int]  # Unchanged context lines (in new file)

    def get_changed_line_range(self) -> tuple[int, int]:
        """
        Get the range of changed lines in the new file.

        Returns:
            Tuple of (start_line, end_line) inclusive
        """
        if not self.added_lines:
            return (self.new_start, self.new_start)

        return (min(self.added_lines), max(self.added_lines))

    def to_json(self) -> Dict[str, Any]:
        """Serialize to JSON."""
        return {
            "oldStart": self.old_start,
            "oldCount": self.old_count,
            "newStart": self.new_start,
            "newCount": self.new_count,
            "addedLines": sorted(list(self.added_lines)),
            "deletedLines": sorted(list(self.deleted_lines)),
            "contextLines": sorted(list(self.context_lines)),
        }


@dataclass
class FileDiff:
    """
    Diff information for a single file.

    Contains all hunks and aggregated changed line information.
    """

    file_path: str  # Path to the file
    old_path: str | None = None  # Old path (for renames)
    is_new: bool = False  # File was added
    is_deleted: bool = False  # File was deleted
    is_renamed: bool = False  # File was renamed
    hunks: List[DiffHunk] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        """Initialize hunks list if not provided."""
        if self.hunks is None:
            self.hunks = []

    def get_all_added_lines(self) -> Set[int]:
        """
        Get all added line numbers across all hunks.

        Returns:
            Set of line numbers that were added
        """
        all_lines: Set[int] = set()
        for hunk in self.hunks:
            all_lines.update(hunk.added_lines)
        return all_lines

    def get_all_deleted_lines(self) -> Set[int]:
        """
        Get all deleted line numbers across all hunks.

        Returns:
            Set of line numbers that were deleted (from old file)
        """
        all_lines: Set[int] = set()
        for hunk in self.hunks:
            all_lines.update(hunk.deleted_lines)
        return all_lines

    def get_changed_line_ranges(self) -> List[tuple[int, int]]:
        """
        Get all ranges of changed lines.

        Returns:
            List of (start_line, end_line) tuples
        """
        return [hunk.get_changed_line_range() for hunk in self.hunks]

    def to_json(self) -> Dict[str, Any]:
        """Serialize to JSON."""
        return {
            "filePath": self.file_path,
            "oldPath": self.old_path,
            "isNew": self.is_new,
            "isDeleted": self.is_deleted,
            "isRenamed": self.is_renamed,
            "hunks": [hunk.to_json() for hunk in self.hunks],
            "addedLines": sorted(list(self.get_all_added_lines())),
            "deletedLines": sorted(list(self.get_all_deleted_lines())),
        }


class GitDiffParser:
    """
    Parser for git diff unified format.

    Parses output from:
        - git diff
        - git diff HEAD
        - git diff <commit>..<commit>
        - git show <commit>

    Example diff format:
        diff --git a/file.py b/file.py
        index abc123..def456 100644
        --- a/file.py
        +++ b/file.py
        @@ -10,7 +10,8 @@ def foo():
             context line
        -    old line
        +    new line
        +    another new line
             context line
    """

    # Regex patterns for parsing
    DIFF_HEADER = re.compile(r"^diff --git a/(.*) b/(.*)$")
    FILE_HEADER_OLD = re.compile(r"^--- (.*)$")
    FILE_HEADER_NEW = re.compile(r"^\+\+\+ (.*)$")
    HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
    NEW_FILE = re.compile(r"^new file mode")
    DELETED_FILE = re.compile(r"^deleted file mode")
    RENAME_FROM = re.compile(r"^rename from (.*)$")
    RENAME_TO = re.compile(r"^rename to (.*)$")

    def parse(self, diff_output: str) -> List[FileDiff]:
        """
        Parse git diff output.

        Args:
            diff_output: Output from git diff command

        Returns:
            List of FileDiff objects, one per changed file

        Example:
            >>> parser = GitDiffParser()
            >>> diffs = parser.parse(git_diff_output)
            >>> for file_diff in diffs:
            ...     print(f"{file_diff.file_path}: {len(file_diff.get_all_added_lines())} lines added")
        """
        if not diff_output or not diff_output.strip():
            return []

        lines = diff_output.split("\n")
        file_diffs: List[FileDiff] = []
        current_file: FileDiff | None = None
        current_hunk: DiffHunk | None = None
        current_old_line = 0
        current_new_line = 0

        for line in lines:
            # Start of new file diff
            if match := self.DIFF_HEADER.match(line):
                # Save previous file if exists
                if current_file and current_hunk:
                    current_file.hunks.append(current_hunk)
                    current_hunk = None
                if current_file:
                    file_diffs.append(current_file)

                # Start new file
                old_path = match.group(1)
                new_path = match.group(2)
                current_file = FileDiff(file_path=new_path, old_path=old_path if old_path != new_path else None)
                continue

            if not current_file:
                continue

            # File status markers
            if self.NEW_FILE.match(line):
                current_file.is_new = True
                continue

            if self.DELETED_FILE.match(line):
                current_file.is_deleted = True
                continue

            if match := self.RENAME_FROM.match(line):
                current_file.is_renamed = True
                current_file.old_path = match.group(1)
                continue

            if match := self.RENAME_TO.match(line):
                current_file.file_path = match.group(1)
                continue

            # Hunk header
            if match := self.HUNK_HEADER.match(line):
                # Save previous hunk if exists
                if current_hunk:
                    current_file.hunks.append(current_hunk)

                # Parse hunk header
                old_start = int(match.group(1))
                old_count = int(match.group(2)) if match.group(2) else 1
                new_start = int(match.group(3))
                new_count = int(match.group(4)) if match.group(4) else 1

                # Create new hunk
                current_hunk = DiffHunk(
                    old_start=old_start,
                    old_count=old_count,
                    new_start=new_start,
                    new_count=new_count,
                    added_lines=set(),
                    deleted_lines=set(),
                    context_lines=set(),
                )

                # Initialize line counters
                current_old_line = old_start
                current_new_line = new_start
                continue

            if not current_hunk:
                continue

            # Added line
            if line.startswith("+") and not line.startswith("+++"):
                current_hunk.added_lines.add(current_new_line)
                current_new_line += 1
                continue

            # Deleted line
            if line.startswith("-") and not line.startswith("---"):
                current_hunk.deleted_lines.add(current_old_line)
                current_old_line += 1
                continue

            # Context line (unchanged)
            if line.startswith(" "):
                current_hunk.context_lines.add(current_new_line)
                current_old_line += 1
                current_new_line += 1
                continue

        # Save last hunk and file
        if current_file and current_hunk:
            current_file.hunks.append(current_hunk)
        if current_file:
            file_diffs.append(current_file)

        return file_diffs

    def parse_for_file(self, diff_output: str, file_path: str) -> FileDiff | None:
        """
        Parse diff output and return diff for specific file.

        Args:
            diff_output: Output from git diff command
            file_path: Path to specific file

        Returns:
            FileDiff for the file, or None if file not in diff
        """
        all_diffs = self.parse(diff_output)
        for file_diff in all_diffs:
            if file_diff.file_path == file_path:
                return file_diff
        return None
