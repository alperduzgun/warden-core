"""
Project Context Model - Represents entire project structure for project-level validation.

This model provides a comprehensive view of the project structure, enabling
project-level frames to analyze architectural patterns, module organization,
and cross-file relationships.

Used by: ProjectArchitectureFrame, DependencyGraphFrame, etc.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Any, Optional, Set


@dataclass
class ModuleInfo:
    """
    Information about a Python module (directory with __init__.py).

    Attributes:
        path: Absolute path to module directory
        name: Module name (e.g., 'validation.frames.security')
        files: Python files in this module
        subdirectories: Subdirectories (potential submodules)
        is_empty: True if only __init__.py exists and it's empty
        line_count: Total lines of code in module
    """

    path: Path
    name: str
    files: List[Path]
    subdirectories: List[Path]
    is_empty: bool = False
    line_count: int = 0

    def __post_init__(self) -> None:
        """Calculate derived properties."""
        # Check if empty (only __init__.py with < 100 bytes)
        if len(self.files) == 1 and self.files[0].name == "__init__.py":
            if self.files[0].stat().st_size < 100:
                self.is_empty = True


@dataclass
class ProjectContext:
    """
    Complete project structure context for project-level validation.

    This model represents the entire project, enabling frames to analyze:
    - Module organization and architecture
    - Empty/redundant modules
    - Duplicate implementations
    - Architectural patterns
    - Cross-module dependencies

    Attributes:
        root_path: Project root directory (usually where .warden/ is)
        all_files: All Python files in project
        all_directories: All directories in project
        modules: Detected Python modules (directories with __init__.py)
        module_tree: Hierarchical module structure
        metadata: Additional project metadata (build system, dependencies, etc.)
    """

    root_path: Path
    all_files: List[Path] = field(default_factory=list)
    all_directories: List[Path] = field(default_factory=list)
    modules: List[ModuleInfo] = field(default_factory=list)
    module_tree: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_project_root(cls, root_path: Path) -> "ProjectContext":
        """
        Create ProjectContext by scanning project root.

        Args:
            root_path: Project root directory

        Returns:
            ProjectContext with discovered files and modules
        """
        context = cls(root_path=root_path)

        # Discover all files and directories
        context._discover_structure()

        # Detect Python modules
        context._discover_modules()

        # Build module tree
        context._build_module_tree()

        return context

    def _discover_structure(self) -> None:
        """Discover all files and directories in project."""
        # Find all Python files
        self.all_files = list(self.root_path.rglob("*.py"))

        # Find all directories
        self.all_directories = [
            d for d in self.root_path.rglob("*") if d.is_dir()
        ]

    def _discover_modules(self) -> None:
        """Discover Python modules (directories with __init__.py)."""
        for directory in self.all_directories:
            init_file = directory / "__init__.py"

            if init_file.exists():
                # Get all Python files in this directory
                files = list(directory.glob("*.py"))

                # Get subdirectories
                subdirs = [d for d in directory.iterdir() if d.is_dir()]

                # Calculate module name (relative to src/)
                module_name = self._get_module_name(directory)

                # Calculate total lines
                line_count = sum(
                    len(f.read_text().splitlines()) for f in files if f.exists()
                )

                module = ModuleInfo(
                    path=directory,
                    name=module_name,
                    files=files,
                    subdirectories=subdirs,
                    line_count=line_count,
                )

                self.modules.append(module)

    def _get_module_name(self, directory: Path) -> str:
        """
        Get Python module name from directory path.

        Example:
            /path/to/project/src/warden/validation/frames
            → warden.validation.frames
        """
        try:
            # Find 'src' directory in path
            parts = directory.parts
            if "src" in parts:
                src_idx = parts.index("src")
                # Module path starts after 'src'
                module_parts = parts[src_idx + 1 :]
                return ".".join(module_parts)
            else:
                # Fallback: relative to project root
                relative = directory.relative_to(self.root_path)
                return ".".join(relative.parts)
        except (ValueError, IndexError):
            return directory.name

    def _build_module_tree(self) -> None:
        """Build hierarchical module tree."""
        tree: Dict[str, Any] = {}

        for module in self.modules:
            parts = module.name.split(".")
            current = tree

            for part in parts:
                if part not in current:
                    current[part] = {}
                current = current[part]

        self.module_tree = tree

    # ==============================================
    # QUERY METHODS
    # ==============================================

    def get_empty_modules(self) -> List[ModuleInfo]:
        """
        Get all empty modules (only __init__.py with minimal content).

        Returns:
            List of empty ModuleInfo objects
        """
        return [m for m in self.modules if m.is_empty]

    def get_modules_by_pattern(self, pattern: str) -> List[ModuleInfo]:
        """
        Get modules matching name pattern.

        Args:
            pattern: Module name pattern (e.g., 'validation.frames.*')

        Returns:
            List of matching ModuleInfo objects
        """
        import fnmatch

        return [m for m in self.modules if fnmatch.fnmatch(m.name, pattern)]

    def get_duplicate_files(self) -> Dict[str, List[Path]]:
        """
        Find files with identical names in different locations.

        Returns:
            Dict mapping filename to list of paths
        """
        file_groups: Dict[str, List[Path]] = {}

        for file_path in self.all_files:
            filename = file_path.name
            if filename not in file_groups:
                file_groups[filename] = []
            file_groups[filename].append(file_path)

        # Return only duplicates (>1 file)
        return {name: paths for name, paths in file_groups.items() if len(paths) > 1}

    def has_clean_architecture_pattern(self) -> bool:
        """
        Check if project uses Clean Architecture pattern.

        Detects:
        - api/ directory
        - application/ directory
        - domain/ directory
        - infrastructure/ directory

        Returns:
            True if Clean Architecture pattern detected
        """
        patterns = ["api", "application", "domain", "infrastructure"]

        # Check if majority of these directories exist
        found_count = sum(1 for pattern in patterns if self._has_module_pattern(pattern))

        # Clean Architecture if 3+ layers found
        return found_count >= 3

    def has_analyzer_pattern(self) -> bool:
        """
        Check if project uses Analyzer Pattern.

        Detects:
        - analyzers/ directory
        - models/ directory
        - validation/ or validators/ directory

        Returns:
            True if Analyzer Pattern detected
        """
        patterns = ["analyzers", "models", "validation", "validators"]

        found_count = sum(1 for pattern in patterns if self._has_module_pattern(pattern))

        # Analyzer pattern if 2+ components found
        return found_count >= 2

    def _has_module_pattern(self, pattern: str) -> bool:
        """Check if any module name contains pattern."""
        return any(pattern in module.name.lower() for module in self.modules)

    def is_cli_tool(self) -> bool:
        """
        Check if project is a CLI/TUI tool (not web API).

        Detects:
        - cli/ directory
        - tui/ directory
        - No fastapi/flask/django dependencies

        Returns:
            True if CLI/TUI tool detected
        """
        # Check for CLI/TUI directories
        has_cli = self._has_module_pattern("cli")
        has_tui = self._has_module_pattern("tui")

        # Check for web framework imports (heuristic)
        has_web_framework = self._has_module_pattern("fastapi") or self._has_module_pattern(
            "flask"
        )

        return (has_cli or has_tui) and not has_web_framework

    def get_module_statistics(self) -> Dict[str, int]:
        """
        Get project module statistics.

        Returns:
            Dict with statistics
        """
        return {
            "total_modules": len(self.modules),
            "empty_modules": len(self.get_empty_modules()),
            "total_files": len(self.all_files),
            "total_directories": len(self.all_directories),
            "total_lines": sum(m.line_count for m in self.modules),
            "average_module_size": (
                sum(m.line_count for m in self.modules) // len(self.modules)
                if self.modules
                else 0
            ),
        }

    def __repr__(self) -> str:
        """String representation for debugging."""
        stats = self.get_module_statistics()
        return (
            f"ProjectContext("
            f"root={self.root_path.name}, "
            f"modules={stats['total_modules']}, "
            f"files={stats['total_files']}, "
            f"empty={stats['empty_modules']})"
        )
