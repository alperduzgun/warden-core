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

from dataclasses import dataclass, field
from typing import List, Dict, Any

from warden.shared.domain.base_model import BaseDomainModel


@dataclass
class Cleaning(BaseDomainModel):
    """
    A single cleaning suggestion.

    Represents a code cleanup or refactoring improvement.
    Panel displays this with HTML support in detail field (e.g., <code> tags).

    Attributes:
        id: Unique identifier for this cleaning
        title: Short summary of the cleaning
        detail: Detailed explanation, may contain HTML (e.g., <code> tags)
    """

    id: str
    title: str
    detail: str  # Can contain HTML for Panel rendering


@dataclass
class CleaningResult(BaseDomainModel):
    """
    Result of cleaning step execution.

    Aggregates all cleaning suggestions found and metadata about the cleaning process.

    Attributes:
        cleanings: List of cleaning suggestions
        files_modified: List of file paths that would be modified (placeholder)
        duration: Duration of cleaning analysis in seconds
    """

    cleanings: List[Cleaning] = field(default_factory=list)
    files_modified: List[str] = field(default_factory=list)
    duration: float = 0.0

    def to_json(self) -> Dict[str, Any]:
        """
        Serialize to Panel-compatible JSON.

        Panel expects:
        {
            "cleanings": [{id, title, detail}],
            "filesModified": ["path/to/file.py"],
            "duration": "0.8s"
        }

        Returns:
            Dictionary with camelCase keys for Panel
        """
        return {
            "cleanings": [c.to_json() for c in self.cleanings],
            "filesModified": self.files_modified,
            "duration": f"{self.duration:.1f}s"  # Format as string with unit
        }
