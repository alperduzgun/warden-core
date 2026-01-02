"""
Main file discoverer.

Orchestrates file discovery, classification, and framework detection.
"""

import time
from pathlib import Path
from typing import List, Optional

from warden.analysis.application.discovery.models import (
    DiscoveredFile,
    DiscoveryResult,
    DiscoveryStats,
    FileType,
)
from warden.analysis.application.discovery.classifier import FileClassifier
from warden.analysis.application.discovery.gitignore_filter import GitignoreFilter, create_gitignore_filter
from warden.analysis.application.discovery.framework_detector import FrameworkDetector


class FileDiscoverer:
    """
    Main file discovery orchestrator.

    Discovers files in a project directory, classifies them, and detects frameworks.
    """

    def __init__(
        self,
        root_path: str | Path,
        max_depth: Optional[int] = None,
        use_gitignore: bool = True,
    ) -> None:
        """
        Initialize the file discoverer.

        Args:
            root_path: Root directory to scan
            max_depth: Maximum directory depth to scan (None for unlimited)
            use_gitignore: Whether to respect .gitignore patterns

        Examples:
            >>> discoverer = FileDiscoverer(root_path="/path/to/project")
            >>> result = await discoverer.discover_async()
        """
        self.root_path = Path(root_path).resolve()
        self.max_depth = max_depth
        self.use_gitignore = use_gitignore

        # Initialize components
        self.classifier = FileClassifier()
        self.gitignore_filter: Optional[GitignoreFilter] = None

        if self.use_gitignore:
            self.gitignore_filter = create_gitignore_filter(self.root_path)

    async def discover_async(self) -> DiscoveryResult:
        """
        Discover files asynchronously.

        Returns:
            DiscoveryResult with all discovered files and metadata

        Examples:
            >>> discoverer = FileDiscoverer(root_path="/path/to/project")
            >>> result = await discoverer.discover_async()
            >>> print(f"Found {result.stats.total_files} files")
        """
        start_time = time.time()

        # Discover files
        files = await self._discover_files()

        # Detect frameworks
        framework_detector = FrameworkDetector(self.root_path)
        framework_result = await framework_detector.detect()

        # Calculate statistics
        stats = self._calculate_stats(files, start_time)

        # Get gitignore patterns
        gitignore_patterns: List[str] = []
        if self.gitignore_filter:
            gitignore_patterns = self.gitignore_filter.get_patterns()

        return DiscoveryResult(
            project_path=str(self.root_path),
            files=files,
            framework_detection=framework_result,
            stats=stats,
            gitignore_patterns=gitignore_patterns,
            metadata={
                "max_depth": self.max_depth,
                "use_gitignore": self.use_gitignore,
            },
        )

    def discover_sync(self) -> DiscoveryResult:
        """
        Discover files synchronously (blocks until complete).

        Returns:
            DiscoveryResult with all discovered files and metadata

        Examples:
            >>> discoverer = FileDiscoverer(root_path="/path/to/project")
            >>> result = discoverer.discover_sync()
            >>> print(f"Found {result.stats.total_files} files")
        """
        import asyncio

        return asyncio.run(self.discover_async())

    async def _discover_files(self) -> List[DiscoveredFile]:
        """
        Discover all files in the project.

        Returns:
            List of DiscoveredFile objects
        """
        discovered_files: List[DiscoveredFile] = []

        # Walk directory tree
        for file_path in self._walk_directory(self.root_path, current_depth=0):
            # Skip if gitignore says so
            if self.gitignore_filter and self.gitignore_filter.should_ignore(file_path):
                continue

            # Skip non-files (directories, symlinks, etc.)
            if not file_path.is_file():
                continue

            # Skip binary and non-code files
            if self.classifier.should_skip(file_path):
                continue

            # Classify file
            file_type = self.classifier.classify(file_path)

            # Get file size
            try:
                size_bytes = file_path.stat().st_size
            except OSError:
                size_bytes = 0

            # Create DiscoveredFile
            relative_path = file_path.relative_to(self.root_path)
            discovered_file = DiscoveredFile(
                path=str(file_path),
                relative_path=str(relative_path),
                file_type=file_type,
                size_bytes=size_bytes,
                is_analyzable=file_type.is_analyzable,
                metadata={},
            )

            discovered_files.append(discovered_file)

        return discovered_files

    def _walk_directory(self, directory: Path, current_depth: int) -> List[Path]:
        """
        Recursively walk directory tree.

        Args:
            directory: Directory to walk
            current_depth: Current recursion depth

        Returns:
            List of file paths
        """
        # Check max depth
        if self.max_depth is not None and current_depth > self.max_depth:
            return []

        paths: List[Path] = []

        try:
            for item in directory.iterdir():
                # Skip if gitignore says so
                if self.gitignore_filter and self.gitignore_filter.should_ignore(item):
                    continue

                if item.is_file():
                    paths.append(item)
                elif item.is_dir():
                    # Recurse into subdirectory
                    sub_paths = self._walk_directory(item, current_depth + 1)
                    paths.extend(sub_paths)
        except (PermissionError, OSError):
            # Skip directories we can't read
            pass

        return paths

    def _calculate_stats(
        self, files: List[DiscoveredFile], start_time: float
    ) -> DiscoveryStats:
        """
        Calculate discovery statistics.

        Args:
            files: List of discovered files
            start_time: Start time of discovery

        Returns:
            DiscoveryStats object
        """
        stats = DiscoveryStats()

        stats.total_files = len(files)
        stats.analyzable_files = sum(1 for f in files if f.is_analyzable)
        stats.total_size_bytes = sum(f.size_bytes for f in files)
        stats.scan_duration_seconds = time.time() - start_time

        # Count files by type
        files_by_type: dict[str, int] = {}
        for file in files:
            file_type_str = file.file_type.value
            files_by_type[file_type_str] = files_by_type.get(file_type_str, 0) + 1

        stats.files_by_type = files_by_type

        # Calculate ignored files (rough estimate)
        # This is a simplification - we'd need to count during walking for accuracy
        stats.ignored_files = 0

        return stats

    def get_analyzable_files(self) -> List[Path]:
        """
        Get only analyzable files (synchronous).

        Returns:
            List of paths to analyzable files

        Examples:
            >>> discoverer = FileDiscoverer(root_path="/path/to/project")
            >>> files = discoverer.get_analyzable_files()
            >>> len(files)
            42
        """
        result = self.discover_sync()
        return [Path(f.path) for f in result.get_analyzable_files()]

    async def get_analyzable_files_async(self) -> List[Path]:
        """
        Get only analyzable files (asynchronous).

        Returns:
            List of paths to analyzable files

        Examples:
            >>> discoverer = FileDiscoverer(root_path="/path/to/project")
            >>> files = await discoverer.get_analyzable_files_async()
            >>> len(files)
            42
        """
        result = await self.discover_async()
        return [Path(f.path) for f in result.get_analyzable_files()]

    def get_files_by_type(self, file_type: FileType) -> List[Path]:
        """
        Get files of a specific type (synchronous).

        Args:
            file_type: Type of files to get

        Returns:
            List of paths matching the file type

        Examples:
            >>> discoverer = FileDiscoverer(root_path="/path/to/project")
            >>> py_files = discoverer.get_files_by_type(FileType.PYTHON)
            >>> len(py_files)
            15
        """
        result = self.discover_sync()
        return [Path(f.path) for f in result.get_files_by_type(file_type)]


async def discover_project_files(
    project_root: str | Path,
    max_depth: Optional[int] = None,
    use_gitignore: bool = True,
) -> DiscoveryResult:
    """
    Discover files in a project (convenience function).

    Args:
        project_root: Root directory of the project
        max_depth: Maximum directory depth to scan
        use_gitignore: Whether to respect .gitignore patterns

    Returns:
        DiscoveryResult with all discovered files

    Examples:
        >>> result = await discover_project_files("/path/to/project")
        >>> print(f"Found {result.stats.total_files} files")
        Found 123 files
    """
    discoverer = FileDiscoverer(
        root_path=project_root,
        max_depth=max_depth,
        use_gitignore=use_gitignore,
    )
    return await discoverer.discover_async()
