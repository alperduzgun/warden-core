"""
Build context provider with auto-detection.

Main entry point for extracting build configuration from projects.
Auto-detects build system and uses appropriate parser.
"""

import asyncio
from pathlib import Path
from typing import Optional, List, Type

from warden.build_context.models import BuildContext, BuildSystem, create_empty_context
from warden.build_context.parsers import (
    PackageJsonParser,
    PyprojectParser,
    RequirementsParser,
)


class BuildContextProvider:
    """
    Auto-detects and extracts build configuration from projects.

    Usage:
    ```python
    provider = BuildContextProvider("/path/to/project")
    context = await provider.get_context_async()
    print(f"Build system: {context.build_system}")
    print(f"Dependencies: {len(context.dependencies)}")
    ```

    Supports:
    - JavaScript/TypeScript: package.json (NPM, Yarn, PNPM)
    - Python: pyproject.toml (Poetry, PEP 621), requirements.txt (Pip)
    - Priority: package.json > pyproject.toml > requirements.txt
    """

    def __init__(self, project_path: str) -> None:
        """
        Initialize provider.

        Args:
            project_path: Path to project root directory
        """
        self.project_path = Path(project_path)

        if not self.project_path.exists():
            raise ValueError(f"Project path does not exist: {project_path}")

        if not self.project_path.is_dir():
            raise ValueError(f"Project path is not a directory: {project_path}")

        # Initialize parsers
        self.parsers: List[object] = [
            PackageJsonParser(str(self.project_path)),
            PyprojectParser(str(self.project_path)),
            RequirementsParser(str(self.project_path)),
        ]

    async def get_context_async(self) -> BuildContext:
        """
        Get build context asynchronously.

        Auto-detects build system and parses configuration.

        Returns:
            BuildContext with detected configuration
        """
        # Run in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        context = await loop.run_in_executor(None, self.get_context)
        return context

    def get_context(self) -> BuildContext:
        """
        Get build context synchronously.

        Tries parsers in order:
        1. PackageJsonParser (package.json)
        2. PyprojectParser (pyproject.toml)
        3. RequirementsParser (requirements.txt)

        Returns:
            BuildContext with detected configuration, or empty context if no build system found
        """
        # Try each parser in order
        for parser in self.parsers:
            if hasattr(parser, "can_parse") and parser.can_parse():  # type: ignore
                context = parser.parse()  # type: ignore
                if context is not None:
                    return context

        # No build system detected - return empty context
        return create_empty_context(str(self.project_path))

    def detect_build_system(self) -> BuildSystem:
        """
        Detect build system without full parsing.

        Returns:
            Detected BuildSystem enum
        """
        # Check for package.json
        if (self.project_path / "package.json").exists():
            parser = PackageJsonParser(str(self.project_path))
            return parser.detect_build_system()

        # Check for pyproject.toml
        if (self.project_path / "pyproject.toml").exists():
            parser = PyprojectParser(str(self.project_path))
            return parser.detect_build_system()

        # Check for requirements.txt
        if (self.project_path / "requirements.txt").exists():
            return BuildSystem.PIP

        # No build system detected
        return BuildSystem.UNKNOWN

    def has_build_config(self) -> bool:
        """
        Check if project has any build configuration files.

        Returns:
            True if any build config file exists
        """
        config_files = [
            "package.json",
            "pyproject.toml",
            "requirements.txt",
        ]

        for config_file in config_files:
            if (self.project_path / config_file).exists():
                return True

        return False

    def get_config_files(self) -> List[str]:
        """
        Get list of existing build configuration files.

        Returns:
            List of config file names found in project
        """
        config_files = [
            "package.json",
            "package-lock.json",
            "yarn.lock",
            "pnpm-lock.yaml",
            "pyproject.toml",
            "poetry.lock",
            "requirements.txt",
            "requirements-dev.txt",
            "setup.py",
            "setup.cfg",
        ]

        found_files: List[str] = []

        for config_file in config_files:
            if (self.project_path / config_file).exists():
                found_files.append(config_file)

        return found_files


async def get_build_context(project_path: str) -> BuildContext:
    """
    Convenience function to get build context.

    Args:
        project_path: Path to project root directory

    Returns:
        BuildContext with detected configuration

    Example:
    ```python
    context = await get_build_context("/path/to/project")
    print(f"Build system: {context.build_system}")
    ```
    """
    provider = BuildContextProvider(project_path)
    return await provider.get_context_async()


def get_build_context_sync(project_path: str) -> BuildContext:
    """
    Convenience function to get build context synchronously.

    Args:
        project_path: Path to project root directory

    Returns:
        BuildContext with detected configuration

    Example:
    ```python
    context = get_build_context_sync("/path/to/project")
    print(f"Build system: {context.build_system}")
    ```
    """
    provider = BuildContextProvider(project_path)
    return provider.get_context()
