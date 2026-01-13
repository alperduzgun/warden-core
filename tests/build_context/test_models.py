"""
Tests for build_context.models module.

Tests Panel JSON compatibility and model functionality.
"""

import pytest
from warden.build_context.models import (
    BuildSystem,
    DependencyType,
    Dependency,
    BuildScript,
    BuildContext,
    create_empty_context,
)


class TestBuildSystem:
    """Test BuildSystem enum."""

    def test_enum_values(self) -> None:
        """Test enum has expected values."""
        assert BuildSystem.UNKNOWN.value == 0
        assert BuildSystem.NPM.value == 1
        assert BuildSystem.YARN.value == 2
        assert BuildSystem.POETRY.value == 5
        assert BuildSystem.PIP.value == 4

    def test_enum_serialization(self) -> None:
        """Test enum can be serialized to int."""
        assert BuildSystem.NPM.value == 1
        assert BuildSystem.POETRY.value == 5


class TestDependencyType:
    """Test DependencyType enum."""

    def test_enum_values(self) -> None:
        """Test enum has expected values."""
        assert DependencyType.PRODUCTION.value == 0
        assert DependencyType.DEVELOPMENT.value == 1
        assert DependencyType.OPTIONAL.value == 2
        assert DependencyType.PEER.value == 3


class TestDependency:
    """Test Dependency model."""

    def test_create_simple_dependency(self) -> None:
        """Test creating simple dependency."""
        dep = Dependency(
            name="fastapi",
            version=">=0.100.0",
            type=DependencyType.PRODUCTION,
            is_direct=True
        )

        assert dep.name == "fastapi"
        assert dep.version == ">=0.100.0"
        assert dep.type == DependencyType.PRODUCTION
        assert dep.is_direct is True
        assert dep.extras == []

    def test_create_dependency_with_extras(self) -> None:
        """Test creating dependency with extras."""
        dep = Dependency(
            name="httpx",
            version="0.24.1",
            type=DependencyType.PRODUCTION,
            is_direct=True,
            extras=["http2", "socks"]
        )

        assert dep.name == "httpx"
        assert dep.extras == ["http2", "socks"]

    def test_to_json(self) -> None:
        """Test converting to Panel JSON."""
        dep = Dependency(
            name="react",
            version="^18.2.0",
            type=DependencyType.PRODUCTION,
            is_direct=True
        )

        json_data = dep.to_json()

        assert json_data["name"] == "react"
        assert json_data["version"] == "^18.2.0"
        assert json_data["type"] == 0  # Enum serialized to int
        assert json_data["isDirect"] is True  # camelCase
        assert json_data["extras"] == []


class TestBuildScript:
    """Test BuildScript model."""

    def test_create_script(self) -> None:
        """Test creating build script."""
        script = BuildScript(
            name="build",
            command="tsc",
            description="Compile TypeScript"
        )

        assert script.name == "build"
        assert script.command == "tsc"
        assert script.description == "Compile TypeScript"

    def test_to_json(self) -> None:
        """Test converting to Panel JSON."""
        script = BuildScript(
            name="test",
            command="pytest",
            description="Run tests"
        )

        json_data = script.to_json()

        assert json_data["name"] == "test"
        assert json_data["command"] == "pytest"
        assert json_data["description"] == "Run tests"


