"""
Issue domain models.

Panel Source: /warden-panel-development/src/lib/types/warden.ts

TypeScript:
    export interface StateTransition {
        fromState: IssueState;
        toState: IssueState;
        timestamp: Date;
        transitionedBy: string;
        comment: string;
    }

    export interface WardenIssue {
        id: string;
        type: string;
        severity: IssueSeverity;
        filePath: string;
        message: string;
        codeSnippet: string;
        codeHash: string;
        state: IssueState;
        firstDetected: Date;
        lastUpdated: Date;
        reopenCount: number;
        stateHistory: StateTransition[];
    }
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Dict, Any, Type

from warden.shared.domain.base_model import BaseDomainModel
from warden.issues.domain.enums import IssueSeverity, IssueState


class StateTransition(BaseDomainModel):
    """
    State transition record for issue history.

    Tracks who changed the state, when, and why.
    """

    from_state: IssueState
    to_state: IssueState
    timestamp: datetime
    transitioned_by: str  # "system", "user", "ci/cd", etc.
    comment: str

    @classmethod
    def from_json(cls: Type[StateTransition], data: Dict[str, Any]) -> StateTransition:
        """Deserialize from Panel JSON (camelCase)."""
        return cls(
            from_state=IssueState(data["fromState"]),
            to_state=IssueState(data["toState"]),
            timestamp=datetime.fromisoformat(data["timestamp"]),
            transitioned_by=data["transitionedBy"],
            comment=data["comment"],
        )


class WardenIssue(BaseDomainModel):
    """
    Core issue model (matches Panel TypeScript interface).

    Fields are snake_case internally, but serialize to camelCase for Panel.
    """

    id: str  # "W001", "W002", etc.
    type: str  # "Git Changes Analysis", "Security Analysis", etc.
    severity: IssueSeverity
    file_path: str
    message: str
    code_snippet: str
    code_hash: str  # For tracking across scans
    state: IssueState
    first_detected: datetime
    last_updated: datetime
    reopen_count: int
    state_history: List[StateTransition]
    confidence: float = 0.7  # Confidence score (0.0 - 1.0), default: 0.7
    line_number: int = 0  # Line number where issue occurs, default: 0 (extract from file_path)

    def to_json(self) -> Dict[str, Any]:
        """
        Serialize to Panel-compatible JSON (camelCase).

        Override to handle nested StateTransition objects.
        """
        result = super().to_json()

        # Manually handle state_history list
        result["stateHistory"] = [transition.to_json() for transition in self.state_history]

        return result

    @classmethod
    def from_json(cls: Type[WardenIssue], data: Dict[str, Any]) -> WardenIssue:
        """Deserialize from Panel JSON (camelCase)."""
        return cls(
            id=data["id"],
            type=data["type"],
            severity=IssueSeverity(data["severity"]),
            file_path=data["filePath"],
            message=data["message"],
            code_snippet=data["codeSnippet"],
            code_hash=data["codeHash"],
            state=IssueState(data["state"]),
            first_detected=datetime.fromisoformat(data["firstDetected"]),
            last_updated=datetime.fromisoformat(data["lastUpdated"]),
            reopen_count=data["reopenCount"],
            state_history=[
                StateTransition.from_json(t) for t in data.get("stateHistory", [])
            ],
        )

    def is_critical(self) -> bool:
        """Check if issue is critical severity."""
        return self.severity == IssueSeverity.CRITICAL

    def is_high_or_critical(self) -> bool:
        """Check if issue is high or critical severity."""
        return self.severity in (IssueSeverity.CRITICAL, IssueSeverity.HIGH)

    def is_open(self) -> bool:
        """Check if issue is in open state."""
        return self.state == IssueState.OPEN

    def resolve(self, resolved_by: str, comment: str = "") -> None:
        """
        Mark issue as resolved.

        Args:
            resolved_by: Who resolved the issue (user, system, etc.)
            comment: Optional comment about resolution
        """
        if self.state == IssueState.RESOLVED:
            return  # Already resolved

        transition = StateTransition(
            from_state=self.state,
            to_state=IssueState.RESOLVED,
            timestamp=datetime.now(),
            transitioned_by=resolved_by,
            comment=comment or "Issue resolved",
        )

        self.state = IssueState.RESOLVED
        self.last_updated = datetime.now()
        self.state_history.append(transition)

    def suppress(self, suppressed_by: str, comment: str = "") -> None:
        """
        Suppress issue (mark as false positive).

        Args:
            suppressed_by: Who suppressed the issue
            comment: Reason for suppression
        """
        if self.state == IssueState.SUPPRESSED:
            return  # Already suppressed

        transition = StateTransition(
            from_state=self.state,
            to_state=IssueState.SUPPRESSED,
            timestamp=datetime.now(),
            transitioned_by=suppressed_by,
            comment=comment or "Issue suppressed",
        )

        self.state = IssueState.SUPPRESSED
        self.last_updated = datetime.now()
        self.state_history.append(transition)

    def reopen(self, reopened_by: str, comment: str = "") -> None:
        """
        Reopen a resolved or suppressed issue.

        Args:
            reopened_by: Who reopened the issue
            comment: Reason for reopening
        """
        if self.state == IssueState.OPEN:
            return  # Already open

        transition = StateTransition(
            from_state=self.state,
            to_state=IssueState.OPEN,
            timestamp=datetime.now(),
            transitioned_by=reopened_by,
            comment=comment or "Issue reopened",
        )

        self.state = IssueState.OPEN
        self.last_updated = datetime.now()
        self.reopen_count += 1
        self.state_history.append(transition)
