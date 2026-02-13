"""Async file I/O (ID 13)."""

import os
from pathlib import Path

import aiofiles

from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)


async def read_file_async(path, project_root=None):
    """
    Read file asynchronously with security checks.

    Args:
        path: Path to read
        project_root: Optional root path for traversal check (Blocker #5)
    """
    file_path = Path(path).resolve()

    # Security: Ensure path is within project root if provided
    if project_root:
        root_path = Path(project_root).resolve()
        try:
            file_path.relative_to(root_path)
            # Extra check for common traversal patterns not caught by relative_to
            if ".." in str(file_path):
                raise ValueError("Path traversal detected")
        except ValueError:
            logger.warning("security_path_traversal_blocked", path=str(file_path), root=str(root_path))
            raise ValueError(f"Security: Access denied to {file_path} (outside {root_path})")
    else:
        # Observability: Warn if security check is skipped
        logger.debug("security_check_skipped_no_root", path=str(file_path))

    async with aiofiles.open(file_path, encoding="utf-8", errors="ignore") as f:
        return await f.read()
