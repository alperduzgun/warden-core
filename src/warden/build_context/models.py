"""
Build context models for Panel compatibility.

These models represent build configuration and dependencies:
- BuildSystem: Enum for build systems (NPM, YARN, PIP, POETRY, etc.)
- Dependency: Individual dependency with version info
- BuildContext: Complete build configuration and dependencies

Panel JSON format: camelCase
Python internal format: snake_case
"""

from enum import Enum
from typing import Dict, Any, List, Optional

from pydantic import Field
from warden.shared.domain.base_model import BaseDomainModel


class BuildSystem(Enum):
    """
    Build system type.

    Panel TypeScript equivalent:
    ```typescript
    enum BuildSystem {
      UNKNOWN = 0,
      NPM = 1,
      YARN = 2,
      PNPM = 3,
      PIP = 4,
      POETRY = 5,
      PIPENV = 6,
      CONDA = 7,
      GRADLE = 8,
      MAVEN = 9,
      CARGO = 10,
      GO_MOD = 11,
      BUNDLE = 12,
      COMPOSER = 13
    }
    ```
    """

    UNKNOWN = 0
    NPM = 1
    YARN = 2
    PNPM = 3
    PIP = 4
    POETRY = 5
    PIPENV = 6
    CONDA = 7
    GRADLE = 8
    MAVEN = 9
    CARGO = 10
    GO_MOD = 11
    BUNDLE = 12
    COMPOSER = 13


class DependencyType(Enum):
    """
    Dependency type classification.

    Panel TypeScript equivalent:
    ```typescript
    enum DependencyType {
      PRODUCTION = 0,
      DEVELOPMENT = 1,
      OPTIONAL = 2,
      PEER = 3
    }
    ```
    """

    PRODUCTION = 0
    DEVELOPMENT = 1
    OPTIONAL = 2
    PEER = 3


class Dependency(BaseDomainModel):
    """
    Individual dependency with version info.

    Panel TypeScript equivalent:
    ```typescript
    export interface Dependency {
      name: string
      version: string
      type: DependencyType
      isDirect: boolean
      extras?: string[]
    }
    ```

    Examples:
    - NPM: { name: "react", version: "^18.2.0", type: PRODUCTION, isDirect: true }
    - Python: { name: "fastapi", version: ">=0.100.0", type: PRODUCTION, isDirect: true }
    - Python with extras: { name: "httpx", version: "0.24.1", extras: ["http2"] }
    """

    name: str
    version: str
    type: DependencyType = DependencyType.PRODUCTION
    is_direct: bool = True
    extras: List[str] = Field(default_factory=list)

    def to_json(self) -> Dict[str, Any]:
        """Convert to Panel-compatible JSON (camelCase)."""
        data = super().to_json()
        # Ensure extras is always present even if empty
        if 'extras' not in data:
            data['extras'] = []
        return data


class BuildScript(BaseDomainModel):
    """
    Build script definition.

    Panel TypeScript equivalent:
    ```typescript
    export interface BuildScript {
      name: string
      command: string
      description?: string
    }
    ```

    Examples:
    - { name: "build", command: "tsc", description: "Compile TypeScript" }
    - { name: "test", command: "pytest", description: "Run tests" }
    """

    name: str
    command: str
    description: Optional[str] = None


class BuildContext(BaseDomainModel):
    """
    Complete build configuration and dependencies.

    Panel TypeScript equivalent:
    ```typescript
    export interface BuildContext {
      buildSystem: BuildSystem
      projectName?: string
      projectVersion?: string
      projectDescription?: string
      projectPath: string
      configFilePath?: string
      dependencies: Dependency[]
      devDependencies: Dependency[]
      scripts: BuildScript[]
      pythonVersion?: string
      nodeVersion?: string
      engines?: { [key: string]: string }
      metadata: { [key: string]: any }
    }
    ```

    This is the primary model returned by BuildContextProvider.
    Contains all build-related information about a project.
    """

    build_system: BuildSystem
    project_path: str
    project_name: Optional[str] = None
    project_version: Optional[str] = None
    project_description: Optional[str] = None
    config_file_path: Optional[str] = None
    dependencies: List[Dependency] = Field(default_factory=list)
    dev_dependencies: List[Dependency] = Field(default_factory=list)
    scripts: List[BuildScript] = Field(default_factory=list)
    python_version: Optional[str] = None
    node_version: Optional[str] = None
    engines: Dict[str, str] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def to_json(self) -> Dict[str, Any]:
        """Convert to Panel-compatible JSON (camelCase)."""
        data = super().to_json()

        # Convert nested dependencies
        data['dependencies'] = [dep.to_json() for dep in self.dependencies]
        data['devDependencies'] = [dep.to_json() for dep in self.dev_dependencies]
        data['scripts'] = [script.to_json() for script in self.scripts]

        return data

    def get_all_dependencies(self) -> List[Dependency]:
        """Get all dependencies (production + dev)."""
        return self.dependencies + self.dev_dependencies

    def get_dependency_by_name(self, name: str) -> Optional[Dependency]:
        """Find dependency by name (case-insensitive)."""
        name_lower = name.lower()
        for dep in self.get_all_dependencies():
            if dep.name.lower() == name_lower:
                return dep
        return None

    def has_dependency(self, name: str) -> bool:
        """Check if dependency exists (case-insensitive)."""
        return self.get_dependency_by_name(name) is not None

    def get_production_dependencies(self) -> List[Dependency]:
        """Get only production dependencies."""
        return [
            dep for dep in self.get_all_dependencies()
            if dep.type == DependencyType.PRODUCTION
        ]

    def get_script_by_name(self, name: str) -> Optional[BuildScript]:
        """Find script by name."""
        for script in self.scripts:
            if script.name == name:
                return script
        return None

    def has_script(self, name: str) -> bool:
        """Check if script exists."""
        return self.get_script_by_name(name) is not None


def create_empty_context(project_path: str) -> BuildContext:
    """
    Create an empty build context for projects without detected build system.

    Args:
        project_path: Path to the project

    Returns:
        BuildContext with UNKNOWN build system
    """
    return BuildContext(
        build_system=BuildSystem.UNKNOWN,
        project_path=project_path,
        project_name="Unknown Project",
        project_version="0.0.0",
        project_description="No build system detected"
    )
