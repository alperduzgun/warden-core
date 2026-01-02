"""
Repository Pattern interfaces for domain persistence.

All repository implementations should follow these contracts.
Follows the pattern established by ISecretProvider and ILlmClient.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Generic, List, Optional, TypeVar

if TYPE_CHECKING:
    from typing import Any, Dict

    from warden.issues.domain.enums import IssueSeverity, IssueState
    from warden.issues.domain.models import StateTransition, WardenIssue


T = TypeVar("T")
ID = TypeVar("ID")


class IRepository(ABC, Generic[T, ID]):
    """
    Generic repository interface for CRUD operations.

    Type Parameters:
        T: Entity type (e.g., WardenIssue)
        ID: Identifier type (e.g., str for issue IDs)
    """

    @abstractmethod
    async def get(self, id: ID) -> Optional[T]:
        """Get entity by ID."""
        ...

    @abstractmethod
    async def get_all(self) -> List[T]:
        """Get all entities."""
        ...

    @abstractmethod
    async def save(self, entity: T) -> T:
        """Save or update entity."""
        ...

    @abstractmethod
    async def delete(self, id: ID) -> bool:
        """Delete entity by ID. Returns True if deleted."""
        ...

    @abstractmethod
    async def exists(self, id: ID) -> bool:
        """Check if entity exists."""
        ...

    @abstractmethod
    async def count(self) -> int:
        """Get total entity count."""
        ...


class IIssueRepository(ABC):
    """
    Repository interface for WardenIssue entities.

    Extends base repository with issue-specific queries.
    """

    @abstractmethod
    async def get(self, id: str) -> Optional["WardenIssue"]:
        """Get issue by ID."""
        ...

    @abstractmethod
    async def get_all(self) -> List["WardenIssue"]:
        """Get all issues."""
        ...

    @abstractmethod
    async def save(self, entity: "WardenIssue") -> "WardenIssue":
        """Save or update issue."""
        ...

    @abstractmethod
    async def delete(self, id: str) -> bool:
        """Delete issue by ID."""
        ...

    @abstractmethod
    async def exists(self, id: str) -> bool:
        """Check if issue exists."""
        ...

    @abstractmethod
    async def count(self) -> int:
        """Get total issue count."""
        ...

    @abstractmethod
    async def get_by_state(self, state: "IssueState") -> List["WardenIssue"]:
        """Get all issues by state (OPEN, RESOLVED, SUPPRESSED)."""
        ...

    @abstractmethod
    async def get_by_severity(self, severity: "IssueSeverity") -> List["WardenIssue"]:
        """Get all issues by severity."""
        ...

    @abstractmethod
    async def get_by_file_path(self, file_path: str) -> List["WardenIssue"]:
        """Get all issues for a specific file."""
        ...

    @abstractmethod
    async def get_history(self, issue_id: str) -> List["StateTransition"]:
        """Get state transition history for an issue."""
        ...

    @abstractmethod
    async def save_all(self, issues: List["WardenIssue"]) -> List["WardenIssue"]:
        """Batch save multiple issues."""
        ...


class ISuppressionRepository(ABC):
    """
    Repository interface for suppression entries.

    Manages issue suppression rules.
    """

    @abstractmethod
    async def get(self, id: str) -> Optional["Dict[str, Any]"]:
        """Get suppression by ID."""
        ...

    @abstractmethod
    async def get_all(self) -> List["Dict[str, Any]"]:
        """Get all suppressions."""
        ...

    @abstractmethod
    async def save(self, entity: "Dict[str, Any]") -> "Dict[str, Any]":
        """Save or update suppression."""
        ...

    @abstractmethod
    async def delete(self, id: str) -> bool:
        """Delete suppression by ID."""
        ...

    @abstractmethod
    async def exists(self, id: str) -> bool:
        """Check if suppression exists."""
        ...

    @abstractmethod
    async def count(self) -> int:
        """Get total suppression count."""
        ...

    @abstractmethod
    async def get_enabled(self) -> List["Dict[str, Any]"]:
        """Get all enabled suppressions."""
        ...

    @abstractmethod
    async def get_for_file(self, file_path: str) -> List["Dict[str, Any]"]:
        """Get suppressions applicable to a file path."""
        ...

    @abstractmethod
    async def get_for_rule(self, rule_id: str) -> List["Dict[str, Any]"]:
        """Get suppressions for a specific rule."""
        ...


class IIssueHistoryRepository(ABC):
    """
    Repository interface for issue history/audit trail.

    Separate from IIssueRepository for clean separation of concerns.
    """

    @abstractmethod
    async def add_event(self, issue_id: str, event: "Dict[str, Any]") -> None:
        """Add an event to issue history."""
        ...

    @abstractmethod
    async def get_events(
        self, issue_id: str, limit: int = 100
    ) -> List["Dict[str, Any]"]:
        """Get events for an issue."""
        ...

    @abstractmethod
    async def get_all_events(self, limit: int = 1000) -> List["Dict[str, Any]"]:
        """Get all events across all issues."""
        ...
