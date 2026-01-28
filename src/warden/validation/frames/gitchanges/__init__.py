"""
GitChanges Frame

Analyzes git diff to focus validation on changed code only.
Useful for CI/CD to only check modified lines.

Components:
- GitChangesFrame: Main frame
- GitDiffParser: Parses git diff output

Usage:
    from . import GitChangesFrame

    frame = GitChangesFrame(config={"compare_mode": "staged"})
    result = await frame.execute(code_file)
"""

from warden.validation.frames.gitchanges.gitchanges_frame import GitChangesFrame
from warden.validation.frames.gitchanges.git_diff_parser import (
    GitDiffParser,
    DiffHunk,
    FileDiff,
)

__all__ = [
    "GitChangesFrame",
    "GitDiffParser",
    "DiffHunk",
    "FileDiff",
]