class TestBuildContext:
    """Test BuildContext model."""

    def test_create_minimal_context(self) -> None:
        """Test creating minimal build context."""
        context = BuildContext(
            build_system=BuildSystem.NPM,
            project_path="/path/to/project"
        )

        assert context.build_system == BuildSystem.NPM
        assert context.project_path == "/path/to/project"
        assert context.dependencies == []
        assert context.dev_dependencies == []
        assert context.scripts == []

    def test_create_full_context(self) -> None:
        """Test creating full build context."""
        deps = [
            Dependency(name="fastapi", version=">=0.100.0"),
        ]
        dev_deps = [
            Dependency(name="pytest", version="^7.0.0", type=DependencyType.DEVELOPMENT),
        ]
        scripts = [
            BuildScript(name="test", command="pytest"),
        ]

        context = BuildContext(
            build_system=BuildSystem.POETRY,
            project_path="/path/to/project",
            project_name="my-app",
            project_version="1.0.0",
            project_description="My application",
            config_file_path="/path/to/project/pyproject.toml",
            dependencies=deps,
            dev_dependencies=dev_deps,
            scripts=scripts,
            python_version="^3.11",
        )

        assert context.build_system == BuildSystem.POETRY
        assert context.project_name == "my-app"
        assert context.project_version == "1.0.0"
        assert len(context.dependencies) == 1
        assert len(context.dev_dependencies) == 1
        assert len(context.scripts) == 1

    def test_get_all_dependencies(self) -> None:
        """Test getting all dependencies."""
        context = BuildContext(
            build_system=BuildSystem.NPM,
            project_path="/path/to/project",
            dependencies=[
                Dependency(name="react", version="^18.0.0"),
            ],
            dev_dependencies=[
                Dependency(name="typescript", version="^5.0.0"),
            ]
        )

        all_deps = context.get_all_dependencies()

        assert len(all_deps) == 2
        assert all_deps[0].name == "react"
        assert all_deps[1].name == "typescript"

    def test_get_dependency_by_name(self) -> None:
        """Test finding dependency by name."""
        context = BuildContext(
            build_system=BuildSystem.NPM,
            project_path="/path/to/project",
            dependencies=[
                Dependency(name="react", version="^18.0.0"),
                Dependency(name="vue", version="^3.0.0"),
            ]
        )

        dep = context.get_dependency_by_name("react")
        assert dep is not None
        assert dep.name == "react"

        # Test case-insensitive
        dep = context.get_dependency_by_name("REACT")
        assert dep is not None

        # Test not found
        dep = context.get_dependency_by_name("angular")
        assert dep is None

    def test_has_dependency(self) -> None:
        """Test checking if dependency exists."""
        context = BuildContext(
            build_system=BuildSystem.PIP,
            project_path="/path/to/project",
            dependencies=[
                Dependency(name="fastapi", version=">=0.100.0"),
            ]
        )

        assert context.has_dependency("fastapi") is True
        assert context.has_dependency("FASTAPI") is True  # Case-insensitive
        assert context.has_dependency("django") is False

    def test_get_production_dependencies(self) -> None:
        """Test getting only production dependencies."""
        context = BuildContext(
            build_system=BuildSystem.NPM,
            project_path="/path/to/project",
            dependencies=[
                Dependency(name="react", version="^18.0.0", type=DependencyType.PRODUCTION),
                Dependency(name="lodash", version="^4.0.0", type=DependencyType.OPTIONAL),
            ],
            dev_dependencies=[
                Dependency(name="typescript", version="^5.0.0", type=DependencyType.DEVELOPMENT),
            ]
        )

        prod_deps = context.get_production_dependencies()

        assert len(prod_deps) == 1
        assert prod_deps[0].name == "react"

    def test_get_script_by_name(self) -> None:
        """Test finding script by name."""
        context = BuildContext(
            build_system=BuildSystem.NPM,
            project_path="/path/to/project",
            scripts=[
                BuildScript(name="build", command="tsc"),
                BuildScript(name="test", command="jest"),
            ]
        )

        script = context.get_script_by_name("build")
        assert script is not None
        assert script.command == "tsc"

        script = context.get_script_by_name("deploy")
        assert script is None

    def test_has_script(self) -> None:
        """Test checking if script exists."""
        context = BuildContext(
            build_system=BuildSystem.NPM,
            project_path="/path/to/project",
            scripts=[
                BuildScript(name="build", command="tsc"),
            ]
        )

        assert context.has_script("build") is True
        assert context.has_script("test") is False

    def test_to_json(self) -> None:
        """Test converting to Panel JSON."""
        context = BuildContext(
            build_system=BuildSystem.NPM,
            project_path="/path/to/project",
            project_name="my-app",
            project_version="1.0.0",
            dependencies=[
                Dependency(name="react", version="^18.0.0"),
            ],
            scripts=[
                BuildScript(name="build", command="tsc"),
            ]
        )

        json_data = context.to_json()

        # Check camelCase conversion
        assert json_data["buildSystem"] == 1  # NPM enum value
        assert json_data["projectPath"] == "/path/to/project"
        assert json_data["projectName"] == "my-app"
        assert json_data["projectVersion"] == "1.0.0"

        # Check nested objects
        assert len(json_data["dependencies"]) == 1
        assert json_data["dependencies"][0]["name"] == "react"
        assert len(json_data["scripts"]) == 1
        assert json_data["scripts"][0]["name"] == "build"


class TestCreateEmptyContext:
    """Test create_empty_context helper function."""

    def test_create_empty_context(self) -> None:
        """Test creating empty context."""
        context = create_empty_context("/path/to/project")

        assert context.build_system == BuildSystem.UNKNOWN
        assert context.project_path == "/path/to/project"
        assert context.project_name == "Unknown Project"
        assert context.project_version == "0.0.0"
        assert context.dependencies == []
        assert context.dev_dependencies == []
