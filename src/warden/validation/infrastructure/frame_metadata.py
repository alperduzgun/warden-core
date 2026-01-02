"""
Frame metadata parser and validator.

Validates frame.yaml structure and provides type-safe metadata access.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any, List, Optional
import yaml

from warden.validation.domain.enums import FrameCategory, FramePriority, FrameScope


@dataclass
class FrameMetadata:
    """
    Frame metadata from frame.yaml.

    All custom frames must provide frame.yaml with this structure.
    """

    # Required fields
    name: str
    id: str
    version: str
    author: str
    description: str

    # Frame classification
    category: str = "global"  # Will be validated as FrameCategory
    priority: str = "medium"  # Will be validated as FramePriority
    scope: str = "file_level"  # Will be validated as FrameScope
    is_blocker: bool = False

    # Optional fields
    applicability: List[Dict[str, str]] = field(default_factory=list)
    min_warden_version: Optional[str] = None
    max_warden_version: Optional[str] = None
    config_schema: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)

    # Metadata
    source_path: Optional[Path] = None  # Path to frame directory

    @classmethod
    def from_yaml(cls, yaml_path: Path) -> "FrameMetadata":
        """
        Load and validate frame metadata from YAML file.

        Args:
            yaml_path: Path to frame.yaml

        Returns:
            Validated FrameMetadata instance

        Raises:
            ValueError: If YAML is invalid or required fields missing
            FileNotFoundError: If YAML file not found
        """
        if not yaml_path.exists():
            raise FileNotFoundError(f"Frame metadata not found: {yaml_path}")

        if not yaml_path.is_file():
            raise ValueError(f"Path is not a file: {yaml_path}")

        try:
            with open(yaml_path) as f:
                data = yaml.safe_load(f)

            if not data:
                raise ValueError("Empty YAML file")

            # Validate and create metadata
            metadata = cls._from_dict(data, yaml_path.parent)
            metadata.validate()

            return metadata

        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML in {yaml_path}: {e}") from e

    @classmethod
    def _from_dict(cls, data: Dict[str, Any], source_path: Path) -> "FrameMetadata":
        """Create FrameMetadata from dictionary."""
        return cls(
            name=data.get("name", ""),
            id=data.get("id", ""),
            version=data.get("version", ""),
            author=data.get("author", ""),
            description=data.get("description", ""),
            category=data.get("category", "global"),
            priority=data.get("priority", "medium"),
            scope=data.get("scope", "file_level"),
            is_blocker=data.get("is_blocker", False),
            applicability=data.get("applicability", []),
            min_warden_version=data.get("min_warden_version"),
            max_warden_version=data.get("max_warden_version"),
            config_schema=data.get("config_schema", {}),
            tags=data.get("tags", []),
            source_path=source_path,
        )

    def validate(self) -> None:
        """
        Validate frame metadata.

        Raises:
            ValueError: If validation fails
        """
        errors = []

        # Required fields
        if not self.name:
            errors.append("Missing required field: name")
        if not self.id:
            errors.append("Missing required field: id")
        if not self.version:
            errors.append("Missing required field: version")
        if not self.author:
            errors.append("Missing required field: author")
        if not self.description:
            errors.append("Missing required field: description")

        # Validate category
        valid_categories = [cat.value for cat in FrameCategory]
        if self.category not in valid_categories:
            errors.append(
                f"Invalid category: {self.category}. "
                f"Must be one of: {', '.join(str(c) for c in valid_categories)}"
            )

        # Validate priority (FramePriority uses int values, but YAML uses string names)
        valid_priority_names = [pri.name.lower() for pri in FramePriority]
        if self.priority.lower() not in valid_priority_names:
            errors.append(
                f"Invalid priority: {self.priority}. "
                f"Must be one of: {', '.join(valid_priority_names)}"
            )

        # Validate scope
        valid_scopes = [scope.value for scope in FrameScope]
        if self.scope not in valid_scopes:
            errors.append(
                f"Invalid scope: {self.scope}. "
                f"Must be one of: {', '.join(str(s) for s in valid_scopes)}"
            )

        # Validate ID format (kebab-case)
        if self.id:
            if not self.id.replace("-", "").replace("_", "").isalnum():
                errors.append(
                    f"Invalid ID format: {self.id}. Use kebab-case (e.g., redis-security)"
                )

        # Validate version format (semver)
        if self.version:
            parts = self.version.split(".")
            if len(parts) != 3 or not all(p.isdigit() for p in parts):
                errors.append(
                    f"Invalid version format: {self.version}. Use semantic versioning (e.g., 1.0.0)"
                )

        # Validate applicability structure
        if self.applicability:
            for i, app in enumerate(self.applicability):
                if not isinstance(app, dict):
                    errors.append(
                        f"Invalid applicability[{i}]: Must be a dictionary with 'language' or 'framework' field"
                    )
                    continue

                if "language" not in app and "framework" not in app:
                    errors.append(
                        f"Invalid applicability[{i}]: Must have 'language' or 'framework' field"
                    )

        # Validate tags (should be list of strings)
        if self.tags:
            if not isinstance(self.tags, list):
                errors.append(f"Invalid tags: Must be a list of strings")
            else:
                for i, tag in enumerate(self.tags):
                    if not isinstance(tag, str):
                        errors.append(f"Invalid tags[{i}]: Must be a string, got {type(tag).__name__}")

        if errors:
            raise ValueError(
                f"Frame metadata validation failed:\n  - " + "\n  - ".join(errors)
            )

    def get_category_enum(self) -> FrameCategory:
        """Get category as enum."""
        return FrameCategory(self.category)

    def get_priority_enum(self) -> FramePriority:
        """Get priority as enum."""
        return FramePriority(self.priority)

    def get_scope_enum(self) -> FrameScope:
        """Get scope as enum."""
        return FrameScope(self.scope)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary (for JSON serialization)."""
        return {
            "name": self.name,
            "id": self.id,
            "version": self.version,
            "author": self.author,
            "description": self.description,
            "category": self.category,
            "priority": self.priority,
            "scope": self.scope,
            "is_blocker": self.is_blocker,
            "applicability": self.applicability,
            "min_warden_version": self.min_warden_version,
            "max_warden_version": self.max_warden_version,
            "config_schema": self.config_schema,
            "tags": self.tags,
            "source": "community" if self.source_path else "built-in",
        }

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"FrameMetadata("
            f"id={self.id}, "
            f"name={self.name}, "
            f"version={self.version}, "
            f"category={self.category}, "
            f"priority={self.priority})"
        )


class FrameMetadataError(Exception):
    """Raised when frame metadata is invalid."""

    pass
