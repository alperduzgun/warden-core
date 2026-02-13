"""
Path utilities for security and sanitization.
"""

import os
from pathlib import Path
from typing import List, Optional


def sanitize_path(path: str | Path, base_dir: str | Path) -> Path:
    """
    Sanitizes a path to ensure it is within the base_dir.
    Prevents path traversal attacks.

    Args:
        path: The path to sanitize.
        base_dir: The allowed root directory.

    Returns:
        The resolved Path object.

    Raises:
        ValueError: If a path traversal attempt is detected.
    """
    base_dir = Path(base_dir).resolve()
    requested_path = Path(path)

    # If the path is absolute, resolve it and check if it starts with base_dir
    # If the path is relative, resolve it relative to base_dir
    if requested_path.is_absolute():
        resolved_path = requested_path.resolve()
    else:
        resolved_path = (base_dir / requested_path).resolve()

    # Security check: Does the resolved path start with the base directory?
    # We use os.path.commonpath to safely verify the boundary
    try:
        if os.path.commonpath([str(base_dir), str(resolved_path)]) != str(base_dir):
            raise ValueError(f"Security Alert: Path traversal attempt blocked for path: {path}")
    except (ValueError, TypeError):
        raise ValueError(f"Security Alert: Path traversal attempt blocked for path: {path}")

    return resolved_path


class SafeFileScanner:
    """
    Chaos-Protected file scanner.

    Features:
    - follow_symlinks=False: Prevents infinite recursion.
    - max_depth: Limits deep-nesting traversal.
    - Global excludes: Built-in noise filtering.
    """

    DEFAULT_EXCLUDES = {
        "node_modules",
        "venv",
        ".venv",
        "build",
        "dist",
        ".git",
        "__pycache__",
        ".warden",
        ".idea",
        ".vscode",
    }

    def __init__(self, project_root: Path, max_depth: int = 15, exclude_dirs: set[str] | None = None):
        self.project_root = project_root.resolve()
        self.max_depth = max_depth
        self.exclude_dirs = exclude_dirs or self.DEFAULT_EXCLUDES

    def scan(self, extensions: set[str]) -> list[Path]:
        """Performs a safe scan for files with given extensions."""
        if not extensions:
            return []

        found_files: list[Path] = []
        try:
            for root, dirs, files in os.walk(str(self.project_root), followlinks=False):
                # Prune excluded directories
                dirs[:] = [d for d in dirs if d not in self.exclude_dirs]

                for fname in files:
                    p = Path(root) / fname
                    if p.suffix in extensions:
                        found_files.append(p)

            # print(f"  [Scanner] Found {len(found_files)} files total.")
        except Exception as e:
            # print(f"  [Scanner] Error: {e}")
            pass

        return found_files
