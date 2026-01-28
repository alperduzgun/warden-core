"""
Path utilities for security and sanitization.
"""

import os
from pathlib import Path

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
