"""
File-based implementation of IIssueHistoryRepository.

Stores issue history/audit trail in .warden/grpc/history.json
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from warden.grpc.infrastructure.base_file_repository import BaseFileRepository
from warden.shared.domain.repository import IIssueHistoryRepository

# Optional: structured logging
try:
    from warden.shared.infrastructure.logging import get_logger

    logger = get_logger(__name__)
except ImportError:
    import logging

    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

DEFAULT_STORAGE_PATH = ".warden/grpc/history.json"


class FileHistoryRepository(BaseFileRepository, IIssueHistoryRepository):
    """
    File-based history repository implementation.

    Storage format:
    {
        "version": "1.0",
        "created_at": "2025-12-26T...",
        "updated_at": "2025-12-26T...",
        "events": [
            {"issue_id": "W001", "event_type": "created", "timestamp": "...", ...},
            {"issue_id": "W001", "event_type": "state_changed", "timestamp": "...", ...}
        ]
    }
    """

    MAX_EVENTS = 10000  # Maximum events to store

    def __init__(self, project_root: Optional[Path] = None):
        """
        Initialize history repository.

        Args:
            project_root: Project root directory (default: cwd)
        """
        root = project_root or Path.cwd()
        storage_path = root / DEFAULT_STORAGE_PATH
        super().__init__(storage_path, "history")
        logger.info("history_repository_initialized", storage_path=str(storage_path))

    def _get_empty_structure(self) -> Dict[str, Any]:
        """Get empty data structure for history storage."""
        return {
            "version": "1.0",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "events": [],
        }

    async def add_event(self, issue_id: str, event: Dict[str, Any]) -> None:
        """Add an event to issue history."""
        data = await self._read_data()

        if "events" not in data:
            data["events"] = []

        # Add event with metadata
        event_record = {
            "issue_id": issue_id,
            "timestamp": datetime.now().isoformat(),
            **event,
        }

        data["events"].append(event_record)

        # Trim old events if exceeding max
        if len(data["events"]) > self.MAX_EVENTS:
            data["events"] = data["events"][-self.MAX_EVENTS :]

        await self._write_data(data)

        logger.debug(
            "history_event_added",
            issue_id=issue_id,
            event_type=event.get("event_type"),
        )

    async def get_events(self, issue_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Get events for an issue."""
        data = await self._read_data()
        events = data.get("events", [])

        # Filter by issue_id
        issue_events = [e for e in events if e.get("issue_id") == issue_id]

        # Return most recent first, limited
        return sorted(
            issue_events[-limit:],
            key=lambda e: e.get("timestamp", ""),
            reverse=True,
        )

    async def get_all_events(self, limit: int = 1000) -> List[Dict[str, Any]]:
        """Get all events across all issues."""
        data = await self._read_data()
        events = data.get("events", [])

        # Return most recent first, limited
        return sorted(
            events[-limit:],
            key=lambda e: e.get("timestamp", ""),
            reverse=True,
        )

    async def get_events_by_type(
        self, event_type: str, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get events by event type."""
        data = await self._read_data()
        events = data.get("events", [])

        # Filter by event_type
        filtered_events = [e for e in events if e.get("event_type") == event_type]

        # Return most recent first, limited
        return sorted(
            filtered_events[-limit:],
            key=lambda e: e.get("timestamp", ""),
            reverse=True,
        )

    async def get_events_since(
        self, since: datetime, limit: int = 1000
    ) -> List[Dict[str, Any]]:
        """Get events since a specific datetime."""
        data = await self._read_data()
        events = data.get("events", [])

        since_str = since.isoformat()
        filtered_events = [
            e for e in events if e.get("timestamp", "") >= since_str
        ]

        # Return most recent first, limited
        return sorted(
            filtered_events[-limit:],
            key=lambda e: e.get("timestamp", ""),
            reverse=True,
        )

    async def count_events(self) -> int:
        """Get total event count."""
        data = await self._read_data()
        return len(data.get("events", []))

    async def count_events_for_issue(self, issue_id: str) -> int:
        """Get event count for a specific issue."""
        events = await self.get_events(issue_id, limit=self.MAX_EVENTS)
        return len(events)
