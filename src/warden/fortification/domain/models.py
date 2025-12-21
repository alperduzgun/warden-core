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

from dataclasses import dataclass, field
from typing import List, Dict, Any

from warden.shared.domain.base_model import BaseDomainModel


@dataclass
class Fortification(BaseDomainModel):
    """
    A single fortification suggestion.

    Represents a defensive code improvement that should be applied.
    Panel displays this with HTML support in detail field (e.g., <code> tags).

    Attributes:
        id: Unique identifier for this fortification
        title: Short summary of the fortification
        detail: Detailed explanation, may contain HTML (e.g., <code> tags)
    """

    id: str
    title: str
    detail: str  # Can contain HTML for Panel rendering


@dataclass
class FortificationResult(BaseDomainModel):
    """
    Result of fortification step execution.

    Aggregates all fortifications found and metadata about the fortification process.

    Attributes:
        fortifications: List of fortification suggestions
        files_modified: List of file paths that would be modified (placeholder)
        duration: Duration of fortification analysis in seconds
    """

    fortifications: List[Fortification] = field(default_factory=list)
    files_modified: List[str] = field(default_factory=list)
    duration: float = 0.0

    def to_json(self) -> Dict[str, Any]:
        """
        Serialize to Panel-compatible JSON.

        Panel expects:
        {
            "fortifications": [{id, title, detail}],
            "filesModified": ["path/to/file.py"],
            "duration": "1.2s"
        }

        Returns:
            Dictionary with camelCase keys for Panel
        """
        return {
            "fortifications": [f.to_json() for f in self.fortifications],
            "filesModified": self.files_modified,
            "duration": f"{self.duration:.1f}s"  # Format as string with unit
        }
