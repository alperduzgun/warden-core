"""
Tests for build_context.context_provider module.

Tests auto-detection and parsing of various build configurations.
"""

import pytest
import tempfile
import json
from pathlib import Path
from typing import Generator

from warden.build_context import (
    BuildContextProvider,
    BuildSystem,
    get_build_context_sync,
)


@pytest.fixture
def temp_project_dir() -> Generator[Path, None, None]:
    """Create temporary project directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


class TestBuildContextProvider:
    """Test BuildContextProvider class."""

    def test_init_with_valid_path(self, temp_project_dir: Path) -> None:
        """Test initializing with valid project path."""
        provider = BuildContextProvider(str(temp_project_dir))
        assert provider.project_path == temp_project_dir

    def test_init_with_invalid_path(self) -> None:
        """Test initializing with invalid path raises error."""
        with pytest.raises(ValueError, match="does not exist"):
            BuildContextProvider("/nonexistent/path")

    def test_init_with_file_path(self, temp_project_dir: Path) -> None:
        """Test initializing with file path raises error."""
        file_path = temp_project_dir / "test.txt"
        file_path.write_text("test")

        with pytest.raises(ValueError, match="not a directory"):
            BuildContextProvider(str(file_path))

    def test_has_build_config_empty_project(self, temp_project_dir: Path) -> None:
        """Test has_build_config returns False for empty project."""
        provider = BuildContextProvider(str(temp_project_dir))
        assert provider.has_build_config() is False

    def test_has_build_config_with_package_json(self, temp_project_dir: Path) -> None:
        """Test has_build_config returns True with package.json."""
        (temp_project_dir / "package.json").write_text("{}")
        provider = BuildContextProvider(str(temp_project_dir))
        assert provider.has_build_config() is True

    def test_has_build_config_with_pyproject(self, temp_project_dir: Path) -> None:
        """Test has_build_config returns True with pyproject.toml."""
        (temp_project_dir / "pyproject.toml").write_text("")
        provider = BuildContextProvider(str(temp_project_dir))
        assert provider.has_build_config() is True

    def test_has_build_config_with_requirements(self, temp_project_dir: Path) -> None:
        """Test has_build_config returns True with requirements.txt."""
        (temp_project_dir / "requirements.txt").write_text("")
        provider = BuildContextProvider(str(temp_project_dir))
        assert provider.has_build_config() is True

    def test_get_config_files_empty_project(self, temp_project_dir: Path) -> None:
        """Test get_config_files returns empty list for empty project."""
        provider = BuildContextProvider(str(temp_project_dir))
        files = provider.get_config_files()
        assert files == []

    def test_get_config_files_npm_project(self, temp_project_dir: Path) -> None:
        """Test get_config_files returns NPM files."""
        (temp_project_dir / "package.json").write_text("{}")
        (temp_project_dir / "package-lock.json").write_text("{}")

        provider = BuildContextProvider(str(temp_project_dir))
        files = provider.get_config_files()

        assert "package.json" in files
        assert "package-lock.json" in files

    def test_get_config_files_poetry_project(self, temp_project_dir: Path) -> None:
        """Test get_config_files returns Poetry files."""
        (temp_project_dir / "pyproject.toml").write_text("")
        (temp_project_dir / "poetry.lock").write_text("")

        provider = BuildContextProvider(str(temp_project_dir))
        files = provider.get_config_files()

        assert "pyproject.toml" in files
        assert "poetry.lock" in files

    def test_detect_build_system_unknown(self, temp_project_dir: Path) -> None:
        """Test detect_build_system returns UNKNOWN for empty project."""
        provider = BuildContextProvider(str(temp_project_dir))
        build_system = provider.detect_build_system()
        assert build_system == BuildSystem.UNKNOWN

    def test_detect_build_system_npm(self, temp_project_dir: Path) -> None:
        """Test detect_build_system returns NPM."""
        (temp_project_dir / "package.json").write_text("{}")
        (temp_project_dir / "package-lock.json").write_text("{}")

        provider = BuildContextProvider(str(temp_project_dir))
        build_system = provider.detect_build_system()
        assert build_system == BuildSystem.NPM

    def test_detect_build_system_yarn(self, temp_project_dir: Path) -> None:
        """Test detect_build_system returns YARN."""
        (temp_project_dir / "package.json").write_text("{}")
        (temp_project_dir / "yarn.lock").write_text("")

        provider = BuildContextProvider(str(temp_project_dir))
        build_system = provider.detect_build_system()
        assert build_system == BuildSystem.YARN

    def test_detect_build_system_pnpm(self, temp_project_dir: Path) -> None:
        """Test detect_build_system returns PNPM."""
        (temp_project_dir / "package.json").write_text("{}")
        (temp_project_dir / "pnpm-lock.yaml").write_text("")

        provider = BuildContextProvider(str(temp_project_dir))
        build_system = provider.detect_build_system()
        assert build_system == BuildSystem.PNPM

    def test_detect_build_system_poetry(self, temp_project_dir: Path) -> None:
        """Test detect_build_system returns POETRY."""
        (temp_project_dir / "pyproject.toml").write_text("[tool.poetry]")

        provider = BuildContextProvider(str(temp_project_dir))
        build_system = provider.detect_build_system()
        assert build_system == BuildSystem.POETRY

    def test_detect_build_system_pip(self, temp_project_dir: Path) -> None:
        """Test detect_build_system returns PIP."""
        (temp_project_dir / "requirements.txt").write_text("")

        provider = BuildContextProvider(str(temp_project_dir))
        build_system = provider.detect_build_system()
        assert build_system == BuildSystem.PIP

    def test_get_context_empty_project(self, temp_project_dir: Path) -> None:
        """Test get_context returns empty context for project without config."""
        provider = BuildContextProvider(str(temp_project_dir))
        context = provider.get_context()

        assert context.build_system == BuildSystem.UNKNOWN
        assert context.project_path == str(temp_project_dir)
        assert context.project_name == "Unknown Project"

    def test_get_context_npm_project(self, temp_project_dir: Path) -> None:
        """Test get_context parses NPM project."""
        package_json = {
            "name": "my-app",
            "version": "1.0.0",
            "description": "My application",
            "dependencies": {
                "react": "^18.2.0",
                "lodash": "^4.17.21"
            },
            "devDependencies": {
                "typescript": "^5.0.0"
            },
            "scripts": {
                "build": "tsc",
                "test": "jest"
            }
        }

        (temp_project_dir / "package.json").write_text(json.dumps(package_json))
        (temp_project_dir / "package-lock.json").write_text("{}")

        provider = BuildContextProvider(str(temp_project_dir))
        context = provider.get_context()

        assert context.build_system == BuildSystem.NPM
        assert context.project_name == "my-app"
        assert context.project_version == "1.0.0"
        assert context.project_description == "My application"
        assert len(context.dependencies) == 2
        assert len(context.dev_dependencies) == 1
        assert len(context.scripts) == 2

        # Check dependencies
        react_dep = context.get_dependency_by_name("react")
        assert react_dep is not None
        assert react_dep.version == "^18.2.0"

        # Check scripts
        assert context.has_script("build")
        assert context.has_script("test")

    def test_get_context_poetry_project(self, temp_project_dir: Path) -> None:
        """Test get_context parses Poetry project."""
        pyproject_content = """
