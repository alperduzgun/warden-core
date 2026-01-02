"""
Cleaning domain models.

Panel Type Reference:
/Users/alper/Documents/Development/warden-panel/src/lib/types/pipeline.ts

export interface Cleaning {
    id: string;
    title: string;
    detail: string;
}

NOTE: This is a placeholder implementation for future cleaning features.
The cleaning step will analyze code and suggest cleanup/refactoring improvements.
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any

from pydantic import Field
from warden.shared.domain.base_model import BaseDomainModel

class CleaningIssueType(Enum):
    """Types of cleaning opportunities."""
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
    DESIGN_SMELL = "design_smell"
    MISSING_DOC = "missing_doc"
    TESTABILITY_ISSUE = "testability_issue"
    POOR_DOC = "poor_doc"

class CleaningIssueSeverity(Enum):
    """Severity levels for cleaning issues."""
    CRITICAL = 0
    HIGH = 1
    MEDIUM = 2
    LOW = 3
    INFO = 4

class Cleaning(BaseDomainModel):
    """
    A single cleaning suggestion.
    Represents a code cleanup or refactoring improvement.
    """
    id: str
    title: str
    detail: str  # Can contain HTML for Panel rendering

class CleaningIssue(BaseDomainModel):
    """Represents a single cleanup opportunity."""
    issue_type: CleaningIssueType
    description: str
    line_number: int
    severity: CleaningIssueSeverity = CleaningIssueSeverity.MEDIUM
    code_snippet: Optional[str] = None
    column_start: Optional[int] = None
    column_end: Optional[int] = None

class CleaningSuggestion(BaseDomainModel):
    """A suggestion for code cleanup."""
    issue: CleaningIssue
    suggestion: str
    example_code: Optional[str] = None
    rationale: Optional[str] = None

class CleaningResult(BaseDomainModel):
    """
    Result of cleaning step execution.
    """
    success: bool = True
    cleanings: List[Cleaning] = Field(default_factory=list)
    issues_found: int = 0
    suggestions: List[CleaningSuggestion] = Field(default_factory=list)
    cleanup_score: float = 0.0
    files_modified: List[str] = Field(default_factory=list)
    summary: str = ""
    duration: float = 0.0
    timestamp: datetime = Field(default_factory=datetime.now)
    metrics: dict = Field(default_factory=dict)

    def to_json(self) -> Dict[str, Any]:
        """Serialize to Panel-compatible JSON."""
        return {
            "success": self.success,
            "cleanings": [c.to_json() for c in self.cleanings],
            "issuesFound": self.issues_found,
            "suggestions": [s.to_json() for s in self.suggestions],
            "cleanupScore": self.cleanup_score,
            "filesModified": self.files_modified,
            "summary": self.summary,
            "duration": f"{self.duration:.1f}s",
            "timestamp": self.timestamp.isoformat(),
            "metrics": self.metrics
        }

