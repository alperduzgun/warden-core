"""
Fortification domain models.

Panel Type Reference:
/Users/alper/Documents/Development/warden-panel/src/lib/types/pipeline.ts

export interface Fortification {
    id: string;
    title: string;
    detail: string;
}

NOTE: Warden is a Read-Only tool. The fortification phase provides security remediation
guidance and code suggestions, acting as an AI Tech Lead. It NEVER modifies source
code directly.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import Field

from warden.shared.domain.base_model import BaseDomainModel


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

class Fortification(BaseDomainModel):
    """
    A fortification/remediation suggestion.
    Represents a defensive code improvement recommended by the AI Tech Lead.
    """
    id: str  # Unique ID for the fortification itself
    finding_id: str | None = None  # ID of the finding this fixes
    title: str
    detail: str  # Can contain HTML for Panel rendering
    suggested_code: str | None = None
    original_code: str | None = None
    file_path: str | None = None
    line_number: int | None = None
    confidence: float = 0.0
    severity: str = "medium"
    auto_fixable: bool = False

class FortificationAction(BaseDomainModel):
    """Represents a single fortification action applied to code."""
    type: FortificationActionType
    description: str
    line_number: int
    severity: str = "High"

class FortificationSuggestion(BaseDomainModel):
    """Internal representation of a fortification suggestion."""
    issue_line: int
    issue_type: str
    description: str
    suggestion: str
    severity: str = "Medium"
    code_snippet: str | None = None


class FortificationResult(BaseDomainModel):
    """
    Result of fortification step execution.
    """
    success: bool = True
    fortifications: list[Fortification] = Field(default_factory=list)
    suggestions: list[Fortification] = Field(default_factory=list)
    actions: list[FortificationAction] = Field(default_factory=list)
    files_modified: list[str] = Field(default_factory=list)
    summary: str = ""
    duration: float = 0.0
    timestamp: datetime = Field(default_factory=datetime.now)

    def to_json(self) -> dict[str, Any]:
        """Serialize to Panel-compatible JSON."""
        return {
            "success": self.success,
            "fortifications": [f.to_json() for f in self.fortifications],
            "suggestions": [s.to_json() for s in self.suggestions],
            "actions": [a.to_json() for a in self.actions],
            "filesModified": self.files_modified,
            "summary": self.summary,
            "duration": f"{self.duration:.1f}s",
            "timestamp": self.timestamp.isoformat()
        }

