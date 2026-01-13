"""
Discovery domain models.

Core entities for file discovery and classification.
"""

from __future__ import annotations

from pydantic import Field
from enum import Enum
from typing import List, Dict, Any, Optional, Set

from warden.shared.domain.base_model import BaseDomainModel


class FileType(Enum):
    """
    Supported file types for code analysis.

    Panel expects string values for display.
    """

    PYTHON = "python"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    JSX = "jsx"
    TSX = "tsx"
    HTML = "html"
    CSS = "css"
    JSON = "json"
    YAML = "yaml"
    MARKDOWN = "markdown"
    SHELL = "shell"
    SQL = "sql"
    GO = "go"
    RUST = "rust"
    JAVA = "java"
    KOTLIN = "kotlin"
    SWIFT = "swift"
    RUBY = "ruby"
    PHP = "php"
    C = "c"
    CPP = "cpp"
    CSHARP = "csharp"
    UNKNOWN = "unknown"

    @property
    def extension(self) -> str:
        """Get primary file extension for this file type."""
        from warden.shared.utils.language_utils import get_primary_extension
        return get_primary_extension(self.value)

    @property
    def is_analyzable(self) -> bool:
        """Check if this file type can be analyzed by Warden."""
        analyzable_types = {
            FileType.PYTHON,
            FileType.JAVASCRIPT,
            FileType.TYPESCRIPT,
            FileType.JSX,
            FileType.TSX,
            FileType.GO,
            FileType.RUST,
            FileType.JAVA,
            FileType.KOTLIN,
        }
        return self in analyzable_types


class Framework(Enum):
    """
    Detected frameworks in the project.

    Panel expects string values for display.
    """

    # Python frameworks
    DJANGO = "django"
    FLASK = "flask"
    FASTAPI = "fastapi"
    PYRAMID = "pyramid"
    TORNADO = "tornado"

    # JavaScript/TypeScript frameworks
    REACT = "react"
    VUE = "vue"
    ANGULAR = "angular"
    NEXT = "next"
    NUXT = "nuxt"
    SVELTE = "svelte"
    EXPRESS = "express"
    NEST = "nest"

    # Other frameworks
    SPRING = "spring"  # Java
    RAILS = "rails"  # Ruby
    LARAVEL = "laravel"  # PHP

    UNKNOWN = "unknown"


class DiscoveredFile(BaseDomainModel):
    """
    A file discovered during project scanning.

    Represents a single file with its metadata and classification.
    """

    path: str  # Absolute path to the file
    relative_path: str  # Path relative to project root
    file_type: FileType
    size_bytes: int
    is_analyzable: bool  # Can Warden analyze this file?
    metadata: Dict[str, Any] = Field(default_factory=dict)


class FrameworkDetectionResult(BaseDomainModel):
    """
    Result of framework detection for the project.

    Contains all detected frameworks and their confidence scores.
    """

    detected_frameworks: List[Framework] = Field(default_factory=list)
    primary_framework: Optional[Framework] = None
    confidence_scores: Dict[str, float] = Field(default_factory=dict)  # framework -> score
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DiscoveryStats(BaseDomainModel):
    """
    Statistics about the discovery process.

    Aggregates file counts by type and analyzability.
    """

    total_files: int = 0
    analyzable_files: int = 0
    ignored_files: int = 0  # Filtered by .gitignore
    files_by_type: Dict[str, int] = Field(default_factory=dict)  # file_type -> count
    total_size_bytes: int = 0
    scan_duration_seconds: float = 0.0

    @property
    def analyzable_percentage(self) -> float:
        """Calculate percentage of analyzable files."""
        if self.total_files == 0:
            return 0.0
        return (self.analyzable_files / self.total_files) * 100


class DiscoveryResult(BaseDomainModel):
    """
    Complete result of project file discovery.

    Contains all discovered files, detected frameworks, and statistics.
    """

    project_path: str
    files: List[DiscoveredFile] = Field(default_factory=list)
    framework_detection: FrameworkDetectionResult = Field(
        default_factory=FrameworkDetectionResult
    )
    stats: DiscoveryStats = Field(default_factory=DiscoveryStats)
    gitignore_patterns: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def get_analyzable_files(self) -> List[DiscoveredFile]:
        """Get only files that can be analyzed."""
        return [f for f in self.files if f.is_analyzable]

    def get_files_by_type(self, file_type: FileType) -> List[DiscoveredFile]:
        """Get all files of a specific type."""
        return [f for f in self.files if f.file_type == file_type]

    def has_framework(self, framework: Framework) -> bool:
        """Check if a specific framework was detected."""
        return framework in self.framework_detection.detected_frameworks
