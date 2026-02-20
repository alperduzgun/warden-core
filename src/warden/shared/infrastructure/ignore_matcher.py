"""
Ignore Matcher - Pattern Matching for File Exclusions.

Loads and applies ignore patterns from .wardenignore (gitignore syntax).
Supports glob patterns for directories, files, and deep paths.
Frame-specific ignores are passed via constructor from frame config.
"""

import fnmatch
from pathlib import Path

from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)


class IgnoreMatcher:
    """
    Matcher for ignore patterns from .wardenignore.

    Provides efficient pattern matching for:
    - Directory names (e.g., 'build', 'node_modules')
    - File patterns (e.g., '*.min.js', '*_pb2.py')
    - Path patterns with ** (e.g., '**/test_fixtures/**')
    - Frame-specific ignores (passed via constructor)
    """

    def __init__(
        self,
        project_root: Path,
        use_gitignore: bool = True,
        frame_ignores: dict[str, list[str]] | None = None,
    ):
        """
        Initialize ignore matcher.

        Args:
            project_root: Project root directory
            use_gitignore: Whether to also use .gitignore patterns
            frame_ignores: Optional per-frame ignore patterns (frame_id -> patterns)
        """
        self.project_root = project_root
        self.gitignore_file = project_root / ".gitignore"
        self.wardenignore_file = project_root / ".wardenignore"
        self.use_gitignore = use_gitignore

        # Loaded patterns
        self._directories: set[str] = set()
        self._file_patterns: list[str] = []
        self._path_patterns: list[str] = []
        self._gitignore_patterns: list[str] = []
        self._frame_ignores: dict[str, list[str]] = frame_ignores or {}

        self._loaded = False
        self._load_patterns()

    def _load_patterns(self) -> None:
        """Load patterns from .wardenignore and optionally .gitignore."""
        # Load .wardenignore as primary source
        self._load_wardenignore()

        # Also load .gitignore if enabled
        if self.use_gitignore:
            self._load_gitignore()

        if self._frame_ignores:
            logger.info("frame_ignores_configured", frames=list(self._frame_ignores.keys()))

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
                    if not line or line.startswith("#"):
                        continue

                    if line.endswith("/"):
                        line = line.rstrip("/")
                        patterns.append(f"**/{line}/**")
                        patterns.append(f"{line}/**")

                    patterns.append(line)

            self._gitignore_patterns = patterns
            logger.info("gitignore_patterns_loaded", count=len(patterns))

        except Exception as e:
            logger.warning("gitignore_load_failed", error=str(e))

    def _load_wardenignore(self) -> None:
        """Load patterns from .wardenignore file (primary ignore source)."""
        if not self.wardenignore_file.exists():
            logger.debug("wardenignore_not_found", path=str(self.wardenignore_file))
            return

        try:
            dir_patterns = []
            file_patterns = []
            path_patterns = []

            with open(self.wardenignore_file) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue

                    # Directory pattern (ends with /)
                    if line.endswith("/"):
                        dir_name = line.rstrip("/")
                        dir_patterns.append(dir_name)
                        # Also add as path pattern for nested matching
                        path_patterns.append(f"**/{dir_name}/**")
                        path_patterns.append(f"{dir_name}/**")
                        continue

                    # Deep path pattern (contains ** or /)
                    if "**" in line or "/" in line:
                        path_patterns.append(line)
                        continue

                    # File pattern (contains wildcard)
                    if "*" in line:
                        file_patterns.append(line)
                        continue

                    # Bare name — treat as directory
                    dir_patterns.append(line)
                    path_patterns.append(f"**/{line}/**")
                    path_patterns.append(f"{line}/**")

            self._directories.update(dir_patterns)
            self._file_patterns.extend(file_patterns)
            self._path_patterns.extend(path_patterns)

            logger.info(
                "wardenignore_loaded",
                directories=len(dir_patterns),
                file_patterns=len(file_patterns),
                path_patterns=len(path_patterns),
            )

        except Exception as e:
            logger.warning("wardenignore_load_failed", error=str(e))

    def should_ignore_directory(self, dir_name: str) -> bool:
        """
        Check if a directory should be ignored.

        Args:
            dir_name: Directory name (not full path)

        Returns:
            True if directory should be skipped
        """
        if dir_name in self._directories:
            return True

        return any("*" in pattern and fnmatch.fnmatch(dir_name, pattern) for pattern in self._directories)

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

            # Check directory ignores (parent directories)
            for part in relative_path.parts[:-1]:
                if self.should_ignore_directory(part):
                    logger.debug("directory_ignored", dir=part, file=rel_str)
                    return True

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
            pass

        return False

    def should_ignore_for_frame(self, file_path: Path, frame_id: str) -> bool:
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
        path = path.replace("\\", "/")
        pattern = pattern.replace("\\", "/")

        if "**" in pattern:
            parts = pattern.split("**")
            if len(parts) == 2:
                prefix, suffix = parts
                prefix = prefix.rstrip("/")
                suffix = suffix.lstrip("/")

                if prefix and not path.startswith(prefix.rstrip("*")):
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

                if suffix:
                    if suffix.endswith("/**"):
                        check_part = suffix.rstrip("/**")
                        if f"/{check_part}/" in f"/{path}/" or path.startswith(f"{check_part}/"):
                            return True
                    elif not fnmatch.fnmatch(path.split("/")[-1], suffix.lstrip("/")):
                        if not any(fnmatch.fnmatch(p, suffix.strip("/")) for p in path.split("/")):
                            return False

                return True

        return fnmatch.fnmatch(path, pattern)

    def get_frame_ignores(self, frame_id: str) -> list[str]:
        """Get ignore patterns for a specific frame."""
        return self._frame_ignores.get(frame_id, [])

    def reload(self) -> None:
        """Reload patterns from file."""
        self._directories.clear()
        self._file_patterns.clear()
        self._path_patterns.clear()
        self._gitignore_patterns.clear()
        # Preserve frame_ignores (set via constructor, not file)
        self._loaded = False
        self._load_patterns()
