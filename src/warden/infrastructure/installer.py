"""
Auto-installer for Warden in CI/CD environments.

Provides scripts and utilities for installing Warden in various CI platforms.
"""

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, List


@dataclass
class InstallConfig:
    """Configuration for Warden installation."""

    version: Optional[str] = None
    install_path: Optional[Path] = None
    config_path: Optional[Path] = None
    install_hooks: bool = False
    verify_install: bool = True


@dataclass
class InstallResult:
    """Result of Warden installation."""

    success: bool
    message: str
    version: Optional[str] = None
    install_path: Optional[str] = None
    config_discovered: bool = False


class AutoInstaller:
    """Auto-installer for Warden in CI/CD environments."""

    @staticmethod
    def detect_ci_platform() -> Optional[str]:
        """
        Detect current CI/CD platform from environment variables.

        Returns:
            Platform name or None
        """
        # GitHub Actions
        if os.getenv("GITHUB_ACTIONS"):
            return "github"

        # GitLab CI
        if os.getenv("GITLAB_CI"):
            return "gitlab"

        # Azure Pipelines
        if os.getenv("AZURE_HTTP_USER_AGENT"):
            return "azure"

        # Jenkins
        if os.getenv("JENKINS_HOME"):
            return "jenkins"

        # CircleCI
        if os.getenv("CIRCLECI"):
            return "circleci"

        # Travis CI
        if os.getenv("TRAVIS"):
            return "travis"

        return None

    @staticmethod
    def install(config: InstallConfig) -> InstallResult:
        """
        Install Warden.

        Args:
            config: Installation configuration

        Returns:
            Installation result
        """
        # Build pip install command
        if config.version:
            package = f"warden-core=={config.version}"
        else:
            package = "warden-core"

        cmd = [sys.executable, "-m", "pip", "install", package]

        if config.install_path:
            cmd.extend(["--target", str(config.install_path)])

        try:
            # Run pip install
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
            )

            if result.returncode != 0:
                return InstallResult(
                    success=False,
                    message=f"Installation failed: {result.stderr}",
                )

            # Verify installation
            if config.verify_install:
                verify_result = AutoInstaller._verify_install()
                if not verify_result.success:
                    return verify_result

            # Discover config
            config_discovered = False
            if config.config_path:
                config_discovered = config.config_path.exists()
            else:
                discovered_config = AutoInstaller.discover_config()
                config_discovered = discovered_config is not None

            # Install hooks if requested
            if config.install_hooks:
                from warden.infrastructure.hooks.installer import HookInstaller

                hook_results = HookInstaller.install_hooks()
                hooks_ok = all(r.installed for r in hook_results)
                if not hooks_ok:
                    return InstallResult(
                        success=False,
                        message="Hooks installation failed",
                    )

            version = AutoInstaller._get_installed_version()

            return InstallResult(
                success=True,
                message="Warden installed successfully",
                version=version,
                install_path=str(config.install_path) if config.install_path else None,
                config_discovered=config_discovered,
            )

        except Exception as e:
            return InstallResult(
                success=False,
                message=f"Installation error: {str(e)}",
            )

    @staticmethod
    def _verify_install() -> InstallResult:
        """Verify Warden installation."""
        try:
            result = subprocess.run(
                ["warden", "--version"],
                capture_output=True,
                text=True,
                check=False,
            )

            if result.returncode != 0:
                return InstallResult(
                    success=False,
                    message="Warden command not found after installation",
                )

            return InstallResult(
                success=True,
                message="Verification successful",
            )

        except Exception as e:
            return InstallResult(
                success=False,
                message=f"Verification failed: {str(e)}",
            )

    @staticmethod
    def _get_installed_version() -> Optional[str]:
        """Get installed Warden version."""
        try:
            result = subprocess.run(
                ["warden", "--version"],
                capture_output=True,
                text=True,
                check=False,
            )

            if result.returncode == 0:
                # Extract version from output
                version_line = result.stdout.strip()
                # Format: "warden, version 1.0.0"
                if "version" in version_line:
                    return version_line.split("version")[-1].strip()

            return None

        except Exception:
            return None

    @staticmethod
    def discover_config(start_path: Optional[Path] = None) -> Optional[Path]:
        """
        Discover Warden config file.

        Looks for .warden/config.yaml in current directory and parents.

        Args:
            start_path: Starting directory (default: current directory)

        Returns:
            Path to config file or None
        """
        if start_path is None:
            start_path = Path.cwd()

        current = start_path.resolve()

        while current != current.parent:
            config_path = current / ".warden" / "config.yaml"
            if config_path.exists():
                return config_path

            current = current.parent

        return None

    @staticmethod
    def create_default_config(output_path: Path) -> bool:
        """
        Create default Warden config.

        Args:
            output_path: Path to save config file

        Returns:
            True if created, False otherwise
        """
        default_config = """# Warden Configuration
version: "1.0"
name: "Warden Analysis"

# Validation frames to run
frames:
  - security
  - fuzz
  - property

# Pipeline settings
settings:
  fail_fast: true
  parallel: false
  timeout: 300

  # Enhanced pipeline features
  enable_discovery: true
  enable_build_context: true
  enable_suppression: true
  enable_issue_validation: true

# Infrastructure configuration
infrastructure:
  ci_provider: "github"  # github, gitlab, azure
  hooks:
    pre_commit: true
    pre_push: false
  installer:
    auto_update: false
"""

        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(default_config)
            return True
        except Exception:
            return False

    @staticmethod
    def get_ci_env_info() -> Dict[str, str]:
        """
        Get CI environment information.

        Returns:
            Dictionary of CI environment variables
        """
        env_info = {}

        # Common CI variables
        ci_vars = [
            "CI",
            "GITHUB_ACTIONS",
            "GITLAB_CI",
            "CIRCLECI",
            "TRAVIS",
            "JENKINS_HOME",
            "BUILD_ID",
            "BUILD_NUMBER",
            "BRANCH_NAME",
            "CI_COMMIT_SHA",
            "GITHUB_SHA",
        ]

        for var in ci_vars:
            value = os.getenv(var)
            if value:
                env_info[var] = value

        return env_info

    @staticmethod
    def generate_install_script(
        platform: str = "github",
        version: Optional[str] = None,
    ) -> str:
        """
        Generate installation script for CI platform.

        Args:
            platform: CI platform (github, gitlab, azure)
            version: Warden version to install

        Returns:
            Installation script as string
        """
        warden_install = (
            f"pip install warden-core=={version}"
            if version
            else "pip install warden-core"
        )

        if platform == "github":
            return f"""# GitHub Actions Warden Installation
- name: Install Warden
  run: |
    python -m pip install --upgrade pip
    {warden_install}
    warden --version
"""

        elif platform == "gitlab":
            return f"""# GitLab CI Warden Installation
before_script:
  - python -m pip install --upgrade pip
  - {warden_install}
  - warden --version
"""

        elif platform == "azure":
            return f"""# Azure Pipelines Warden Installation
- script: |
    python -m pip install --upgrade pip
    {warden_install}
    warden --version
  displayName: 'Install Warden'
"""

        else:
            return f"""# Generic Warden Installation
python -m pip install --upgrade pip
{warden_install}
warden --version
"""

    @staticmethod
    def check_docker_support() -> bool:
        """
        Check if Docker is available.

        Returns:
            True if Docker is available, False otherwise
        """
        try:
            result = subprocess.run(
                ["docker", "--version"],
                capture_output=True,
                text=True,
                check=False,
            )
            return result.returncode == 0
        except Exception:
            return False

    @staticmethod
    def generate_dockerfile() -> str:
        """
        Generate Dockerfile for Warden.

        Returns:
            Dockerfile content as string
        """
        return """# Warden Docker Image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install Warden
RUN pip install --no-cache-dir warden-core

# Copy project files
COPY . /app

# Run Warden
ENTRYPOINT ["warden"]
CMD ["analyze", "--ci"]
"""
