"""
Fortification domain models.

Panel Type Reference:
/Users/alper/Documents/Development/warden-panel/src/lib/types/pipeline.ts

export interface Fortification {
    id: string;
    title: string;
    detail: string;
}

NOTE: This is a placeholder implementation for future fortification features.
The fortification step will analyze code and suggest defensive improvements.
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any

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
    A single fortification suggestion.
    Represents a defensive code improvement that should be applied.
    """
    id: str
    title: str
    detail: str  # Can contain HTML for Panel rendering

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
    code_snippet: Optional[str] = None


class FortificationResult(BaseDomainModel):
    """
    Result of fortification step execution.
    """
    success: bool = True
    fortifications: List[Fortification] = Field(default_factory=list)
    suggestions: List[Fortification] = Field(default_factory=list)
    actions: List[FortificationAction] = Field(default_factory=list)
    files_modified: List[str] = Field(default_factory=list)
    summary: str = ""
    duration: float = 0.0
    timestamp: datetime = Field(default_factory=datetime.now)

    def to_json(self) -> Dict[str, Any]:
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

