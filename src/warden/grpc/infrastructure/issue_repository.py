"""
File-based implementation of IIssueRepository.

Stores issues in .warden/grpc/issues.json
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

from warden.grpc.infrastructure.base_file_repository import BaseFileRepository
from warden.issues.domain.enums import IssueSeverity, IssueState
from warden.issues.domain.models import StateTransition, WardenIssue
from warden.shared.domain.repository import IIssueRepository

if TYPE_CHECKING:
    pass

# Optional: structured logging
try:
    from warden.shared.infrastructure.logging import get_logger

    logger = get_logger(__name__)
except ImportError:
    import logging

    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

DEFAULT_STORAGE_PATH = ".warden/grpc/issues.json"


class FileIssueRepository(BaseFileRepository[WardenIssue], IIssueRepository):
    """
    File-based issue repository implementation.

    Storage format:
    {
        "version": "1.0",
        "created_at": "2025-12-26T...",
        "updated_at": "2025-12-26T...",
        "entities": {
            "W001": { ... issue data ... },
            "W002": { ... issue data ... }
        }
    }
    """

    def __init__(self, project_root: Optional[Path] = None):
        """
        Initialize issue repository.

        Args:
            project_root: Project root directory (default: cwd)
        """
        root = project_root or Path.cwd()
        storage_path = root / DEFAULT_STORAGE_PATH
        super().__init__(storage_path, "issues")
        logger.info("issue_repository_initialized", storage_path=str(storage_path))

    async def get(self, id: str) -> Optional[WardenIssue]:
        """Get issue by ID."""
        data = await self._read_data()
        entity_data = data.get("entities", {}).get(id)

        if entity_data is None:
            return None

        return WardenIssue.from_json(entity_data)

    async def get_all(self) -> List[WardenIssue]:
        """Get all issues."""
        data = await self._read_data()
        entities = data.get("entities", {})

        return [WardenIssue.from_json(e) for e in entities.values()]

    async def save(self, entity: WardenIssue) -> WardenIssue:
        """Save or update issue."""
        data = await self._read_data()

        if "entities" not in data:
            data["entities"] = {}

        # Serialize to JSON
        data["entities"][entity.id] = entity.to_json()

        await self._write_data(data)

        logger.debug("issue_saved", issue_id=entity.id)
        return entity

    async def delete(self, id: str) -> bool:
        """Delete issue by ID."""
        data = await self._read_data()
        entities = data.get("entities", {})

        if id not in entities:
            return False

        del entities[id]
        await self._write_data(data)

        logger.debug("issue_deleted", issue_id=id)
        return True

    async def exists(self, id: str) -> bool:
        """Check if issue exists."""
        data = await self._read_data()
        return id in data.get("entities", {})

    async def count(self) -> int:
        """Get total issue count."""
        data = await self._read_data()
        return len(data.get("entities", {}))

    async def get_by_state(self, state: IssueState) -> List[WardenIssue]:
        """Get all issues by state."""
        all_issues = await self.get_all()
        return [i for i in all_issues if i.state == state]

    async def get_by_severity(self, severity: IssueSeverity) -> List[WardenIssue]:
        """Get all issues by severity."""
        all_issues = await self.get_all()
        return [i for i in all_issues if i.severity == severity]

    async def get_by_file_path(self, file_path: str) -> List[WardenIssue]:
        """Get all issues for a specific file."""
        all_issues = await self.get_all()
        return [i for i in all_issues if i.file_path == file_path]

    async def get_history(self, issue_id: str) -> List[StateTransition]:
        """Get state transition history for an issue."""
        issue = await self.get(issue_id)
        if issue is None:
            return []
        return issue.state_history

    async def save_all(self, issues: List[WardenIssue]) -> List[WardenIssue]:
        """Batch save multiple issues."""
        data = await self._read_data()

        if "entities" not in data:
            data["entities"] = {}

        for issue in issues:
            data["entities"][issue.id] = issue.to_json()

        await self._write_data(data)

        logger.debug("issues_batch_saved", count=len(issues))
        return issues

    async def get_open_issues(self) -> List[WardenIssue]:
        """Get all open issues."""
        return await self.get_by_state(IssueState.OPEN)

    async def get_critical_issues(self) -> List[WardenIssue]:
        """Get all critical severity issues."""
        return await self.get_by_severity(IssueSeverity.CRITICAL)

    async def get_high_or_critical_issues(self) -> List[WardenIssue]:
        """Get all high or critical severity issues."""
        all_issues = await self.get_all()
        return [
            i
            for i in all_issues
            if i.severity in (IssueSeverity.CRITICAL, IssueSeverity.HIGH)
        ]
