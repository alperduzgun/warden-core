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
    """

    CRITICAL = 1  # Execute first, block on failure
    HIGH = 2  # Execute early, high importance
    MEDIUM = 3  # Normal priority
    LOW = 4  # Execute later, low priority
    INFORMATIONAL = 5  # Execute last, informational only


class FrameScope(str, Enum):
    """
    Frame execution scope.

    Matches C# Warden.Core.Validation.FrameScope:
        public enum FrameScope {
            FileLevel,
            RepositoryLevel
        }

    - FileLevel: Frame executes on individual files
    - RepositoryLevel: Frame executes on entire repository (once per run)
    """

    FILE_LEVEL = "file_level"  # Execute per file
    REPOSITORY_LEVEL = "repository_level"  # Execute once per repository


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
    PYTHON = "python"
    JAVA = "java"
    GO = "go"
    FLUTTER = "flutter"
    REACT = "react"
    ASPNETCORE = "aspnetcore"
    NEXTJS = "nextjs"
