"""
Pyproject.toml parser for Poetry/PEP 621 projects.

Extracts build configuration and dependencies from pyproject.toml files.
"""

from pathlib import Path
from typing import Optional, Dict, Any, List
import re

from warden.build_context.models import (
    BuildContext,
    BuildSystem,
    Dependency,
    DependencyType,
    BuildScript,
)


class PyprojectParser:
    """
    Parser for pyproject.toml files.

    Supports:
    - Poetry projects ([tool.poetry])
    - PEP 621 projects ([project])
    - Extracts dependencies with version constraints and extras
    """

    def __init__(self, project_path: str) -> None:
        """
        Initialize parser.

        Args:
            project_path: Path to project root directory
        """
        self.project_path = Path(project_path)
        self.pyproject_path = self.project_path / "pyproject.toml"

    def can_parse(self) -> bool:
        """
        Check if pyproject.toml exists.

        Returns:
            True if pyproject.toml exists
        """
        return self.pyproject_path.exists()

    def detect_build_system(self) -> BuildSystem:
        """
        Detect specific build system (Poetry or generic PIP).

        Checks for Poetry-specific sections.

        Returns:
            POETRY or PIP
        """
        if not self.can_parse():
            return BuildSystem.PIP

        try:
            content = self.pyproject_path.read_text(encoding="utf-8")
            if "[tool.poetry]" in content:
                return BuildSystem.POETRY
            else:
                return BuildSystem.PIP
        except IOError:
            return BuildSystem.PIP

    def parse(self) -> Optional[BuildContext]:
        """
        Parse pyproject.toml and extract build context.

        Returns:
            BuildContext if successful, None if parsing fails
        """
        if not self.can_parse():
            return None

        try:
            # Use simple TOML parsing (no external dependencies)
            data = self._parse_toml(self.pyproject_path)

            build_system = self.detect_build_system()

            # Try Poetry format first
            if "tool" in data and "poetry" in data["tool"]:
                return self._parse_poetry(data, build_system)
            # Try PEP 621 format
            elif "project" in data:
                return self._parse_pep621(data, build_system)
            else:
                return None

        except (IOError, ValueError) as e:
            print(f"Error parsing pyproject.toml: {e}")
            return None

    def _parse_poetry(
        self,
        data: Dict[str, Any],
        build_system: BuildSystem
    ) -> BuildContext:
        """
        Parse Poetry-style pyproject.toml.

        Args:
            data: Parsed TOML data
            build_system: Detected build system

        Returns:
            BuildContext
        """
        poetry = data["tool"]["poetry"]

        project_name = poetry.get("name")
        project_version = poetry.get("version")
        project_description = poetry.get("description")

        # Extract Python version
        python_version = None
        deps_raw = poetry.get("dependencies", {})
        if "python" in deps_raw:
            python_version = str(deps_raw["python"])

        # Parse dependencies
        dependencies = self._parse_poetry_dependencies(
            deps_raw,
            exclude=["python"]
        )

        # Parse dev dependencies
        dev_dependencies = self._parse_poetry_dependencies(
            poetry.get("dev-dependencies", {})
        )

        # Also check group.dev.dependencies (Poetry 1.2+)
        if "group" in poetry and "dev" in poetry["group"]:
            dev_deps_group = self._parse_poetry_dependencies(
                poetry["group"]["dev"].get("dependencies", {})
            )
            dev_dependencies.extend(dev_deps_group)

        # Extract scripts
        scripts = self._parse_poetry_scripts(poetry.get("scripts", {}))

        # Extract metadata
        metadata: Dict[str, Any] = {}
        for key in ["authors", "license", "repository", "keywords", "homepage"]:
            if key in poetry:
                metadata[key] = poetry[key]

        return BuildContext(
            build_system=build_system,
            project_path=str(self.project_path),
            project_name=project_name,
            project_version=project_version,
            project_description=project_description,
            config_file_path=str(self.pyproject_path),
            dependencies=dependencies,
            dev_dependencies=dev_dependencies,
            scripts=scripts,
            python_version=python_version,
            metadata=metadata,
        )

    def _parse_pep621(
        self,
        data: Dict[str, Any],
        build_system: BuildSystem
    ) -> BuildContext:
        """
        Parse PEP 621-style pyproject.toml.

        Args:
            data: Parsed TOML data
            build_system: Detected build system

        Returns:
            BuildContext
        """
        project = data["project"]

        project_name = project.get("name")
        project_version = project.get("version")
        project_description = project.get("description")

        # Parse dependencies
        dependencies = self._parse_pep621_dependencies(
            project.get("dependencies", [])
        )

        # Parse optional dependencies (dev, test, etc.)
        dev_dependencies: List[Dependency] = []
        optional_deps = project.get("optional-dependencies", {})
        for group_name, group_deps in optional_deps.items():
            parsed = self._parse_pep621_dependencies(group_deps)
            if group_name in ["dev", "development", "test", "testing"]:
                dev_dependencies.extend(parsed)
            else:
                dependencies.extend(parsed)

        # Extract Python version
        python_version = None
        requires_python = project.get("requires-python")
        if requires_python:
            python_version = requires_python

        # Extract scripts
        scripts = self._parse_pep621_scripts(project.get("scripts", {}))

        # Extract metadata
        metadata: Dict[str, Any] = {}
        for key in ["authors", "license", "repository", "keywords", "homepage"]:
            if key in project:
                metadata[key] = project[key]

        return BuildContext(
            build_system=build_system,
            project_path=str(self.project_path),
            project_name=project_name,
            project_version=project_version,
            project_description=project_description,
            config_file_path=str(self.pyproject_path),
            dependencies=dependencies,
            dev_dependencies=dev_dependencies,
            scripts=scripts,
            python_version=python_version,
            metadata=metadata,
        )

    def _parse_poetry_dependencies(
        self,
        deps_dict: Dict[str, Any],
        exclude: Optional[List[str]] = None
    ) -> List[Dependency]:
        """
        Parse Poetry dependencies.

        Poetry format:
        - Simple: package = "^1.0.0"
        - Complex: package = { version = "^1.0.0", extras = ["extra1"] }

        Args:
            deps_dict: Dependencies dictionary
            exclude: Package names to exclude

        Returns:
            List of Dependency objects
        """
        dependencies: List[Dependency] = []
        exclude = exclude or []

        for name, spec in deps_dict.items():
            if name in exclude:
                continue

            # Simple version string
            if isinstance(spec, str):
                dependencies.append(
                    Dependency(
                        name=name,
                        version=spec,
                        type=DependencyType.PRODUCTION,
                        is_direct=True
                    )
                )
            # Complex dependency dict
            elif isinstance(spec, dict):
                version = spec.get("version", "*")
                extras = spec.get("extras", [])

                dependencies.append(
                    Dependency(
                        name=name,
                        version=version,
                        type=DependencyType.PRODUCTION,
                        is_direct=True,
                        extras=extras
                    )
                )

        return dependencies

    def _parse_pep621_dependencies(
        self,
        deps_list: List[str]
    ) -> List[Dependency]:
        """
        Parse PEP 621 dependencies.

        Format: "package>=1.0.0" or "package[extra1,extra2]>=1.0.0"

        Args:
            deps_list: List of dependency strings

        Returns:
            List of Dependency objects
        """
        dependencies: List[Dependency] = []

        for dep_str in deps_list:
            parsed = self._parse_requirement_string(dep_str)
            if parsed:
                dependencies.append(parsed)

        return dependencies

    def _parse_requirement_string(self, req_str: str) -> Optional[Dependency]:
        """
        Parse a single requirement string.

        Examples:
        - "package>=1.0.0"
        - "package[extra1,extra2]>=1.0.0"
        - "package==1.0.0"

        Args:
            req_str: Requirement string

        Returns:
            Dependency if valid, None otherwise
        """
        # Pattern: name[extras]version_spec
        pattern = r'^([a-zA-Z0-9_-]+)(?:\[([^\]]+)\])?(.*)?$'
        match = re.match(pattern, req_str.strip())

        if not match:
            return None

        name = match.group(1)
        extras_str = match.group(2)
        version = match.group(3).strip() if match.group(3) else "*"

        extras: List[str] = []
        if extras_str:
            extras = [e.strip() for e in extras_str.split(",")]

        return Dependency(
            name=name,
            version=version if version else "*",
            type=DependencyType.PRODUCTION,
            is_direct=True,
            extras=extras
        )

    def _parse_poetry_scripts(
        self,
        scripts_dict: Dict[str, str]
    ) -> List[BuildScript]:
        """
        Parse Poetry scripts.

        Args:
            scripts_dict: Scripts dictionary

        Returns:
            List of BuildScript objects
        """
        scripts: List[BuildScript] = []

        for name, command in scripts_dict.items():
            scripts.append(
                BuildScript(
                    name=name,
                    command=command
                )
            )

        return scripts

    def _parse_pep621_scripts(
        self,
        scripts_dict: Dict[str, str]
    ) -> List[BuildScript]:
        """
        Parse PEP 621 scripts.

        Args:
            scripts_dict: Scripts dictionary

        Returns:
            List of BuildScript objects
        """
        return self._parse_poetry_scripts(scripts_dict)

    def _parse_toml(self, path: Path) -> Dict[str, Any]:
        """
        Simple TOML parser (basic support only).

        This is a minimal implementation to avoid external dependencies.
        Only supports basic TOML syntax needed for pyproject.toml.

        Args:
            path: Path to TOML file

        Returns:
            Parsed data dictionary
        """
        try:
            import tomllib  # Python 3.11+
            with open(path, "rb") as f:
                return tomllib.load(f)
        except ImportError:
            try:
                import tomli  # Fallback for Python < 3.11
                with open(path, "rb") as f:
                    return tomli.load(f)  # type: ignore
            except ImportError:
                # Fallback to basic parsing if no TOML library available
                return self._basic_toml_parse(path)

    def _basic_toml_parse(self, path: Path) -> Dict[str, Any]:
        """
        Very basic TOML parsing fallback.

        Only handles simple cases needed for pyproject.toml.

        Args:
            path: Path to TOML file

        Returns:
            Parsed data dictionary
        """
        result: Dict[str, Any] = {}
        current_section: List[str] = []

        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()

                # Skip empty lines and comments
                if not line or line.startswith("#"):
                    continue

                # Section header
                if line.startswith("[") and line.endswith("]"):
                    section = line[1:-1]
                    current_section = section.split(".")

                    # Create nested dict structure
                    current = result
                    for part in current_section[:-1]:
                        if part not in current:
                            current[part] = {}
                        current = current[part]

                    if current_section[-1] not in current:
                        current[current_section[-1]] = {}

                # Key-value pair
                elif "=" in line:
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip()

                    # Remove quotes
                    if value.startswith('"') and value.endswith('"'):
                        value = value[1:-1]

                    # Navigate to current section
                    current = result
                    for part in current_section:
                        if part not in current:
                            current[part] = {}
                        current = current[part]

                    current[key] = value

        return result
