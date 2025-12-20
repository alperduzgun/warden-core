"""
Cleanup Models

Panel-compatible data models for cleanup analysis results.
Python internally uses snake_case, JSON output uses camelCase.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional


class CleanupIssueType(Enum):
    """Types of cleanup opportunities."""

    POOR_NAMING = "poor_naming"
    CODE_DUPLICATION = "code_duplication"
    SOLID_VIOLATION = "solid_violation"
    MAGIC_NUMBER = "magic_number"
    LONG_METHOD = "long_method"
    COMPLEX_METHOD = "complex_method"
    MISSING_DOCSTRING = "missing_docstring"
    UNUSED_CODE = "unused_code"
    COMMENTED_CODE = "commented_code"
    DEAD_CODE = "dead_code"


class CleanupIssueSeverity(Enum):
    """Severity levels for cleanup issues."""

    CRITICAL = 0
    HIGH = 1
    MEDIUM = 2
    LOW = 3
    INFO = 4


@dataclass
class CleanupIssue:
    """
    Represents a single cleanup opportunity.

    Warden reports cleanup opportunities but NEVER modifies code.
    """

    issue_type: CleanupIssueType
    description: str
    line_number: int
    severity: CleanupIssueSeverity = CleanupIssueSeverity.MEDIUM
    code_snippet: Optional[str] = None
    column_start: Optional[int] = None
    column_end: Optional[int] = None

    def to_json(self) -> dict:
        """Convert to Panel-compatible JSON (camelCase)."""
        return {
            "issueType": self.issue_type.value,
            "description": self.description,
            "lineNumber": self.line_number,
            "severity": self.severity.value,
            "codeSnippet": self.code_snippet,
            "columnStart": self.column_start,
            "columnEnd": self.column_end,
        }

    @classmethod
    def from_json(cls, data: dict) -> "CleanupIssue":
        """Parse Panel JSON (camelCase) to Python."""
        return cls(
            issue_type=CleanupIssueType(data["issueType"]),
            description=data["description"],
            line_number=data["lineNumber"],
            severity=CleanupIssueSeverity(data.get("severity", 2)),
            code_snippet=data.get("codeSnippet"),
            column_start=data.get("columnStart"),
            column_end=data.get("columnEnd"),
        )


@dataclass
class CleanupSuggestion:
    """
    A suggestion for code cleanup.

    Warden reports suggestions but NEVER modifies code.
    Developer makes final decisions.
    """

    issue: CleanupIssue
    suggestion: str  # LLM-enhanced suggestion
    example_code: Optional[str] = None  # Example of cleaner code (if available)
    rationale: Optional[str] = None  # Why this needs cleanup

    def to_json(self) -> dict:
        """Convert to Panel-compatible JSON (camelCase)."""
        return {
            "issue": self.issue.to_json(),
            "suggestion": self.suggestion,
            "exampleCode": self.example_code,
            "rationale": self.rationale,
        }

    @classmethod
    def from_json(cls, data: dict) -> "CleanupSuggestion":
        """Parse Panel JSON (camelCase) to Python."""
        return cls(
            issue=CleanupIssue.from_json(data["issue"]),
            suggestion=data["suggestion"],
            example_code=data.get("exampleCode"),
            rationale=data.get("rationale"),
        )


@dataclass
class CleanupResult:
    """
    Result of cleanup analysis.

    IMPORTANT: Warden is a REPORTER, not a code modifier.
    - Reports cleanup opportunities and suggestions
    - NEVER modifies source code
    - Developer decides which suggestions to apply
    """

    success: bool
    file_path: str
    issues_found: int
    suggestions: List[CleanupSuggestion] = field(default_factory=list)
    cleanup_score: float = 0.0  # 0-100 cleanup score (100 = no issues)
    summary: str = ""
    error_message: Optional[str] = None
    analyzer_name: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    metrics: dict = field(default_factory=dict)  # Additional metrics

    def to_json(self) -> dict:
        """Convert to Panel-compatible JSON (camelCase)."""
        return {
            "success": self.success,
            "filePath": self.file_path,
            "issuesFound": self.issues_found,
            "suggestions": [s.to_json() for s in self.suggestions],
            "cleanupScore": self.cleanup_score,
            "summary": self.summary,
            "errorMessage": self.error_message,
            "analyzerName": self.analyzer_name,
            "timestamp": self.timestamp.isoformat(),
            "metrics": self.metrics,
        }

    @classmethod
    def from_json(cls, data: dict) -> "CleanupResult":
        """Parse Panel JSON (camelCase) to Python."""
        return cls(
            success=data["success"],
            file_path=data["filePath"],
            issues_found=data["issuesFound"],
            suggestions=[
                CleanupSuggestion.from_json(s) for s in data.get("suggestions", [])
            ],
            cleanup_score=data.get("cleanupScore", 0.0),
            summary=data.get("summary", ""),
            error_message=data.get("errorMessage"),
            analyzer_name=data.get("analyzerName", ""),
            timestamp=datetime.fromisoformat(data["timestamp"]),
            metrics=data.get("metrics", {}),
        )
