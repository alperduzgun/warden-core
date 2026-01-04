"""
Ignore Matcher - Pattern Matching for File Exclusions.

Loads and applies ignore patterns from .warden/ignore.yaml.
Supports glob patterns for directories, files, and deep paths.
"""

import fnmatch
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import yaml

from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)


class IgnoreMatcher:
    """
    Matcher for ignore patterns from .warden/ignore.yaml.
    
    Provides efficient pattern matching for:
    - Directory names (e.g., 'build', 'node_modules')
    - File patterns (e.g., '*.min.js', '*_pb2.py')
    - Path patterns with ** (e.g., '**/test_fixtures/**')
    - Frame-specific ignores
    """

    def __init__(self, project_root: Path, use_gitignore: bool = True):
        """
        Initialize ignore matcher.

        Args:
            project_root: Project root directory
            use_gitignore: Whether to also use .gitignore patterns
        """
        self.project_root = project_root
        self.ignore_file = project_root / ".warden" / "ignore.yaml"
        self.gitignore_file = project_root / ".gitignore"
        self.use_gitignore = use_gitignore
        
        # Loaded patterns
        self._directories: Set[str] = set()
        self._file_patterns: List[str] = []
        self._path_patterns: List[str] = []
        self._gitignore_patterns: List[str] = []
        self._frame_ignores: Dict[str, List[str]] = {}
        
        self._loaded = False
        self._load_patterns()

    def _load_patterns(self) -> None:
        """Load patterns from ignore.yaml."""
        if not self.ignore_file.exists():
            logger.debug("ignore_file_not_found", path=str(self.ignore_file))
            self._loaded = True
            return

        try:
            with open(self.ignore_file) as f:
                data = yaml.safe_load(f) or {}
            
            self._directories = set(data.get("directories", []))
            self._file_patterns = data.get("file_patterns", [])
            self._path_patterns = data.get("path_patterns", [])
            self._frame_ignores = data.get("frames", {})
            
            logger.info(
                "ignore_patterns_loaded",
                directories=len(self._directories),
                file_patterns=len(self._file_patterns),
                path_patterns=len(self._path_patterns),
                frame_rules=len(self._frame_ignores),
            )
            
            # Also load .gitignore if enabled
            if self.use_gitignore:
                self._load_gitignore()
                
            self._loaded = True

        except Exception as e:
            logger.error("ignore_load_failed", error=str(e))
            self._loaded = True

    def _load_gitignore(self) -> None:
        """Load patterns from .gitignore file."""
        if not self.gitignore_file.exists():
            return

        try:
            patterns = []
            with open(self.gitignore_file) as f:
                for line in f:
                    line = line.strip()
                    # Skip empty lines and comments
                    if not line or line.startswith("#"):
                        continue
                    
                    # Normalize pattern
                    if line.endswith("/"):
                        line = line.rstrip("/")
                        # If it's a directory, we can treat it as a path pattern with **
                        patterns.append(f"**/{line}/**")
                        patterns.append(f"{line}/**")
                    
                    patterns.append(line)
            
            self._gitignore_patterns = patterns
            logger.info("gitignore_patterns_loaded", count=len(patterns))
            
        except Exception as e:
            logger.warning("gitignore_load_failed", error=str(e))

    def should_ignore_directory(self, dir_name: str) -> bool:
        """
        Check if a directory should be ignored.

        Args:
            dir_name: Directory name (not full path)

        Returns:
            True if directory should be skipped
        """
        # Direct name match
        if dir_name in self._directories:
            return True
        
        # Pattern match (for things like "*.egg-info")
        for pattern in self._directories:
            if "*" in pattern and fnmatch.fnmatch(dir_name, pattern):
                return True
        
        return False

    def should_ignore_file(self, file_path: Path) -> bool:
        """
        Check if a file should be ignored.

        Args:
            file_path: Full path to file

        Returns:
            True if file should be skipped
        """
        return self.should_ignore_path(file_path)

    def should_ignore_path(self, file_path: Path) -> bool:
        """
        Check if a path should be ignored (global patterns).

        Args:
            file_path: Full path to file/directory

        Returns:
            True if path matches any ignore pattern
        """
        file_name = file_path.name
        
        # Check file patterns
        for pattern in self._file_patterns:
            if fnmatch.fnmatch(file_name, pattern):
                logger.debug("file_ignored", file=str(file_path), pattern=pattern)
                return True
        
        # Check path patterns (relative to project root)
        try:
            relative_path = file_path.relative_to(self.project_root)
            rel_str = str(relative_path)
            
            for pattern in self._path_patterns:
                if self._match_path_pattern(rel_str, pattern):
                    logger.debug("path_ignored", file=rel_str, pattern=pattern)
                    return True
            
            # Check gitignore patterns
            for pattern in self._gitignore_patterns:
                if self._match_path_pattern(rel_str, pattern):
                    logger.debug("gitignore_ignored", file=rel_str, pattern=pattern)
                    return True
        except ValueError:
            # File not under project root
            pass
        
        return False

    def should_ignore_for_frame(
        self, file_path: Path, frame_id: str
    ) -> bool:
        """
        Check if a file should be ignored for a specific frame.

        Args:
            file_path: Full path to file
            frame_id: Frame ID (e.g., 'security', 'orphan')

        Returns:
            True if file should be skipped for this frame
        """
        # Check global ignores first
        if self.should_ignore_file(file_path):
            return True
        
        # Check frame-specific ignores
        frame_patterns = self._frame_ignores.get(frame_id, [])
        if not frame_patterns:
            return False
        
        try:
            relative_path = file_path.relative_to(self.project_root)
            rel_str = str(relative_path)
            
            for pattern in frame_patterns:
                if self._match_path_pattern(rel_str, pattern):
                    logger.debug(
                        "frame_ignore_match",
                        file=rel_str,
                        frame=frame_id,
                        pattern=pattern,
                    )
                    return True
        except ValueError:
            pass
        
        return False

    def _match_path_pattern(self, path: str, pattern: str) -> bool:
        """
        Match a path against a glob pattern with ** support.

        Args:
            path: Relative path string
            pattern: Glob pattern (may contain **)

        Returns:
            True if path matches pattern
        """
        # Normalize separators
        path = path.replace("\\", "/")
        pattern = pattern.replace("\\", "/")
        
        # Handle ** patterns
        if "**" in pattern:
            # Convert ** to regex-like matching
            parts = pattern.split("**")
            if len(parts) == 2:
                prefix, suffix = parts
                prefix = prefix.rstrip("/")
                suffix = suffix.lstrip("/")
                
                # Check if path starts with prefix (if any)
                if prefix and not path.startswith(prefix.rstrip("*")):
                    # Try fnmatch for prefix with wildcards
                    if "*" in prefix:
                        path_parts = path.split("/")
                        prefix_parts = prefix.rstrip("/").split("/")
                        if len(path_parts) < len(prefix_parts):
                            return False
                        for i, pp in enumerate(prefix_parts):
                            if not fnmatch.fnmatch(path_parts[i], pp):
                                return False
                    else:
                        return False
                
                # Check if path ends with suffix (if any)
                if suffix:
                    if suffix.endswith("/**"):
                        # Pattern like "**/examples/**" - check if suffix dir exists
                        check_part = suffix.rstrip("/**")
                        if f"/{check_part}/" in f"/{path}/" or path.startswith(f"{check_part}/"):
                            return True
                    elif not fnmatch.fnmatch(path.split("/")[-1], suffix.lstrip("/")):
                        # Check filename match
                        if not any(fnmatch.fnmatch(p, suffix.strip("/")) for p in path.split("/")):
                            return False
                
                return True
        
        # Simple fnmatch for non-** patterns
        return fnmatch.fnmatch(path, pattern)

    def get_frame_ignores(self, frame_id: str) -> List[str]:
        """Get ignore patterns for a specific frame."""
        return self._frame_ignores.get(frame_id, [])

    def reload(self) -> None:
        """Reload patterns from file."""
        self._directories.clear()
        self._file_patterns.clear()
        self._path_patterns.clear()
        self._frame_ignores.clear()
        self._loaded = False
        self._load_patterns()
