"""Project configuration model and TOML serialization."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomli as tomllib
    except ImportError:
        raise ImportError("tomli is required for Python < 3.11")

# For writing TOML, we'll use a simple string formatter
# or add toml as dependency


@dataclass
class ProjectConfig:
    """Project-specific configuration stored in .warden/project.toml."""

    name: str
    """Project name (from directory name or pyproject.toml)."""

    language: str
    """Primary programming language (python, java, csharp, etc.)."""

    sdk_version: str | None = None
    """SDK/runtime version (e.g., '3.13', '17', '8.0')."""

    framework: str | None = None
    """Detected framework (e.g., 'django', 'spring-boot', 'aspnet')."""

    project_type: str = "application"
    """Project type: 'application', 'library', 'microservice', 'monorepo'."""

    detected_at: datetime = field(default_factory=datetime.now)
    """When this configuration was first created."""

    custom_settings: dict[str, Any] = field(default_factory=dict)
    """Custom user settings."""

    def to_toml(self) -> str:
        """Serialize to TOML format."""
        # Manual TOML serialization (simple and no dependencies)
        lines = ["[project]"]
        lines.append(f'name = "{self.name}"')
        lines.append(f'language = "{self.language}"')

        if self.sdk_version:
            lines.append(f'sdk_version = "{self.sdk_version}"')
        else:
            lines.append('# sdk_version = ""')

        if self.framework:
            lines.append(f'framework = "{self.framework}"')
        else:
            lines.append('# framework = ""')

        lines.append(f'project_type = "{self.project_type}"')
        lines.append(f'detected_at = "{self.detected_at.isoformat()}"')

        if self.custom_settings:
            lines.append("\n[custom]")
            for key, value in self.custom_settings.items():
                if isinstance(value, str):
                    lines.append(f'{key} = "{value}"')
                else:
                    lines.append(f'{key} = {value}')

        return "\n".join(lines) + "\n"

    @classmethod
    def from_toml(cls, toml_content: str) -> ProjectConfig:
        """Deserialize from TOML format."""
        data = tomllib.loads(toml_content)
        project_data = data.get("project", {})

        return cls(
            name=project_data["name"],
            language=project_data["language"],
            sdk_version=project_data.get("sdk_version"),
            framework=project_data.get("framework"),
            project_type=project_data.get("project_type", "application"),
            detected_at=datetime.fromisoformat(project_data["detected_at"]),
            custom_settings=data.get("custom", {}),
        )

    @classmethod
    def from_file(cls, config_path: Path) -> ProjectConfig:
        """Load configuration from .warden/project.toml file."""
        if not config_path.exists():
            msg = f"Project config not found: {config_path}"
            raise FileNotFoundError(msg)

        return cls.from_toml(config_path.read_text())

    def save(self, config_path: Path) -> None:
        """Save configuration to .warden/project.toml file."""
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(self.to_toml())

    def validate(self) -> list[str]:
        """Validate configuration and return list of issues."""
        issues = []

        if not self.name or not self.name.strip():
            issues.append("Project name is required")

        if not self.language or not self.language.strip():
            issues.append("Project language is required")

        valid_languages = {
            "python",
            "java",
            "csharp",
            "javascript",
            "typescript",
            "go",
            "rust",
            "cpp",
            "c",
            "ruby",
            "php",
            "swift",
            "kotlin",
        }
        if self.language.lower() not in valid_languages:
            issues.append(
                f"Unsupported language '{self.language}'. "
                f"Supported: {', '.join(sorted(valid_languages))}"
            )

        valid_project_types = {"application", "library", "microservice", "monorepo"}
        if self.project_type not in valid_project_types:
            issues.append(
                f"Invalid project type '{self.project_type}'. "
                f"Valid types: {', '.join(sorted(valid_project_types))}"
            )

        return issues
