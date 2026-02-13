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

    def __init__(self, project_root: Path | None = None):
        """
        Initialize issue repository.

        Args:
            project_root: Project root directory (default: cwd)
        """
        root = project_root or Path.cwd()
        storage_path = root / DEFAULT_STORAGE_PATH
        super().__init__(storage_path, "issues")
        logger.info("issue_repository_initialized", storage_path=str(storage_path))

    async def get_async(self, id: str) -> WardenIssue | None:
        """Get issue by ID."""
        data = await self._read_data_async()
        entity_data = data.get("entities", {}).get(id)

        if entity_data is None:
            return None

        return WardenIssue.from_json(entity_data)

    async def get_all_async(self) -> list[WardenIssue]:
        """Get all issues."""
        data = await self._read_data_async()
        entities = data.get("entities", {})

        return [WardenIssue.from_json(e) for e in entities.values()]

    async def save_async(self, entity: WardenIssue) -> WardenIssue:
        """Save or update issue."""
        data = await self._read_data_async()

        if "entities" not in data:
            data["entities"] = {}

        # Serialize to JSON
        data["entities"][entity.id] = entity.to_json()

        await self._write_data_async(data)

        logger.debug("issue_saved", issue_id=entity.id)
        return entity

    async def delete_async(self, id: str) -> bool:
        """Delete issue by ID."""
        data = await self._read_data_async()
        entities = data.get("entities", {})

        if id not in entities:
            return False

        del entities[id]
        await self._write_data_async(data)

        logger.debug("issue_deleted", issue_id=id)
        return True

    async def exists_async(self, id: str) -> bool:
        """Check if issue exists."""
        data = await self._read_data_async()
        return id in data.get("entities", {})

    async def count_async(self) -> int:
        """Get total issue count."""
        data = await self._read_data_async()
        return len(data.get("entities", {}))

    async def get_by_state_async(self, state: IssueState) -> list[WardenIssue]:
        """Get all issues by state."""
        all_issues = await self.get_all_async()
        return [i for i in all_issues if i.state == state]

    async def get_by_severity_async(self, severity: IssueSeverity) -> list[WardenIssue]:
        """Get all issues by severity."""
        all_issues = await self.get_all_async()
        return [i for i in all_issues if i.severity == severity]

    async def get_by_file_path_async(self, file_path: str) -> list[WardenIssue]:
        """Get all issues for a specific file."""
        all_issues = await self.get_all_async()
        return [i for i in all_issues if i.file_path == file_path]

    async def get_history_async(self, issue_id: str) -> list[StateTransition]:
        """Get state transition history for an issue."""
        issue = await self.get_async(issue_id)
        if issue is None:
            return []
        return issue.state_history

    async def save_all_async(self, issues: list[WardenIssue]) -> list[WardenIssue]:
        """Batch save multiple issues."""
        data = await self._read_data_async()

        if "entities" not in data:
            data["entities"] = {}

        for issue in issues:
            data["entities"][issue.id] = issue.to_json()

        await self._write_data_async(data)

        logger.debug("issues_batch_saved", count=len(issues))
        return issues

    async def get_open_issues_async(self) -> list[WardenIssue]:
        """Get all open issues."""
        return await self.get_by_state_async(IssueState.OPEN)

    async def get_critical_issues_async(self) -> list[WardenIssue]:
        """Get all critical severity issues."""
        return await self.get_by_severity_async(IssueSeverity.CRITICAL)

    async def get_high_or_critical_issues_async(self) -> list[WardenIssue]:
        """Get all high or critical severity issues."""
        all_issues = await self.get_all_async()
        return [
            i
            for i in all_issues
            if i.severity in (IssueSeverity.CRITICAL, IssueSeverity.HIGH)
        ]
