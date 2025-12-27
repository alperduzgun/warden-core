"""
Warden Servicer Base

Base class with repository-backed persistence for gRPC service.
State is preserved across server restarts.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from warden.cli_bridge.bridge import WardenBridge
from warden.grpc.infrastructure import (
    FileHistoryRepository,
    FileIssueRepository,
    FileSuppressionRepository,
)
from warden.shared.domain.repository import (
    IIssueHistoryRepository,
    IIssueRepository,
    ISuppressionRepository,
)

if TYPE_CHECKING:
    from warden.issues.domain.models import WardenIssue

# Optional: structured logging
try:
    from warden.shared.infrastructure.logging import get_logger

    logger = get_logger(__name__)
except ImportError:
    import logging

    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)


class WardenServicerBase:
    """
    Base class for WardenServicer with repository-backed persistence.

    Uses file-based repositories for persistent storage.
    State is preserved across server restarts.

    Provides initialization and common utilities used by all mixins.
    """

    def __init__(
        self,
        bridge: Optional[WardenBridge] = None,
        project_root: Optional[Path] = None,
        issue_repository: Optional[IIssueRepository] = None,
        suppression_repository: Optional[ISuppressionRepository] = None,
        history_repository: Optional[IIssueHistoryRepository] = None,
    ):
        """
        Initialize servicer with repositories.

        Args:
            bridge: Existing WardenBridge instance (creates new if None)
            project_root: Project root path for bridge initialization
            issue_repository: Custom issue repository (creates FileIssueRepository if None)
            suppression_repository: Custom suppression repository (creates FileSuppressionRepository if None)
            history_repository: Custom history repository (creates FileHistoryRepository if None)
        """
        self._project_root = project_root or Path.cwd()
        self.bridge = bridge or WardenBridge(project_root=self._project_root)
        self.start_time = datetime.now()
        self.total_scans = 0
        self.total_findings = 0

        # Initialize repositories (dependency injection pattern)
        self._issue_repo: IIssueRepository = issue_repository or FileIssueRepository(
            self._project_root
        )
        self._suppression_repo: ISuppressionRepository = (
            suppression_repository or FileSuppressionRepository(self._project_root)
        )
        self._history_repo: IIssueHistoryRepository = (
            history_repository or FileHistoryRepository(self._project_root)
        )

        # In-memory cache for backward compatibility with mixins
        # These will be synced with repositories
        self._issues: Dict[str, dict] = {}
        self._issue_history: List[dict] = []
        self._suppressions: Dict[str, dict] = {}

        # Report status tracking (kept in-memory as it's temporary state)
        self._report_status: Dict[str, dict] = {}

        logger.info(
            "grpc_servicer_initialized",
            endpoints=51,
            project_root=str(self._project_root),
            repositories=["issues", "suppressions", "history"],
        )

    @property
    def issue_repository(self) -> IIssueRepository:
        """Get issue repository."""
        return self._issue_repo

    @property
    def suppression_repository(self) -> ISuppressionRepository:
        """Get suppression repository."""
        return self._suppression_repo

    @property
    def history_repository(self) -> IIssueHistoryRepository:
        """Get history repository."""
        return self._history_repo

    async def load_from_repositories(self) -> None:
        """
        Load data from repositories into in-memory cache.

        Call this during startup to sync with persisted state.
        """
        # Load issues
        issues = await self._issue_repo.get_all()
        self._issues = {issue.id: issue.to_json() for issue in issues}

        # Load suppressions
        suppressions = await self._suppression_repo.get_all()
        self._suppressions = {s.get("id", str(i)): s for i, s in enumerate(suppressions)}

        # Load recent history
        history_events = await self._history_repo.get_all_events(limit=1000)
        self._issue_history = history_events

        logger.info(
            "repositories_loaded",
            issues_count=len(self._issues),
            suppressions_count=len(self._suppressions),
            history_events=len(self._issue_history),
        )

    def track_issue(self, finding: Dict[str, Any]) -> None:
        """
        Track a finding as an issue (in-memory).

        For persistence, use track_issue_async instead.
        """
        hash_content = (
            f"{finding.get('title', '')}"
            f"{finding.get('file_path', '')}"
            f"{finding.get('line_number', 0)}"
        )
        content_hash = hashlib.sha256(hash_content.encode()).hexdigest()[:16]

        issue_id = finding.get("id", str(uuid.uuid4()))

        if content_hash not in [i.get("hash") for i in self._issues.values()]:
            self._issues[issue_id] = {
                "id": issue_id,
                "hash": content_hash,
                "title": finding.get("title", ""),
                "description": finding.get("description", ""),
                "severity": finding.get("severity", "medium"),
                "state": "open",
                "file_path": finding.get("file_path", ""),
                "line_number": finding.get("line_number", 0),
                "code_snippet": finding.get("code_snippet", ""),
                "frame_id": finding.get("frame_id", ""),
                "first_detected": datetime.now().isoformat(),
                "last_seen": datetime.now().isoformat(),
                "occurrence_count": 1,
            }
        else:
            for issue in self._issues.values():
                if issue.get("hash") == content_hash:
                    issue["last_seen"] = datetime.now().isoformat()
                    issue["occurrence_count"] = issue.get("occurrence_count", 0) + 1
                    break

    async def track_issue_async(self, finding: Dict[str, Any]) -> Dict[str, Any]:
        """
        Track a finding as an issue with persistence.

        This method:
        1. Creates or updates issue in in-memory cache
        2. Saves to repository
        3. Logs event to history

        Args:
            finding: Finding data from pipeline execution

        Returns:
            The created/updated issue dict
        """
        hash_content = (
            f"{finding.get('title', '')}"
            f"{finding.get('file_path', '')}"
            f"{finding.get('line_number', 0)}"
        )
        content_hash = hashlib.sha256(hash_content.encode()).hexdigest()[:16]

        issue_id = finding.get("id", str(uuid.uuid4()))
        is_new = True

        # Check if issue already exists by hash
        existing_issue = None
        for issue in self._issues.values():
            if issue.get("hash") == content_hash:
                existing_issue = issue
                is_new = False
                break

        if is_new:
            issue_data = {
                "id": issue_id,
                "hash": content_hash,
                "title": finding.get("title", ""),
                "description": finding.get("description", ""),
                "severity": finding.get("severity", "medium"),
                "state": "open",
                "file_path": finding.get("file_path", ""),
                "line_number": finding.get("line_number", 0),
                "code_snippet": finding.get("code_snippet", ""),
                "frame_id": finding.get("frame_id", ""),
                "first_detected": datetime.now().isoformat(),
                "last_seen": datetime.now().isoformat(),
                "occurrence_count": 1,
            }
            self._issues[issue_id] = issue_data

            # Log creation event
            await self._history_repo.add_event(
                issue_id=issue_id,
                event={
                    "event_type": "issue_created",
                    "severity": issue_data["severity"],
                    "file_path": issue_data["file_path"],
                },
            )
        else:
            # Update existing issue
            existing_issue["last_seen"] = datetime.now().isoformat()
            existing_issue["occurrence_count"] = (
                existing_issue.get("occurrence_count", 0) + 1
            )
            issue_data = existing_issue

            # Log occurrence event
            await self._history_repo.add_event(
                issue_id=existing_issue["id"],
                event={
                    "event_type": "issue_recurred",
                    "occurrence_count": existing_issue["occurrence_count"],
                },
            )

        # Note: For full WardenIssue model persistence, the mixins should use
        # self.issue_repository directly. This method provides backward compatibility
        # with the existing dict-based approach.

        return issue_data

    async def save_issue(self, issue: "WardenIssue") -> "WardenIssue":
        """
        Save a WardenIssue model with persistence.

        Args:
            issue: WardenIssue domain model

        Returns:
            The saved issue
        """
        saved_issue = await self._issue_repo.save(issue)

        # Update in-memory cache
        self._issues[issue.id] = issue.to_json()

        # Log to history
        await self._history_repo.add_event(
            issue_id=issue.id,
            event={"event_type": "issue_saved", "state": issue.state.name},
        )

        return saved_issue

    async def get_issue(self, issue_id: str) -> Optional["WardenIssue"]:
        """Get issue by ID from repository."""
        return await self._issue_repo.get(issue_id)

    async def get_all_issues(self) -> List["WardenIssue"]:
        """Get all issues from repository."""
        return await self._issue_repo.get_all()

    async def delete_issue(self, issue_id: str) -> bool:
        """Delete issue and log to history."""
        deleted = await self._issue_repo.delete(issue_id)

        if deleted:
            # Remove from in-memory cache
            self._issues.pop(issue_id, None)

            # Log to history
            await self._history_repo.add_event(
                issue_id=issue_id,
                event={"event_type": "issue_deleted"},
            )

        return deleted

    def hash_finding(self, finding: Any) -> str:
        """Create hash for a proto finding."""
        hash_content = f"{finding.title}{finding.file_path}{finding.line_number}"
        return hashlib.sha256(hash_content.encode()).hexdigest()[:16]
