"""
Discovery domain models.

Core entities for file discovery and classification.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field

from warden.ast.domain.enums import CodeLanguage
from warden.shared.domain.base_model import BaseDomainModel


class FileType(str, Enum):
    """
    Supported file types for code analysis.
    Delegates to LanguageRegistry for metadata to remain DRY.
    """

    # Import members from CodeLanguage to maintain compatibility
    PYTHON = CodeLanguage.PYTHON.value
    JAVASCRIPT = CodeLanguage.JAVASCRIPT.value
    TYPESCRIPT = CodeLanguage.TYPESCRIPT.value
    JSX = CodeLanguage.JAVASCRIPT.value  # Alias
    TSX = CodeLanguage.TSX.value
    HTML = CodeLanguage.HTML.value
    CSS = CodeLanguage.CSS.value
    JSON = CodeLanguage.JSON.value
    YAML = CodeLanguage.YAML.value
    MARKDOWN = CodeLanguage.MARKDOWN.value
    SHELL = CodeLanguage.SHELL.value
    SQL = CodeLanguage.SQL.value
    GO = CodeLanguage.GO.value
    RUST = CodeLanguage.RUST.value
    JAVA = CodeLanguage.JAVA.value
    KOTLIN = CodeLanguage.KOTLIN.value
    SWIFT = CodeLanguage.SWIFT.value
    RUBY = CodeLanguage.RUBY.value
    PHP = CodeLanguage.PHP.value
    C = CodeLanguage.C.value
    CPP = CodeLanguage.CPP.value
    CSHARP = CodeLanguage.CSHARP.value
    UNKNOWN = CodeLanguage.UNKNOWN.value

    @property
    def extension(self) -> str:
        """Get primary file extension for this file type."""
        from warden.shared.languages.registry import LanguageRegistry

        return LanguageRegistry.get_primary_extension(CodeLanguage(self.value))

    @property
    def is_analyzable(self) -> bool:
        """Check if this file type can be analyzed by Warden."""
        from warden.shared.languages.registry import LanguageRegistry

        defn = LanguageRegistry.get_definition(CodeLanguage(self.value))
        return defn.is_analyzable if defn else False


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
    hash: str | None = None
    line_count: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class FrameworkDetectionResult(BaseDomainModel):
    """
    Result of framework detection for the project.

    Contains all detected frameworks and their confidence scores.
    """

    detected_frameworks: list[Framework] = Field(default_factory=list)
    primary_framework: Framework | None = None
    confidence_scores: dict[str, float] = Field(default_factory=dict)  # framework -> score
    metadata: dict[str, Any] = Field(default_factory=dict)


class DiscoveryStats(BaseDomainModel):
    """
    Statistics about the discovery process.

    Aggregates file counts by type and analyzability.
    """

    total_files: int = 0
    analyzable_files: int = 0
    ignored_files: int = 0  # Filtered by .gitignore
    files_by_type: dict[str, int] = Field(default_factory=dict)  # file_type -> count
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
    files: list[DiscoveredFile] = Field(default_factory=list)
    framework_detection: FrameworkDetectionResult = Field(default_factory=FrameworkDetectionResult)
    stats: DiscoveryStats = Field(default_factory=DiscoveryStats)
    gitignore_patterns: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def get_analyzable_files(self) -> list[DiscoveredFile]:
        """Get only files that can be analyzed."""
        return [f for f in self.files if f.is_analyzable]

    def get_files_by_type(self, file_type: FileType) -> list[DiscoveredFile]:
        """Get all files of a specific type."""
        return [f for f in self.files if f.file_type == file_type]

    def has_framework(self, framework: Framework) -> bool:
        """Check if a specific framework was detected."""
        return framework in self.framework_detection.detected_frameworks
