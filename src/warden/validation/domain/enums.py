"""
Validation domain enums.

Matches C# Warden.Core enum definitions for compatibility.
"""

from enum import IntEnum, Enum


class FramePriority(IntEnum):
    """
    Frame execution priority.

    Matches C# Warden.Core.Validation.FramePriority:
        public enum FramePriority {
            Critical = 1,
            High = 2,
            Medium = 3,
            Low = 4,
            Informational = 5
        }

    Lower values execute first. Critical frames block on failure.
    Panel expects: 'critical' | 'high' | 'medium' | 'low' (string format)
    """

    CRITICAL = 1  # Execute first, block on failure
    HIGH = 2  # Execute early, high importance
    MEDIUM = 3  # Normal priority
    LOW = 4  # Execute later, low priority
    INFORMATIONAL = 5  # Execute last, informational only

    def to_panel_string(self) -> str:
        """
        Convert to Panel-compatible string format.

        Panel expects: 'critical' | 'high' | 'medium' | 'low'
        INFORMATIONAL maps to 'low' as Panel doesn't have informational priority.

        Returns:
            str: Panel-compatible priority string
        """
        mapping = {
            FramePriority.CRITICAL: "critical",
            FramePriority.HIGH: "high",
            FramePriority.MEDIUM: "medium",
            FramePriority.LOW: "low",
            FramePriority.INFORMATIONAL: "low"  # Map to low
        }
        return mapping[self]

    @classmethod
    def from_panel_string(cls, value: str) -> "FramePriority":
        """
        Parse Panel string to FramePriority.

        Args:
            value: Panel priority string ('critical' | 'high' | 'medium' | 'low')

        Returns:
            FramePriority: Corresponding enum value

        Raises:
            ValueError: If value is not a valid priority string
        """
        mapping = {
            "critical": cls.CRITICAL,
            "high": cls.HIGH,
            "medium": cls.MEDIUM,
            "low": cls.LOW
        }
        if value not in mapping:
            raise ValueError(f"Invalid panel priority string: {value}")
        return mapping[value]


class FrameScope(str, Enum):
    """
    Frame execution scope.

    Matches C# Warden.Core.Validation.FrameScope:
        public enum FrameScope {
            FileLevel,
            RepositoryLevel,
            ProjectLevel
        }

    - FILE_LEVEL: Frame executes on individual files
    - REPOSITORY_LEVEL: Frame executes on entire repository (once per run)
    - PROJECT_LEVEL: Frame executes on entire project structure (once per run)
    """

    FILE_LEVEL = "file_level"  # Execute per file
    REPOSITORY_LEVEL = "repository_level"  # Execute once per repository (alias for PROJECT_LEVEL)
    PROJECT_LEVEL = "project_level"  # Execute once per project (architectural analysis)


class FrameCategory(str, Enum):
    """
    Frame category classification.

    Matches Panel TypeScript FrameCategory enum.
    """

    GLOBAL = "global"  # Applies to all code
    LANGUAGE_SPECIFIC = "language-specific"  # Python, JavaScript, etc.
    FRAMEWORK_SPECIFIC = "framework-specific"  # FastAPI, React, Flutter, etc.


class FrameApplicability(str, Enum):
    """
    Language/framework applicability.

    Matches Panel TypeScript FrameApplicability enum.
    """

    ALL = "all"
    CSHARP = "csharp"
    DART = "dart"
    TYPESCRIPT = "typescript"
    JAVASCRIPT = "javascript"
    PYTHON = "python"
    JAVA = "java"
    GO = "go"
    FLUTTER = "flutter"
    REACT = "react"
    ASPNETCORE = "aspnetcore"
    NEXTJS = "nextjs"
