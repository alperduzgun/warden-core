"""
Git Helper for Warden CLI.

Provides robust git operations for incremental scanning.
Adheres to Chaos Engineering principles:
- Fail Fast: Raise detailed errors if git is missing or repo is invalid.
- Strict Types: Typed arguments and returns.
- Observability: Logging for all subprocess calls.
"""

import shutil
import subprocess
from pathlib import Path

from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)


class GitHelper:
    def __init__(self, working_dir: Path):
        self.working_dir = working_dir
        git_cmd = shutil.which("git")

        if not git_cmd:
            raise RuntimeError("Git executable not found in PATH")

        self.git_cmd: str = git_cmd

        if not (self.working_dir / ".git").exists():
            # Check if we are in a subdirectory of a repo
            try:
                subprocess.run(
                    [self.git_cmd, "rev-parse", "--is-inside-work-tree"],
                    cwd=str(self.working_dir),
                    check=True,
                    capture_output=True,
                )
            except subprocess.CalledProcessError:
                raise RuntimeError(f"Directory {working_dir} is not a git repository")

    def get_changed_files(self, base_branch: str = "main", diff_filter: str = "d") -> list[str]:
        """
        Get list of changed files relative to base branch.

        Args:
            base_branch: Branch to compare against (default: main)
            diff_filter: Diff filter options (default: 'd' for no deleted files)

        Returns:
            List of absolute paths to changed files.
        """
        logger.info("git_diff_started", base_branch=base_branch, cwd=str(self.working_dir))

        try:
            # 1. Fetch to ensure we have the base ref
            # (skip in local-only scenarios if user prefers, but safer to try)
            # subprocess.run([self.git_cmd, "fetch", "origin", base_branch], cwd=str(self.working_dir), check=False)

            # 2. Get Diff against base branch (e.g. origin/main...HEAD)
            # We use 3 dots (merge-base) for safer comparison
            # Fallback to local main if origin/main unavailable

            target = f"origin/{base_branch}"

            # Check if remote branch exists, else try local
            if not self._ref_exists(target):
                logger.warning("git_remote_ref_not_found", ref=target, fallback=base_branch)
                target = base_branch
                if not self._ref_exists(target):
                    # Crucial Edge Case: Initial commit or no main branch
                    # Compare against empty tree (all files are new)
                    logger.warning("git_local_ref_not_found", ref=target, fallback="HEAD")
                    # Just return cached changes if no base exists
                    cmd = [self.git_cmd, "diff", "--name-only", f"--diff-filter={diff_filter}", "HEAD"]
                else:
                    cmd = [self.git_cmd, "diff", "--name-only", f"--diff-filter={diff_filter}", f"{target}...HEAD"]
            else:
                cmd = [self.git_cmd, "diff", "--name-only", f"--diff-filter={diff_filter}", f"{target}...HEAD"]

            # Also include staged/unstaged changes not yet committed
            # We combine: (Diff to Base) + (Staged) + (Unstaged)
            # Actually simpler: Diff to Base includes committed. We verify uncommitted separately?
            # User expectation: "Scan what I am working on".
            # If I have uncommitted changes, they are on top of HEAD.
            # So: origin/main...HEAD covers commits.
            # We NEED to also check uncommitted changes.

            changed_files = set()

            # A. Committed changes diff (base...HEAD comparison)
            # Only run if we have a proper base comparison (contains "...")
            if any("..." in arg for arg in cmd):
                result = subprocess.run(cmd, cwd=str(self.working_dir), capture_output=True, text=True, check=True)
                for line in result.stdout.splitlines():
                    if line.strip():
                        changed_files.add(line.strip())

            # B. Unstaged/Staged changes (Current working tree vs HEAD)
            cmd_dirty = [self.git_cmd, "diff", "--name-only", f"--diff-filter={diff_filter}", "HEAD"]
            result_dirty = subprocess.run(
                cmd_dirty, cwd=str(self.working_dir), capture_output=True, text=True, check=True
            )
            for line in result_dirty.stdout.splitlines():
                if line.strip():
                    changed_files.add(line.strip())

            # C. Untracked files
            cmd_untracked = [self.git_cmd, "ls-files", "--others", "--exclude-standard"]
            result_untracked = subprocess.run(
                cmd_untracked, cwd=str(self.working_dir), capture_output=True, text=True, check=True
            )
            for line in result_untracked.stdout.splitlines():
                if line.strip():
                    changed_files.add(line.strip())

            # Resolve to absolute paths
            abs_paths = []
            for rel_path in changed_files:
                abs_p = self.working_dir / rel_path
                if abs_p.exists() and abs_p.is_file():
                    abs_paths.append(str(abs_p))

            logger.info("git_diff_completed", count=len(abs_paths))
            return sorted(abs_paths)

        except subprocess.CalledProcessError as e:
            logger.error("git_diff_failed", error=str(e), stderr=e.stderr)
            raise RuntimeError(f"Git diff failed: {e.stderr}") from e

    def _ref_exists(self, ref: str) -> bool:
        """Check if a git reference exists."""
        try:
            subprocess.run(
                [self.git_cmd, "rev-parse", "--verify", ref], cwd=str(self.working_dir), capture_output=True, check=True
            )
            return True
        except subprocess.CalledProcessError:
            return False
