"""Project detection service for auto-detecting language, SDK, and framework."""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomli as tomllib
    except ImportError:
        raise ImportError("tomli is required for Python < 3.11")

from warden.analysis.application.discovery.framework_detector import FrameworkDetector
from warden.analysis.application.discovery.models import FileType


class ProjectDetector:
    """Detects project metadata (language, SDK version, framework)."""

    # Language file extension mapping
    LANGUAGE_EXTENSIONS = {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".jsx": "javascript",
        ".tsx": "typescript",
        ".java": "java",
        ".kt": "kotlin",
        ".cs": "csharp",
        ".go": "go",
        ".rs": "rust",
        ".rb": "ruby",
        ".php": "php",
        ".swift": "swift",
        ".cpp": "cpp",
        ".cc": "cpp",
        ".cxx": "cpp",
        ".c": "c",
    }

    def __init__(self, project_root: Path) -> None:
        """Initialize project detector.

        Args:
            project_root: Root directory of the project to analyze.
        """
        self.project_root = project_root

    async def detect_language(self) -> str:
        """Detect primary programming language by counting file extensions.

        Returns:
            Primary language name (e.g., 'python', 'java', 'javascript').
        """
        # Count source files by extension
        file_counts: Counter[str] = Counter()

        # Search common source directories first
        search_paths = [
            self.project_root / "src",
            self.project_root / "lib",
            self.project_root / "app",
            self.project_root,  # Fallback to root
        ]

        for search_path in search_paths:
            if not search_path.exists():
                continue

            for ext, lang in self.LANGUAGE_EXTENSIONS.items():
                files = list(search_path.rglob(f"*{ext}"))
                # Filter out test files, node_modules, venv, etc.
                files = [
                    f
                    for f in files
                    if not any(
                        part in f.parts
                        for part in [
                            "node_modules",
                            "venv",
                            ".venv",
                            "env",
                            ".env",
                            "dist",
                            "build",
                            "__pycache__",
                            ".git",
                            "vendor",
                            "target",
                            "cli",  # Ignore TypeScript CLI folder
                            "frontend",  # Also ignore frontend folders
                            "client",  # Common client-side folder
                        ]
                    )
                ]
                file_counts[lang] += len(files)

        if not file_counts:
            return "unknown"

        # Return most common language
        most_common_lang, _ = file_counts.most_common(1)[0]
        return most_common_lang

    async def detect_sdk_version(self, language: str) -> str | None:
        """Detect SDK/runtime version for the given language.

        Args:
            language: Programming language to detect version for.

        Returns:
            SDK version string or None if not detected.
        """
        detectors = {
            "python": self._detect_python_version,
            "java": self._detect_java_version,
            "javascript": self._detect_node_version,
            "typescript": self._detect_node_version,
            "csharp": self._detect_dotnet_version,
            "go": self._detect_go_version,
            "rust": self._detect_rust_version,
            "ruby": self._detect_ruby_version,
        }

        detector = detectors.get(language)
        if detector:
            return await detector()

        return None

    async def _detect_python_version(self) -> str | None:
        """Detect Python version from pyproject.toml or .python-version."""
        # Check pyproject.toml
        pyproject_path = self.project_root / "pyproject.toml"
        if pyproject_path.exists():
            try:
                data = tomllib.loads(pyproject_path.read_text())

                # Poetry format
                if "tool" in data and "poetry" in data["tool"]:
                    python_req = data["tool"]["poetry"].get("dependencies", {}).get(
                        "python"
                    )
                    if python_req:
                        # Extract version like "^3.13" -> "3.13"
                        match = re.search(r"(\d+\.\d+)", python_req)
                        if match:
                            return match.group(1)

                # PEP 621 format
                if "project" in data:
                    requires_python = data["project"].get("requires-python")
                    if requires_python:
                        # Extract version like ">=3.13" -> "3.13"
                        match = re.search(r"(\d+\.\d+)", requires_python)
                        if match:
                            return match.group(1)
            except (Exception, KeyError):
                pass

        # Check .python-version (pyenv)
        python_version_path = self.project_root / ".python-version"
        if python_version_path.exists():
            try:
                version = python_version_path.read_text().strip()
                # Extract major.minor from version like "3.13.1"
                match = re.search(r"(\d+\.\d+)", version)
                if match:
                    return match.group(1)
            except (OSError, UnicodeDecodeError):
                pass

        return None

    async def _detect_java_version(self) -> str | None:
        """Detect Java version from pom.xml or build.gradle."""
        # Check pom.xml (Maven)
        pom_path = self.project_root / "pom.xml"
        if pom_path.exists():
            try:
                content = pom_path.read_text()
                # Look for <maven.compiler.source>17</maven.compiler.source>
                match = re.search(
                    r"<maven\.compiler\.(?:source|target)>(\d+)", content
                )
                if match:
                    return match.group(1)
            except (OSError, UnicodeDecodeError):
                pass

        # Check build.gradle or build.gradle.kts (Gradle)
        for gradle_file in ["build.gradle", "build.gradle.kts"]:
            gradle_path = self.project_root / gradle_file
            if gradle_path.exists():
                try:
                    content = gradle_path.read_text()
                    # Look for sourceCompatibility = '17'
                    match = re.search(r"sourceCompatibility\s*=\s*['\"]?(\d+)", content)
                    if match:
                        return match.group(1)
                except (OSError, UnicodeDecodeError):
                    pass

        return None

    async def _detect_node_version(self) -> str | None:
        """Detect Node.js version from package.json or .nvmrc."""
        # Check package.json
        package_json_path = self.project_root / "package.json"
        if package_json_path.exists():
            try:
                data = json.loads(package_json_path.read_text())
                engines = data.get("engines", {})
                node_version = engines.get("node")
                if node_version:
                    # Extract version like ">=18.0.0" -> "18"
                    match = re.search(r"(\d+)", node_version)
                    if match:
                        return match.group(1)
            except (json.JSONDecodeError, OSError, UnicodeDecodeError):
                pass

        # Check .nvmrc
        nvmrc_path = self.project_root / ".nvmrc"
        if nvmrc_path.exists():
            try:
                version = nvmrc_path.read_text().strip()
                # Extract version like "v18.19.0" -> "18"
                match = re.search(r"(\d+)", version)
                if match:
                    return match.group(1)
            except (OSError, UnicodeDecodeError):
                pass

        return None

    async def _detect_dotnet_version(self) -> str | None:
        """Detect .NET version from .csproj or global.json."""
        # Check *.csproj files
        csproj_files = list(self.project_root.glob("*.csproj"))
        if csproj_files:
            try:
                content = csproj_files[0].read_text()
                # Look for <TargetFramework>net8.0</TargetFramework>
                match = re.search(r"<TargetFramework>net(\d+\.\d+)", content)
                if match:
                    return match.group(1)
            except (OSError, UnicodeDecodeError):
                pass

        # Check global.json
        global_json_path = self.project_root / "global.json"
        if global_json_path.exists():
            try:
                data = json.loads(global_json_path.read_text())
                sdk_version = data.get("sdk", {}).get("version")
                if sdk_version:
                    # Extract major.minor from version like "8.0.100"
                    match = re.search(r"(\d+\.\d+)", sdk_version)
                    if match:
                        return match.group(1)
            except (json.JSONDecodeError, OSError, UnicodeDecodeError):
                pass

        return None

    async def _detect_go_version(self) -> str | None:
        """Detect Go version from go.mod."""
        go_mod_path = self.project_root / "go.mod"
        if go_mod_path.exists():
            try:
                content = go_mod_path.read_text()
                # Look for "go 1.21"
                match = re.search(r"^go\s+(\d+\.\d+)", content, re.MULTILINE)
                if match:
                    return match.group(1)
            except (OSError, UnicodeDecodeError):
                pass

        return None

    async def _detect_rust_version(self) -> str | None:
        """Detect Rust version from rust-toolchain or Cargo.toml."""
        # Check rust-toolchain.toml
        rust_toolchain_path = self.project_root / "rust-toolchain.toml"
        if rust_toolchain_path.exists():
            try:
                data = tomllib.loads(rust_toolchain_path.read_text())
                channel = data.get("toolchain", {}).get("channel")
                if channel and channel != "stable":
                    return channel
            except (Exception, OSError, UnicodeDecodeError):
                pass

        # Check rust-toolchain (plain text)
        rust_toolchain_txt = self.project_root / "rust-toolchain"
        if rust_toolchain_txt.exists():
            try:
                channel = rust_toolchain_txt.read_text().strip()
                if channel != "stable":
                    return channel
            except (OSError, UnicodeDecodeError):
                pass

        # Default to "stable" if Cargo.toml exists
        if (self.project_root / "Cargo.toml").exists():
            return "stable"

        return None

    async def _detect_ruby_version(self) -> str | None:
        """Detect Ruby version from .ruby-version or Gemfile."""
        # Check .ruby-version
        ruby_version_path = self.project_root / ".ruby-version"
        if ruby_version_path.exists():
            try:
                version = ruby_version_path.read_text().strip()
                # Extract major.minor from version like "3.2.0"
                match = re.search(r"(\d+\.\d+)", version)
                if match:
                    return match.group(1)
            except (OSError, UnicodeDecodeError):
                pass

        # Check Gemfile
        gemfile_path = self.project_root / "Gemfile"
        if gemfile_path.exists():
            try:
                content = gemfile_path.read_text()
                # Look for ruby '3.2.0'
                match = re.search(r"ruby\s+['\"](\d+\.\d+)", content)
                if match:
                    return match.group(1)
            except (OSError, UnicodeDecodeError):
                pass

        return None

    async def detect_framework(self) -> str | None:
        """Detect primary framework using FrameworkDetector.

        Returns:
            Framework name (e.g., 'django', 'spring-boot', 'react') or None.
        """
        detector = FrameworkDetector(self.project_root)
        result = await detector.detect()

        if result.primary_framework:
            # Map Framework enum to string representation
            framework_name = result.primary_framework.value

            # Special handling for Java frameworks
            if framework_name == "spring":
                # Check if Spring Boot
                pom_path = self.project_root / "pom.xml"
                if pom_path.exists():
                    try:
                        content = pom_path.read_text()
                        if "spring-boot" in content.lower():
                            return "spring-boot"
                    except (OSError, UnicodeDecodeError):
                        pass
                return "spring"

            return framework_name

        return None

    async def detect_project_type(self) -> str:
        """Detect project type (application, library, microservice, monorepo).

        Returns:
            Project type classification.
        """
        # Check for monorepo indicators
        if self._is_monorepo():
            return "monorepo"

        # Check for library indicators
        if self._is_library():
            return "library"

        # Check for microservice indicators
        if self._is_microservice():
            return "microservice"

        # Default to application
        return "application"

    def _is_monorepo(self) -> bool:
        """Check if project is a monorepo."""
        # Lerna or Nx workspace
        if (self.project_root / "lerna.json").exists():
            return True
        if (self.project_root / "nx.json").exists():
            return True

        # Yarn/npm workspaces
        package_json = self.project_root / "package.json"
        if package_json.exists():
            try:
                data = json.loads(package_json.read_text())
                if "workspaces" in data:
                    return True
            except (json.JSONDecodeError, OSError, UnicodeDecodeError):
                pass

        # Poetry multi-project
        pyproject = self.project_root / "pyproject.toml"
        if pyproject.exists():
            try:
                data = tomllib.loads(pyproject.read_text())
                if (
                    "tool" in data
                    and "poetry" in data["tool"]
                    and "packages" in data["tool"]["poetry"]
                ):
                    return True
            except (Exception, OSError, UnicodeDecodeError):
                pass

        # Multiple package.json or pyproject.toml in subdirectories
        package_jsons = list(self.project_root.glob("*/package.json"))
        pyprojects = list(self.project_root.glob("*/pyproject.toml"))
        if len(package_jsons) > 1 or len(pyprojects) > 1:
            return True

        return False

    def _is_library(self) -> bool:
        """Check if project is a library."""
        # Python library indicators
        pyproject = self.project_root / "pyproject.toml"
        if pyproject.exists():
            try:
                data = tomllib.loads(pyproject.read_text())
                # Check for project classifiers indicating library
                classifiers = data.get("project", {}).get("classifiers", [])
                if any("Library" in c for c in classifiers):
                    return True
            except (Exception, OSError, UnicodeDecodeError):
                pass

        # JavaScript library indicators
        package_json = self.project_root / "package.json"
        if package_json.exists():
            try:
                data = json.loads(package_json.read_text())
                # Has "main" or "module" but no scripts.start
                has_entry = "main" in data or "module" in data
                no_start = "start" not in data.get("scripts", {})
                if has_entry and no_start:
                    return True
            except (json.JSONDecodeError, OSError, UnicodeDecodeError):
                pass

        # Java library (no main class in pom.xml)
        pom_path = self.project_root / "pom.xml"
        if pom_path.exists():
            try:
                content = pom_path.read_text()
                # If packaging is "jar" but no main class
                is_jar = "<packaging>jar</packaging>" in content
                no_main = "mainClass" not in content
                if is_jar and no_main:
                    return True
            except (OSError, UnicodeDecodeError):
                pass

        return False

    def _is_microservice(self) -> bool:
        """Check if project is a microservice."""
        # Docker indicators
        has_dockerfile = (self.project_root / "Dockerfile").exists()
        has_compose = (
            (self.project_root / "docker-compose.yml").exists()
            or (self.project_root / "docker-compose.yaml").exists()
        )

        # Kubernetes indicators
        has_k8s = (self.project_root / "k8s").exists() or (
            self.project_root / "kubernetes"
        ).exists()

        # Microservice frameworks
        microservice_frameworks = {"fastapi", "express", "nest", "spring-boot"}

        # If has Docker + microservice framework, likely a microservice
        if has_dockerfile and any(
            (self.project_root / f"requirements.txt").exists()
            and fw in (self.project_root / "requirements.txt").read_text().lower()
            for fw in ["fastapi", "flask"]
        ):
            return True

        return bool(has_dockerfile or has_compose or has_k8s)

    def get_project_name(self) -> str:
        """Get project name from configuration files or directory name.

        Returns:
            Project name.
        """
        # Try package.json
        package_json = self.project_root / "package.json"
        if package_json.exists():
            try:
                data = json.loads(package_json.read_text())
                if "name" in data:
                    return data["name"]
            except (json.JSONDecodeError, OSError, UnicodeDecodeError):
                pass

        # Try pyproject.toml
        pyproject = self.project_root / "pyproject.toml"
        if pyproject.exists():
            try:
                data = tomllib.loads(pyproject.read_text())
                if "project" in data and "name" in data["project"]:
                    return data["project"]["name"]
                if "tool" in data and "poetry" in data["tool"]:
                    return data["tool"]["poetry"]["name"]
            except (Exception, OSError, UnicodeDecodeError):
                pass

        # Try Cargo.toml
        cargo = self.project_root / "Cargo.toml"
        if cargo.exists():
            try:
                data = tomllib.loads(cargo.read_text())
                if "package" in data and "name" in data["package"]:
                    return data["package"]["name"]
            except (Exception, OSError, UnicodeDecodeError):
                pass

        # Fallback to directory name
        return self.project_root.name
