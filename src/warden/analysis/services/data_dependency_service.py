"""
DataDependencyService — orchestrates DDG build across project files.

Similar to TaintAnalysisService: runs once in Phase 0, result stored in
PipelineContext.data_dependency_graph, consumed by DataFlowAware frames.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from warden.analysis.application.data_dependency_builder import DataDependencyBuilder
from warden.analysis.domain.data_dependency_graph import DataDependencyGraph
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)

# Directories to exclude when collecting Python files.
# Checked via substring matching against each path component.
EXCLUDE_DIRS: frozenset[str] = frozenset(
    {
        ".venv",
        "venv",
        "env",
        "__pycache__",
        ".git",
        "node_modules",
        "dist",
        "build",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".warden",  # warden's own cache dir
    }
)

# Suffix patterns for generated / compiled files to skip.
EXCLUDE_SUFFIXES: frozenset[str] = frozenset({".egg-info", ".dist-info"})


class DataDependencyService:
    """
    Orchestrates the DataDependencyGraph build for a project.

    Collects all Python files from the project root (respecting well-known
    exclusion patterns for virtualenvs, caches, and generated directories),
    delegates parsing to :class:`DataDependencyBuilder`, and returns the
    populated :class:`DataDependencyGraph`.

    Args:
        project_root: Root directory of the project.
    """

    def __init__(self, project_root: str | Path) -> None:
        self.project_root = Path(project_root)
        self._builder = DataDependencyBuilder(project_root)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(self) -> DataDependencyGraph:
        """Build DDG for all Python files in the project.

        Returns:
            A populated :class:`DataDependencyGraph` with write/read nodes
            for all ``context.*`` field accesses found in Python source.
        """
        files = self._collect_python_files()
        logger.info(
            "ddg_service.build_started",
            project_root=str(self.project_root),
            file_count=len(files),
        )
        ddg = self._builder.build(files)
        logger.info(
            "ddg_service.build_complete",
            writes=len(ddg.writes),
            reads=len(ddg.reads),
            init_fields=len(ddg.init_fields),
        )
        return ddg

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _collect_python_files(self) -> list[Path]:
        """Collect ``.py`` files, excluding virtualenv/cache/generated dirs.

        Returns:
            Sorted list of absolute :class:`Path` objects for Python source
            files within ``project_root``, with excluded directories filtered
            out.
        """
        result: list[Path] = []
        for py_file in self.project_root.rglob("*.py"):
            if self._is_excluded(py_file):
                continue
            result.append(py_file)
        return sorted(result)

    def _is_excluded(self, path: Path) -> bool:
        """Return ``True`` when *path* should be excluded from analysis.

        Checks every component of the path relative to ``project_root``
        against :data:`EXCLUDE_DIRS` and :data:`EXCLUDE_SUFFIXES`.

        Args:
            path: Absolute path to test.

        Returns:
            ``True`` when the path is inside an excluded directory or has an
            excluded suffix.
        """
        try:
            rel = path.relative_to(self.project_root)
        except ValueError:
            # Path is outside project_root — exclude it to be safe.
            return True

        # Check each path part against excluded directory names
        for part in rel.parts[:-1]:  # skip the filename itself
            if part in EXCLUDE_DIRS:
                return True
            # Handle egg-info and dist-info directory suffixes
            for suffix in EXCLUDE_SUFFIXES:
                if part.endswith(suffix):
                    return True

        return False


def build_ddg_for_project(project_root: str | Path) -> DataDependencyGraph:
    """Convenience function: build DDG for a project root.

    Args:
        project_root: Root directory of the project.

    Returns:
        A populated :class:`DataDependencyGraph`.
    """
    service = DataDependencyService(project_root)
    return service.build()


__all__: list[Any] = [
    "DataDependencyService",
    "EXCLUDE_DIRS",
    "EXCLUDE_SUFFIXES",
    "build_ddg_for_project",
]
