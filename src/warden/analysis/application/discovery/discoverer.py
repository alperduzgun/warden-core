"""
Main file discoverer.

Orchestrates file discovery, classification, and framework detection.
"""

import time
from pathlib import Path
from typing import List, Optional

import structlog

from warden.analysis.application.discovery.classifier import FileClassifier
from warden.analysis.application.discovery.framework_detector import FrameworkDetector
from warden.analysis.application.discovery.gitignore_filter import GitignoreFilter, create_gitignore_filter
from warden.analysis.application.discovery.models import (
    DiscoveredFile,
    DiscoveryResult,
    DiscoveryStats,
    FileType,
)

logger = structlog.get_logger(__name__)


class FileDiscoverer:
    """
    Main file discovery orchestrator.

    Discovers files in a project directory, classifies them, and detects frameworks.
    """

    def __init__(
        self,
        root_path: str | Path,
        max_depth: int | None = None,
        use_gitignore: bool = True,
        max_size_mb: int | None = None,
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
        self.max_size_mb = max_size_mb

        # Initialize components
        self.classifier = FileClassifier()
        self.gitignore_filter: GitignoreFilter | None = None

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
        files = await self._discover_files_async()

        # Detect frameworks
        framework_detector = FrameworkDetector(self.root_path)
        framework_result = await framework_detector.detect()

        # Calculate statistics
        stats = self._calculate_stats(files, start_time)

        # Get gitignore patterns
        gitignore_patterns: list[str] = []
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

    async def _discover_files_async(self) -> list[DiscoveredFile]:
        """
        Discover all files in the project.

        Returns:
            List of DiscoveredFile objects
        """
        discovered_files: list[DiscoveredFile] = []

        # Try Rust discovery first
        try:
            from warden import warden_core_rust
            RUST_AVAILABLE = True
        except ImportError:
            RUST_AVAILABLE = False

        if RUST_AVAILABLE:
            try:
                logger.debug("discovery_engine_selected", engine="rust", project_root=str(self.root_path), max_size_mb=self.max_size_mb)
                rust_files = warden_core_rust.discover_files(str(self.root_path), self.use_gitignore, self.max_size_mb)

                # STEP 1: Batch get stats (Parallel line count, hash, binary check)
                raw_paths = [f[0] for f in rust_files]
                stats_batch = warden_core_rust.get_file_stats(raw_paths)
                stats_map = {s.path: s for s in stats_batch}

                for path_str, initial_size, detected_lang in rust_files:
                    file_path = Path(path_str)
                    rust_stat = stats_map.get(path_str)

                    # Double check max depth if needed
                    if self.max_depth is not None:
                        try:
                            relative = file_path.relative_to(self.root_path)
                            if len(relative.parts) > self.max_depth:
                                continue
                        except ValueError:
                            continue

                    # Early binary skip via Rust stats
                    if rust_stat and rust_stat.is_binary:
                        continue

                    # Fallback to Python classifier for file-type specific skip rules
                    if self.classifier.should_skip(file_path):
                        continue

                    # Classify file (Use Rust detected lang if valid, else fallback)
                    if detected_lang and detected_lang != "unknown":
                        try:
                            file_type = FileType(detected_lang)
                        except ValueError:
                            file_type = self.classifier.classify(file_path)
                    else:
                        file_type = self.classifier.classify(file_path)

                    # Create DiscoveredFile
                    relative_path = file_path.relative_to(self.root_path)
                    discovered_file = DiscoveredFile(
                        path=str(file_path),
                        relative_path=str(relative_path),
                        file_type=file_type,
                        size_bytes=rust_stat.size if rust_stat else initial_size,
                        line_count=rust_stat.line_count if rust_stat else 0,
                        hash=rust_stat.hash if rust_stat else None,
                        is_analyzable=file_type.is_analyzable,
                        metadata={"engine": "rust", "detected_lang": detected_lang},
                    )
                    discovered_files.append(discovered_file)

                logger.info("discovery_process_complete", engine="rust", file_count=len(discovered_files))
                return discovered_files

            except Exception as e:
                logger.warning("rust_discovery_failed_falling_back", error=str(e))

        # Fallback to Python discovery
        logger.debug("discovery_engine_selected", engine="python", project_root=str(self.root_path))

        for file_path in self._walk_directory(self.root_path, current_depth=0):
            # Skip if gitignore says so (already covered by _walk_directory items,
            # but adding for safety if logic changes)
            if self.gitignore_filter and self.gitignore_filter.should_ignore(file_path):
                continue

            # Skip non-files
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
                metadata={"engine": "python"},
            )

            discovered_files.append(discovered_file)

        return discovered_files

    def _walk_directory(self, directory: Path, current_depth: int) -> list[Path]:
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

        paths: list[Path] = []

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
        self, files: list[DiscoveredFile], start_time: float
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

    def get_analyzable_files(self) -> list[Path]:
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

    async def get_analyzable_files_async(self) -> list[Path]:
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

    def get_files_by_type(self, file_type: FileType) -> list[Path]:
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


async def discover_project_files_async(
    project_root: str | Path,
    max_depth: int | None = None,
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
        >>> result = await discover_project_files_async("/path/to/project")
        >>> print(f"Found {result.stats.total_files} files")
        Found 123 files
    """
    discoverer = FileDiscoverer(
        root_path=project_root,
        max_depth=max_depth,
        use_gitignore=use_gitignore,
    )
    return await discoverer.discover_async()
