"""
File Operations Module

Atomic file operations for CI Manager.
"""

from __future__ import annotations

import hashlib
import shutil
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Final

from .exceptions import FileOperationError
from .validation import validate_path_within_project

try:
    from warden.shared.infrastructure.logging import get_logger
    logger = get_logger(__name__)
except ImportError:
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)


MAX_FILE_SIZE: Final[int] = 1024 * 1024  # 1MB max workflow file


@contextmanager
def atomic_write(target_path: Path, project_root: Path) -> Generator[Any, None, None]:
    """
    Context manager for atomic file writes.

    Uses temp file + rename pattern for crash safety.
    """
    # Validate path is within project
    safe_path = validate_path_within_project(target_path, project_root)

    # Create parent directory if needed
    safe_path.parent.mkdir(parents=True, exist_ok=True)

    # Create temp file in same directory (for atomic rename)
    temp_fd = None
    temp_path = None

    try:
        temp_fd, temp_path_str = tempfile.mkstemp(
            dir=safe_path.parent,
            prefix=".warden_",
            suffix=".tmp"
        )
        temp_path = Path(temp_path_str)

        # Yield file handle for writing
        import os
        with os.fdopen(temp_fd, 'w', encoding='utf-8') as f:
            temp_fd = None  # fd is now owned by file object
            yield f

        # Atomic rename
        shutil.move(str(temp_path), str(safe_path))
        temp_path = None

        logger.debug("ci_atomic_write_success", path=str(safe_path))

    except Exception as e:
        logger.error("ci_atomic_write_failed", path=str(safe_path), error=str(e))
        raise FileOperationError(f"Failed to write {safe_path}: {e}")
    finally:
        # Cleanup temp file if it still exists
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink()
            except (OSError, ValueError):  # CI operation best-effort
                pass


def safe_read_file(path: Path) -> str | None:
    """Read file with size limit and error handling."""
    try:
        if not path.exists():
            return None

        # Check file size
        size = path.stat().st_size
        if size > MAX_FILE_SIZE:
            logger.warning("ci_file_too_large", path=str(path), size=size)
            return None

        return path.read_text(encoding="utf-8")

    except PermissionError:
        logger.error("ci_file_permission_error", path=str(path))
        return None
    except Exception as e:
        logger.error("ci_file_read_error", path=str(path), error=str(e))
        return None


def compute_checksum(content: str) -> str:
    """Compute checksum of content (excluding dynamic header)."""
    lines = content.split("\n")
    content_lines = [
        line for line in lines
        if not line.startswith("# Warden CI v")
        and not line.startswith("# Generated:")
    ]
    return hashlib.sha256("\n".join(content_lines).encode()).hexdigest()[:12]
