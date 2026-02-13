"""
Git Checkpoint Manager for safe auto-fix operations.

Creates git stash checkpoints before applying fixes,
enables single-file rollback on syntax errors.
"""

import subprocess
import sys
from pathlib import Path
from typing import Any

from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)


class GitCheckpointError(Exception):
    """Raised when git checkpoint operations fail."""

    pass


class GitCheckpointManager:
    """
    Manages git checkpoints for safe auto-fix application.

    Safety Protocol:
    1. git stash create -> checkpoint_ref
    2. Apply fix to file (atomic write)
    3. python -m py_compile file.py (syntax validation)
    4. If fail -> git checkout -- file.py (rollback single file)
    5. If pass -> continue to next fix
    """

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self._checkpoint_ref: str | None = None
        self._modified_files: list[str] = []

    def create_checkpoint(self) -> str | None:
        """
        Create a git stash checkpoint of current state.

        Returns:
            Stash reference string, or None if working tree is clean.

        Raises:
            GitCheckpointError: If git operations fail.
        """
        try:
            # Check if we're in a git repo
            result = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                raise GitCheckpointError("Not inside a git repository")

            # Create stash (doesn't pop - just creates ref)
            result = subprocess.run(
                ["git", "stash", "create"], cwd=self.project_root, capture_output=True, text=True, timeout=30
            )

            ref = result.stdout.strip()
            if ref:
                self._checkpoint_ref = ref
                logger.info("git_checkpoint_created", ref=ref[:8])
                return ref

            logger.info("git_checkpoint_clean_tree", message="Working tree is clean")
            return None

        except subprocess.TimeoutExpired:
            raise GitCheckpointError("Git stash timed out")
        except FileNotFoundError:
            raise GitCheckpointError("git not found on PATH")
        except GitCheckpointError:
            raise
        except Exception as e:
            raise GitCheckpointError(f"Checkpoint creation failed: {e}")

    def rollback_file(self, file_path: str) -> bool:
        """
        Rollback a single file to its pre-fix state.

        Args:
            file_path: Relative path to file from project root.

        Returns:
            True if rollback succeeded.
        """
        try:
            result = subprocess.run(
                ["git", "checkout", "--", file_path], cwd=self.project_root, capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                logger.info("file_rollback_success", file=file_path)
                return True

            logger.error("file_rollback_failed", file=file_path, stderr=result.stderr)
            return False

        except Exception as e:
            logger.error("file_rollback_error", file=file_path, error=str(e))
            return False

    def validate_syntax(self, file_path: Path) -> bool:
        """
        Validate Python file syntax using py_compile.

        Args:
            file_path: Absolute path to file.

        Returns:
            True if syntax is valid.
        """
        if file_path.suffix != ".py":
            return True  # Non-Python files skip validation

        try:
            result = subprocess.run(
                [sys.executable, "-m", "py_compile", str(file_path)], capture_output=True, text=True, timeout=10
            )
            return result.returncode == 0
        except Exception as e:
            logger.warning("syntax_validation_error", file=str(file_path), error=str(e))
            return False

    def record_modification(self, file_path: str) -> None:
        """Record that a file was modified by auto-fix."""
        self._modified_files.append(file_path)

    @property
    def modified_files(self) -> list[str]:
        """Get list of files modified by auto-fix."""
        return self._modified_files.copy()

    @property
    def checkpoint_ref(self) -> str | None:
        """Get the checkpoint reference."""
        return self._checkpoint_ref
