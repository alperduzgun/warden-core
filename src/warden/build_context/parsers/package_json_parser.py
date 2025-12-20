"""
Package.json parser for NPM/Yarn/PNPM projects.

Extracts build configuration and dependencies from package.json files.
"""

import json
from pathlib import Path
from typing import Optional, Dict, Any, List

from warden.build_context.models import (
    BuildContext,
    BuildSystem,
    Dependency,
    DependencyType,
    BuildScript,
)


class PackageJsonParser:
    """
    Parser for package.json files.

    Detects NPM, Yarn, or PNPM based on lock files.
    Extracts dependencies, devDependencies, and scripts.
    """

    def __init__(self, project_path: str) -> None:
        """
        Initialize parser.

        Args:
            project_path: Path to project root directory
        """
        self.project_path = Path(project_path)
        self.package_json_path = self.project_path / "package.json"

    def can_parse(self) -> bool:
        """
        Check if package.json exists.

        Returns:
            True if package.json exists
        """
        return self.package_json_path.exists()

    def detect_build_system(self) -> BuildSystem:
        """
        Detect specific build system (NPM, Yarn, or PNPM).

        Checks for lock files:
        - pnpm-lock.yaml → PNPM
        - yarn.lock → YARN
        - package-lock.json → NPM
        - Default → NPM

        Returns:
            Detected build system
        """
        if (self.project_path / "pnpm-lock.yaml").exists():
            return BuildSystem.PNPM
        elif (self.project_path / "yarn.lock").exists():
            return BuildSystem.YARN
        elif (self.project_path / "package-lock.json").exists():
            return BuildSystem.NPM
        else:
            # Default to NPM if package.json exists but no lock file
            return BuildSystem.NPM

    def parse(self) -> Optional[BuildContext]:
        """
        Parse package.json and extract build context.

        Returns:
            BuildContext if successful, None if parsing fails
        """
        if not self.can_parse():
            return None

        try:
            with open(self.package_json_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            build_system = self.detect_build_system()

            # Extract basic project info
            project_name = data.get("name")
            project_version = data.get("version")
            project_description = data.get("description")

            # Extract dependencies
            dependencies = self._parse_dependencies(
                data.get("dependencies", {}),
                DependencyType.PRODUCTION
            )

            dev_dependencies = self._parse_dependencies(
                data.get("devDependencies", {}),
                DependencyType.DEVELOPMENT
            )

            # Handle peerDependencies
            peer_deps = self._parse_dependencies(
                data.get("peerDependencies", {}),
                DependencyType.PEER
            )
            dependencies.extend(peer_deps)

            # Handle optionalDependencies
            optional_deps = self._parse_dependencies(
                data.get("optionalDependencies", {}),
                DependencyType.OPTIONAL
            )
            dependencies.extend(optional_deps)

            # Extract scripts
            scripts = self._parse_scripts(data.get("scripts", {}))

            # Extract engines
            engines = data.get("engines", {})
            node_version = engines.get("node")

            # Extract additional metadata
            metadata: Dict[str, Any] = {}
            for key in ["author", "license", "repository", "keywords", "homepage"]:
                if key in data:
                    metadata[key] = data[key]

            return BuildContext(
                build_system=build_system,
                project_path=str(self.project_path),
                project_name=project_name,
                project_version=project_version,
                project_description=project_description,
                config_file_path=str(self.package_json_path),
                dependencies=dependencies,
                dev_dependencies=dev_dependencies,
                scripts=scripts,
                node_version=node_version,
                engines=engines,
                metadata=metadata,
            )

        except (json.JSONDecodeError, IOError) as e:
            # Log error but don't crash - return None
            print(f"Error parsing package.json: {e}")
            return None

    def _parse_dependencies(
        self,
        deps_dict: Dict[str, str],
        dep_type: DependencyType
    ) -> List[Dependency]:
        """
        Parse dependencies dictionary.

        Args:
            deps_dict: Dictionary of name -> version
            dep_type: Type of dependencies

        Returns:
            List of Dependency objects
        """
        dependencies: List[Dependency] = []

        for name, version in deps_dict.items():
            dependencies.append(
                Dependency(
                    name=name,
                    version=version,
                    type=dep_type,
                    is_direct=True
                )
            )

        return dependencies

    def _parse_scripts(self, scripts_dict: Dict[str, str]) -> List[BuildScript]:
        """
        Parse scripts dictionary.

        Args:
            scripts_dict: Dictionary of script name -> command

        Returns:
            List of BuildScript objects
        """
        scripts: List[BuildScript] = []

        for name, command in scripts_dict.items():
            scripts.append(
                BuildScript(
                    name=name,
                    command=command,
                    description=self._get_script_description(name)
                )
            )

        return scripts

    def _get_script_description(self, script_name: str) -> Optional[str]:
        """
        Get human-readable description for common script names.

        Args:
            script_name: Name of the script

        Returns:
            Description if known, None otherwise
        """
        descriptions = {
            "build": "Build the project",
            "test": "Run tests",
            "lint": "Lint code",
            "format": "Format code",
            "dev": "Start development server",
            "start": "Start application",
            "deploy": "Deploy application",
            "clean": "Clean build artifacts",
            "typecheck": "Run type checking",
            "coverage": "Generate test coverage report",
        }

        return descriptions.get(script_name)
