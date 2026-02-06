"""
Path Traversal Validator (ID 5).

Prevents path traversal attacks by enforcing all paths stay within project_root.
"""

from pathlib import Path
from typing import Optional


class PathTraversalError(Exception):
    """Raised when path traversal attack detected."""
    pass


def validate_safe_path(
    file_path: Path,
    project_root: Path,
    allow_absolute: bool = False
) -> Path:
    """
    Validate path is safe (no traversal outside project_root).

    Args:
        file_path: Path to validate
        project_root: Root directory (boundary)
        allow_absolute: Allow absolute paths (default: False)

    Returns:
        Resolved safe path

    Raises:
        PathTraversalError: If path escapes project_root
    """
    # Resolve to absolute path
    if not file_path.is_absolute():
        resolved = (project_root / file_path).resolve()
    else:
        if not allow_absolute:
            raise PathTraversalError(f"Absolute paths not allowed: {file_path}")
        resolved = file_path.resolve()

    # CRITICAL FIX (ID 5): Enforce path stays within project_root
    try:
        resolved.relative_to(project_root.resolve())
    except ValueError:
        raise PathTraversalError(
            f"Path traversal detected: {file_path} escapes {project_root}"
        )

    return resolved


def safe_read_file(
    file_path: str,
    project_root: Optional[Path] = None
) -> str:
    """
    Safely read file with path validation.

    Args:
        file_path: File to read
        project_root: Root boundary (default: cwd)

    Returns:
        File content

    Raises:
        PathTraversalError: If path escapes root
    """
    root = project_root or Path.cwd()
    safe_path = validate_safe_path(Path(file_path), root)

    with open(safe_path, 'r') as f:
        return f.read()
