"""
Tests for auto-installer functionality.
"""

import pytest
from pathlib import Path
import os

from warden.infrastructure.installer import (
    AutoInstaller,
    InstallConfig,
    InstallResult,
)


class TestAutoInstaller:
    """Test AutoInstaller functionality."""

    def test_detect_ci_platform_github(self, monkeypatch):
        """Test detecting GitHub Actions."""
        monkeypatch.setenv("GITHUB_ACTIONS", "true")

        platform = AutoInstaller.detect_ci_platform()

        assert platform == "github"

    def test_detect_ci_platform_gitlab(self, monkeypatch):
        """Test detecting GitLab CI."""
        monkeypatch.setenv("GITLAB_CI", "true")

        platform = AutoInstaller.detect_ci_platform()

        assert platform == "gitlab"

    def test_detect_ci_platform_azure(self, monkeypatch):
        """Test detecting Azure Pipelines."""
        monkeypatch.setenv("AZURE_HTTP_USER_AGENT", "Azure-Pipelines")

        platform = AutoInstaller.detect_ci_platform()

        assert platform == "azure"

    def test_detect_ci_platform_jenkins(self, monkeypatch):
        """Test detecting Jenkins."""
        monkeypatch.setenv("JENKINS_HOME", "/var/jenkins")

        platform = AutoInstaller.detect_ci_platform()

        assert platform == "jenkins"

    def test_detect_ci_platform_circleci(self, monkeypatch):
        """Test detecting CircleCI."""
        monkeypatch.setenv("CIRCLECI", "true")

        platform = AutoInstaller.detect_ci_platform()

        assert platform == "circleci"

    def test_detect_ci_platform_none(self, monkeypatch):
        """Test when no CI platform is detected."""
        # Clear all CI env vars
        ci_vars = [
            "GITHUB_ACTIONS",
            "GITLAB_CI",
            "AZURE_HTTP_USER_AGENT",
            "JENKINS_HOME",
            "CIRCLECI",
            "TRAVIS",
        ]
        for var in ci_vars:
            monkeypatch.delenv(var, raising=False)

        platform = AutoInstaller.detect_ci_platform()

        assert platform is None

    def test_discover_config_found(self, tmp_path):
        """Test discovering config file."""
        # Create config file
        config_dir = tmp_path / ".warden"
        config_dir.mkdir()
        config_file = config_dir / "config.yaml"
        config_file.write_text("version: '1.0'")

        discovered = AutoInstaller.discover_config(tmp_path)

        assert discovered == config_file

    def test_discover_config_parent(self, tmp_path):
        """Test discovering config in parent directory."""
        # Create config in parent
        config_dir = tmp_path / ".warden"
        config_dir.mkdir()
        config_file = config_dir / "config.yaml"
        config_file.write_text("version: '1.0'")

        # Search from subdirectory
        subdir = tmp_path / "subdir" / "deep"
        subdir.mkdir(parents=True)

        discovered = AutoInstaller.discover_config(subdir)

        assert discovered == config_file

    def test_discover_config_not_found(self, tmp_path):
        """Test when config file is not found."""
        discovered = AutoInstaller.discover_config(tmp_path)

        assert discovered is None

    def test_create_default_config(self, tmp_path):
        """Test creating default config file."""
        config_path = tmp_path / ".warden" / "config.yaml"

        created = AutoInstaller.create_default_config(config_path)

        assert created is True
        assert config_path.exists()

        content = config_path.read_text()
        assert "version:" in content
        assert "frames:" in content
        assert "infrastructure:" in content

    def test_get_ci_env_info_empty(self, monkeypatch):
        """Test getting CI env info when not in CI."""
        # Clear all CI env vars
        ci_vars = [
            "CI",
            "GITHUB_ACTIONS",
            "GITLAB_CI",
            "CIRCLECI",
            "TRAVIS",
            "JENKINS_HOME",
        ]
        for var in ci_vars:
            monkeypatch.delenv(var, raising=False)

        env_info = AutoInstaller.get_ci_env_info()

        assert env_info == {}

    def test_get_ci_env_info_github(self, monkeypatch):
        """Test getting CI env info for GitHub Actions."""
        monkeypatch.setenv("CI", "true")
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        monkeypatch.setenv("GITHUB_SHA", "abc123")

        env_info = AutoInstaller.get_ci_env_info()

        assert "CI" in env_info
        assert "GITHUB_ACTIONS" in env_info
        assert "GITHUB_SHA" in env_info
        assert env_info["GITHUB_SHA"] == "abc123"

    def test_generate_install_script_github(self):
        """Test generating GitHub Actions install script."""
        script = AutoInstaller.generate_install_script(platform="github")

        assert "GitHub Actions" in script
        assert "pip install warden-core" in script
        assert "warden --version" in script

    def test_generate_install_script_gitlab(self):
        """Test generating GitLab CI install script."""
        script = AutoInstaller.generate_install_script(platform="gitlab")

        assert "GitLab CI" in script
        assert "before_script:" in script
        assert "pip install warden-core" in script

    def test_generate_install_script_azure(self):
        """Test generating Azure Pipelines install script."""
        script = AutoInstaller.generate_install_script(platform="azure")

        assert "Azure Pipelines" in script
        assert "pip install warden-core" in script

    def test_generate_install_script_with_version(self):
        """Test generating install script with specific version."""
        script = AutoInstaller.generate_install_script(
            platform="github",
            version="1.0.0",
        )

        assert "pip install warden-core==1.0.0" in script

    def test_generate_dockerfile(self):
        """Test generating Dockerfile."""
        dockerfile = AutoInstaller.generate_dockerfile()

        assert "FROM python:3.11-slim" in dockerfile
        assert "pip install" in dockerfile
        assert "warden-core" in dockerfile
        assert "ENTRYPOINT" in dockerfile


class TestInstallConfig:
    """Test InstallConfig dataclass."""

    def test_default_config(self):
        """Test default configuration."""
        config = InstallConfig()

        assert config.version is None
        assert config.install_path is None
        assert config.config_path is None
        assert config.install_hooks is False
        assert config.verify_install is True

    def test_custom_config(self):
        """Test custom configuration."""
        config = InstallConfig(
            version="1.0.0",
            install_path=Path("/custom/path"),
            install_hooks=True,
            verify_install=False,
        )

        assert config.version == "1.0.0"
        assert config.install_path == Path("/custom/path")
        assert config.install_hooks is True
        assert config.verify_install is False


class TestInstallResult:
    """Test InstallResult dataclass."""

    def test_success_result(self):
        """Test success result."""
        result = InstallResult(
            success=True,
            message="Installation successful",
            version="1.0.0",
            config_discovered=True,
        )

        assert result.success is True
        assert result.version == "1.0.0"
        assert result.config_discovered is True

    def test_failure_result(self):
        """Test failure result."""
        result = InstallResult(
            success=False,
            message="Installation failed",
        )

        assert result.success is False
        assert result.version is None
        assert result.config_discovered is False
