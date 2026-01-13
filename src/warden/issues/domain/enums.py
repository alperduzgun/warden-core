"""
Issue domain enums.

CRITICAL: Enum values MUST match Panel TypeScript definitions exactly!
Panel Source: /warden-panel-development/src/lib/types/warden.ts
"""

from enum import Enum


class IssueSeverity(Enum):
    """
    Issue severity levels (matches Panel TypeScript enum).

    Panel: export enum IssueSeverity {
        Critical = 0,
        High = 1,
        Medium = 2,
        Low = 3
    }
    """

    CRITICAL = 0
    HIGH = 1
    MEDIUM = 2
    LOW = 3

    @property
    def label(self) -> str:
        """Get human-readable label."""
        labels = {
            IssueSeverity.CRITICAL: "Critical",
            IssueSeverity.HIGH: "High",
            IssueSeverity.MEDIUM: "Medium",
            IssueSeverity.LOW: "Low",
        }
        return labels[self]

    @property
    def color(self) -> str:
        """Get Tailwind CSS color class (matches Panel)."""
        colors = {
            IssueSeverity.CRITICAL: "text-destructive",
            IssueSeverity.HIGH: "text-orange-500",
            IssueSeverity.MEDIUM: "text-yellow-500",
            IssueSeverity.LOW: "text-blue-500",
        }
        return colors[self]


class IssueState(Enum):
    """
    Issue state tracking (matches Panel TypeScript enum).

    Panel: export enum IssueState {
        Open = 0,
        Resolved = 1,
        Suppressed = 2
    }
    """

    OPEN = 0
    RESOLVED = 1
    SUPPRESSED = 2

    @property
    def label(self) -> str:
        """Get human-readable label."""
        labels = {
            IssueState.OPEN: "Open",
            IssueState.RESOLVED: "Resolved",
            IssueState.SUPPRESSED: "Suppressed",
        }
        return labels[self]
