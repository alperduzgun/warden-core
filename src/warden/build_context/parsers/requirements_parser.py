"""
Requirements.txt parser for pip-based projects.

Extracts dependencies from requirements.txt and related files.
"""

import re
from pathlib import Path
from typing import Optional, List, Set

from warden.build_context.models import (
    BuildContext,
    BuildSystem,
    Dependency,
    DependencyType,
)


class RequirementsParser:
    """
    Parser for requirements.txt files.

    Supports:
    - requirements.txt (production dependencies)
    - requirements-dev.txt (development dependencies)
    - requirements/*.txt (multiple requirement files)
    - Comments and blank lines
    - -r include directives
    - -e editable installs
    """

    def __init__(self, project_path: str) -> None:
        """
        Initialize parser.

        Args:
            project_path: Path to project root directory
        """
        self.project_path = Path(project_path)
        self.requirements_path = self.project_path / "requirements.txt"

    def can_parse(self) -> bool:
        """
        Check if requirements.txt exists.

        Returns:
            True if requirements.txt exists
        """
        return self.requirements_path.exists()

    def parse(self) -> Optional[BuildContext]:
        """
        Parse requirements.txt and extract build context.

        Returns:
            BuildContext if successful, None if parsing fails
        """
        if not self.can_parse():
            return None

        try:
            # Parse main requirements file
            dependencies = self._parse_requirements_file(
                self.requirements_path,
                visited=set()
            )

            # Parse dev requirements if exists
            dev_dependencies: List[Dependency] = []
            dev_paths = [
                self.project_path / "requirements-dev.txt",
                self.project_path / "requirements_dev.txt",
                self.project_path / "dev-requirements.txt",
                self.project_path / "requirements" / "dev.txt",
                self.project_path / "requirements" / "development.txt",
            ]

            for dev_path in dev_paths:
                if dev_path.exists():
                    dev_deps = self._parse_requirements_file(
                        dev_path,
                        visited=set()
                    )
                    dev_dependencies.extend(dev_deps)
                    break  # Only parse first found dev requirements

            # Try to detect project name from setup.py or directory name
            project_name = self._detect_project_name()

            return BuildContext(
                build_system=BuildSystem.PIP,
                project_path=str(self.project_path),
                project_name=project_name,
                config_file_path=str(self.requirements_path),
                dependencies=dependencies,
                dev_dependencies=dev_dependencies,
            )

        except IOError as e:
            print(f"Error parsing requirements.txt: {e}")
            return None

    def _parse_requirements_file(
        self,
        file_path: Path,
        visited: Set[Path]
    ) -> List[Dependency]:
        """
        Parse a single requirements file.

        Handles:
        - Package specifications
        - -r include directives (recursive)
        - -e editable installs
        - Comments and blank lines

        Args:
            file_path: Path to requirements file
            visited: Set of already visited files (prevent infinite loops)

        Returns:
            List of Dependency objects
        """
        if file_path in visited:
            return []

        visited.add(file_path)
        dependencies: List[Dependency] = []

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()

                    # Skip empty lines and comments
                    if not line or line.startswith("#"):
                        continue

                    # Handle -r include directive
                    if line.startswith("-r "):
                        include_path = file_path.parent / line[3:].strip()
                        if include_path.exists():
                            included_deps = self._parse_requirements_file(
                                include_path,
                                visited
                            )
                            dependencies.extend(included_deps)
                        continue

                    # Handle -e editable install
                    if line.startswith("-e "):
                        # Extract package name from editable install
                        dep = self._parse_editable_requirement(line[3:].strip())
                        if dep:
                            dependencies.append(dep)
                        continue

                    # Parse regular requirement
                    dep = self._parse_requirement_line(line)
                    if dep:
                        dependencies.append(dep)

        except IOError:
            pass

        return dependencies

    def _parse_requirement_line(self, line: str) -> Optional[Dependency]:
        """
        Parse a single requirement line.

        Supports:
        - package==1.0.0
        - package>=1.0.0
        - package~=1.0.0
        - package[extra1,extra2]>=1.0.0
        - package; python_version >= "3.8"

        Args:
            line: Requirement line

        Returns:
            Dependency if valid, None otherwise
        """
        # Remove environment markers (; python_version >= "3.8")
        if ";" in line:
            line = line.split(";")[0].strip()

        # Pattern: name[extras]version_spec
        # Matches: package, package==1.0, package[extra]>=1.0
        pattern = r'^([a-zA-Z0-9_-]+)(?:\[([^\]]+)\])?(.*)?$'
        match = re.match(pattern, line.strip())

        if not match:
            return None

        name = match.group(1)
        extras_str = match.group(2)
        version = match.group(3).strip() if match.group(3) else ""

        # Parse extras
        extras: List[str] = []
        if extras_str:
            extras = [e.strip() for e in extras_str.split(",")]

        # Clean version specifier
        if not version:
            version = "*"

        return Dependency(
            name=name,
            version=version,
            type=DependencyType.PRODUCTION,
            is_direct=True,
            extras=extras
        )

    def _parse_editable_requirement(self, line: str) -> Optional[Dependency]:
        """
        Parse editable requirement (-e flag).

        Examples:
        - -e git+https://github.com/user/repo.git#egg=package
        - -e ./local-package
        - -e .[dev]

        Args:
            line: Editable requirement line

        Returns:
            Dependency if valid, None otherwise
        """
        # Extract package name from #egg=package
        if "#egg=" in line:
            egg_match = re.search(r'#egg=([a-zA-Z0-9_-]+)', line)
            if egg_match:
                name = egg_match.group(1)
                return Dependency(
                    name=name,
                    version="@editable",
                    type=DependencyType.PRODUCTION,
                    is_direct=True
                )

        # Handle local editable installs (e.g., -e .)
        if line.startswith("."):
            # Try to get name from setup.py or pyproject.toml
            return Dependency(
                name="local-package",
                version="@editable",
                type=DependencyType.PRODUCTION,
                is_direct=True
            )

        return None

    def _detect_project_name(self) -> Optional[str]:
        """
        Try to detect project name from setup.py or directory.

        Returns:
            Project name if detected, None otherwise
        """
        # Try setup.py
        setup_py = self.project_path / "setup.py"
        if setup_py.exists():
            try:
                content = setup_py.read_text(encoding="utf-8")
                # Look for name= in setup()
                match = re.search(r'name\s*=\s*["\']([^"\']+)["\']', content)
                if match:
                    return match.group(1)
            except IOError:
                pass

        # Try pyproject.toml
        pyproject = self.project_path / "pyproject.toml"
        if pyproject.exists():
            try:
                content = pyproject.read_text(encoding="utf-8")
                # Look for name = "..."
                match = re.search(r'name\s*=\s*["\']([^"\']+)["\']', content)
                if match:
                    return match.group(1)
            except IOError:
                pass

        # Fallback to directory name
        return self.project_path.name
