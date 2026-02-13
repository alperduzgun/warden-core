"""
Provider Detection Module

Handles CI provider detection from existing files and branch detection.
"""

from __future__ import annotations

import re
import subprocess
from enum import Enum
from pathlib import Path
from typing import Final

try:
    from warden.shared.infrastructure.logging import get_logger

    logger = get_logger(__name__)
except ImportError:
    import logging

    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)


# Security: Allowed characters in branch names
SAFE_BRANCH_PATTERN: Final[re.Pattern] = re.compile(r"^[\w\-./]+$")


class CIProvider(Enum):
    """Supported CI providers."""

    GITHUB = "github"
    GITLAB = "gitlab"

    @classmethod
    def from_string(cls, value: str) -> CIProvider:
        """
        Safe conversion from string with fail-fast validation.

        Raises:
            ValidationError: If value is not a valid provider
        """
        from .exceptions import ValidationError

        if not value or not isinstance(value, str):
            raise ValidationError("Provider must be a non-empty string")

        normalized = value.lower().strip()
        try:
            return cls(normalized)
        except ValueError:
            valid = ", ".join(p.value for p in cls)
            raise ValidationError(f"Invalid provider: '{value}'. Valid: {valid}")


def detect_provider(project_root: Path) -> CIProvider | None:
    """Detect CI provider from existing files."""
    github_dir = project_root / ".github" / "workflows"
    gitlab_file = project_root / ".gitlab-ci.yml"

    if github_dir.exists() and github_dir.is_dir():
        return CIProvider.GITHUB
    elif gitlab_file.exists() and gitlab_file.is_file():
        return CIProvider.GITLAB
    return None


def detect_branch(project_root: Path) -> str:
    """Detect default branch from git or config."""
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            cwd=project_root,
            timeout=5,  # Fail fast
        )
        if result.returncode == 0:
            branch = result.stdout.strip()
            if branch and SAFE_BRANCH_PATTERN.match(branch):
                return branch
    except subprocess.TimeoutExpired:
        logger.warning("ci_git_branch_timeout")
    except Exception as e:
        logger.debug("ci_git_branch_failed", error=str(e))

    return "main"
