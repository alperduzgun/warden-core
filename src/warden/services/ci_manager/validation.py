"""
Validation Module

Input validation and security checks for CI Manager.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

from .exceptions import SecurityError, ValidationError

# Security constraints
SAFE_BRANCH_PATTERN: Final[re.Pattern] = re.compile(r'^[\w\-./]+$')
MAX_BRANCH_LENGTH: Final[int] = 256


def validate_branch(branch: str) -> str:
    """
    Validate and sanitize branch name.

    Raises:
        ValidationError: If branch name is invalid
    """
    if not branch or not isinstance(branch, str):
        raise ValidationError("Branch must be a non-empty string")

    branch = branch.strip()

    if len(branch) > MAX_BRANCH_LENGTH:
        raise ValidationError(f"Branch name too long: max {MAX_BRANCH_LENGTH} chars")

    if not SAFE_BRANCH_PATTERN.match(branch):
        raise ValidationError(f"Invalid branch name: '{branch}'. Use alphanumeric, dash, dot, slash only.")

    return branch


def validate_path_within_project(path: Path, project_root: Path) -> Path:
    """
    Ensure path is within project root (prevent traversal).

    Raises:
        SecurityError: If path escapes project root
    """
    resolved = (project_root / path).resolve()

    try:
        resolved.relative_to(project_root)
    except ValueError:
        raise SecurityError(f"Path traversal detected: {path}")

    return resolved
