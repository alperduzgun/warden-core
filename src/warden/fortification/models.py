"""
Fortification Models

Panel-compatible data models for fortification results.
Python internally uses snake_case, JSON output uses camelCase.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional


class FortificationActionType(Enum):
    """Types of fortification actions."""

    ERROR_HANDLING = "error_handling"
    LOGGING = "logging"
    INPUT_VALIDATION = "input_validation"
    RESOURCE_DISPOSAL = "resource_disposal"
    NULL_CHECK = "null_check"


class FortifierPriority(Enum):
    """Priority levels for fortifiers."""

    CRITICAL = 0
    HIGH = 1
    MEDIUM = 2
    LOW = 3


@dataclass
class FortificationAction:
    """Represents a single fortification action applied to code."""

    type: FortificationActionType
    description: str
    line_number: int
    severity: str = "High"

    def to_json(self) -> dict:
        """Convert to Panel-compatible JSON (camelCase)."""
        return {
            "type": self.type.value,
            "description": self.description,
            "lineNumber": self.line_number,
            "severity": self.severity,
        }

    @classmethod
    def from_json(cls, data: dict) -> "FortificationAction":
        """Parse Panel JSON (camelCase) to Python."""
        return cls(
            type=FortificationActionType(data["type"]),
            description=data["description"],
            line_number=data["lineNumber"],
            severity=data.get("severity", "High"),
        )


@dataclass
class FortificationSuggestion:
    """
    A suggestion for code improvement.

    Warden reports suggestions but NEVER modifies code.
    """

    issue_line: int
    issue_type: str  # e.g., "missing_error_handling"
    description: str  # Human-readable description
    suggestion: str  # LLM-generated suggestion (if available)
    severity: str = "Medium"
    code_snippet: Optional[str] = None  # Relevant code snippet

    def to_json(self) -> dict:
        """Convert to Panel-compatible JSON (camelCase)."""
        return {
            "issueLine": self.issue_line,
            "issueType": self.issue_type,
            "description": self.description,
            "suggestion": self.suggestion,
            "severity": self.severity,
            "codeSnippet": self.code_snippet,
        }

    @classmethod
    def from_json(cls, data: dict) -> "FortificationSuggestion":
        """Parse Panel JSON (camelCase) to Python."""
        return cls(
            issue_line=data["issueLine"],
            issue_type=data["issueType"],
            description=data["description"],
            suggestion=data["suggestion"],
            severity=data.get("severity", "Medium"),
            code_snippet=data.get("codeSnippet"),
        )


@dataclass
class FortificationResult:
    """
    Result of code fortification analysis.

    IMPORTANT: Warden is a REPORTER, not a code modifier.
    - Reports issues and suggestions
    - NEVER modifies source code
    - Developer decides which suggestions to apply
    """

    success: bool
    file_path: str
    issues_found: int
    suggestions: List[FortificationSuggestion] = field(default_factory=list)
    summary: str = ""
    error_message: Optional[str] = None
    fortifier_name: str = ""
    timestamp: datetime = field(default_factory=datetime.now)

    def to_json(self) -> dict:
        """Convert to Panel-compatible JSON (camelCase)."""
        return {
            "success": self.success,
            "filePath": self.file_path,
            "issuesFound": self.issues_found,
            "suggestions": [s.to_json() for s in self.suggestions],
            "summary": self.summary,
            "errorMessage": self.error_message,
            "fortifierName": self.fortifier_name,
            "timestamp": self.timestamp.isoformat(),
        }

    @classmethod
    def from_json(cls, data: dict) -> "FortificationResult":
        """Parse Panel JSON (camelCase) to Python."""
        return cls(
            success=data["success"],
            file_path=data["filePath"],
            issues_found=data["issuesFound"],
            suggestions=[
                FortificationSuggestion.from_json(s) for s in data.get("suggestions", [])
            ],
            summary=data.get("summary", ""),
            error_message=data.get("errorMessage"),
            fortifier_name=data.get("fortifierName", ""),
            timestamp=datetime.fromisoformat(data["timestamp"]),
        )