[tool.poetry]
name = "my-python-app"
version = "0.1.0"
description = "My Python application"

[tool.poetry.dependencies]
python = "^3.11"
fastapi = "^0.100.0"

[tool.poetry.dev-dependencies]
pytest = "^7.0.0"
"""

        (temp_project_dir / "pyproject.toml").write_text(pyproject_content)

        provider = BuildContextProvider(str(temp_project_dir))
        context = provider.get_context()

        assert context.build_system == BuildSystem.POETRY
        assert context.project_name == "my-python-app"
        assert context.project_version == "0.1.0"
        assert context.python_version == "^3.11"

        # Should have fastapi but not python in dependencies
        assert context.has_dependency("fastapi")
        assert not context.has_dependency("python")

    def test_get_context_requirements_project(self, temp_project_dir: Path) -> None:
        """Test get_context parses requirements.txt project."""
        requirements = """
# Production dependencies
fastapi>=0.100.0
uvicorn[standard]==0.23.0
pydantic>=2.0.0

# Comments and blank lines are ignored
"""

        (temp_project_dir / "requirements.txt").write_text(requirements)

        provider = BuildContextProvider(str(temp_project_dir))
        context = provider.get_context()

        assert context.build_system == BuildSystem.PIP
        assert len(context.dependencies) == 3

        # Check specific dependencies
        fastapi_dep = context.get_dependency_by_name("fastapi")
        assert fastapi_dep is not None
        assert fastapi_dep.version == ">=0.100.0"

        uvicorn_dep = context.get_dependency_by_name("uvicorn")
        assert uvicorn_dep is not None
        assert uvicorn_dep.version == "==0.23.0"
        assert "standard" in uvicorn_dep.extras

    def test_get_context_priority_package_json_over_pyproject(
        self,
        temp_project_dir: Path
    ) -> None:
        """Test package.json takes priority over pyproject.toml."""
        # Create both files
        (temp_project_dir / "package.json").write_text('{"name": "npm-project"}')
        (temp_project_dir / "pyproject.toml").write_text("[tool.poetry]\nname = 'poetry-project'")

        provider = BuildContextProvider(str(temp_project_dir))
        context = provider.get_context()

        # Should use package.json
        assert context.project_name == "npm-project"

    def test_get_context_priority_pyproject_over_requirements(
        self,
        temp_project_dir: Path
    ) -> None:
        """Test pyproject.toml takes priority over requirements.txt."""
        # Create both files
        (temp_project_dir / "pyproject.toml").write_text("[tool.poetry]\nname = 'poetry-project'")
        (temp_project_dir / "requirements.txt").write_text("fastapi>=0.100.0")

        provider = BuildContextProvider(str(temp_project_dir))
        context = provider.get_context()

        # Should use pyproject.toml
        assert context.project_name == "poetry-project"

    @pytest.mark.asyncio
    async def test_get_context_async(self, temp_project_dir: Path) -> None:
        """Test async context retrieval."""
        package_json = {"name": "async-app", "version": "1.0.0"}
        (temp_project_dir / "package.json").write_text(json.dumps(package_json))

        provider = BuildContextProvider(str(temp_project_dir))
        context = await provider.get_context_async()

        assert context.project_name == "async-app"
        assert context.project_version == "1.0.0"


class TestConvenienceFunctions:
    """Test convenience functions."""

    def test_get_build_context_sync(self, temp_project_dir: Path) -> None:
        """Test get_build_context_sync convenience function."""
        package_json = {"name": "test-app"}
        (temp_project_dir / "package.json").write_text(json.dumps(package_json))

        context = get_build_context_sync(str(temp_project_dir))

        assert context.project_name == "test-app"
