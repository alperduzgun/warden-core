"""
File-based implementation of ISuppressionRepository.

Stores suppressions in .warden/grpc/suppressions.json
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from warden.grpc.infrastructure.base_file_repository import BaseFileRepository
from warden.shared.domain.repository import ISuppressionRepository
from warden.suppression.models import SuppressionEntry, SuppressionType

# Optional: structured logging
try:
    from warden.shared.infrastructure.logging import get_logger

    logger = get_logger(__name__)
except ImportError:
    import logging

    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

DEFAULT_STORAGE_PATH = ".warden/grpc/suppressions.json"


class FileSuppressionRepository(
    BaseFileRepository[dict[str, Any]], ISuppressionRepository
):
    """
    File-based suppression repository implementation.

    Storage format:
    {
        "version": "1.0",
        "created_at": "2025-12-26T...",
        "updated_at": "2025-12-26T...",
        "entities": {
            "suppress-1": { ... suppression data ... },
            "suppress-2": { ... suppression data ... }
        }
    }
    """

    def __init__(self, project_root: Path | None = None):
        """
        Initialize suppression repository.

        Args:
            project_root: Project root directory (default: cwd)
        """
        root = project_root or Path.cwd()
        storage_path = root / DEFAULT_STORAGE_PATH
        super().__init__(storage_path, "suppressions")
        logger.info(
            "suppression_repository_initialized", storage_path=str(storage_path)
        )

    async def get_async(self, id: str) -> dict[str, Any] | None:
        """Get suppression by ID."""
        data = await self._read_data_async()
        return data.get("entities", {}).get(id)

    async def get_all_async(self) -> list[dict[str, Any]]:
        """Get all suppressions."""
        data = await self._read_data_async()
        return list(data.get("entities", {}).values())

    async def save_async(self, entity: dict[str, Any]) -> dict[str, Any]:
        """Save or update suppression."""
        data = await self._read_data_async()

        if "entities" not in data:
            data["entities"] = {}

        entity_id = entity.get("id")
        if not entity_id:
            raise ValueError("Suppression entity must have an 'id' field")

        data["entities"][entity_id] = entity

        await self._write_data_async(data)

        logger.debug("suppression_saved", suppression_id=entity_id)
        return entity

    async def delete_async(self, id: str) -> bool:
        """Delete suppression by ID."""
        data = await self._read_data_async()
        entities = data.get("entities", {})

        if id not in entities:
            return False

        del entities[id]
        await self._write_data_async(data)

        logger.debug("suppression_deleted", suppression_id=id)
        return True

    async def exists_async(self, id: str) -> bool:
        """Check if suppression exists."""
        data = await self._read_data_async()
        return id in data.get("entities", {})

    async def count_async(self) -> int:
        """Get total suppression count."""
        data = await self._read_data_async()
        return len(data.get("entities", {}))

    async def get_enabled_async(self) -> list[dict[str, Any]]:
        """Get all enabled suppressions."""
        all_suppressions = await self.get_all_async()
        return [s for s in all_suppressions if s.get("enabled", True)]

    async def get_for_file_async(self, file_path: str) -> list[dict[str, Any]]:
        """Get suppressions applicable to a file path."""
        import fnmatch

        all_suppressions = await self.get_all_async()
        result = []

        for suppression in all_suppressions:
            if not suppression.get("enabled", True):
                continue

            file_pattern = suppression.get("file")
            if file_pattern is None:
                # Global suppression, applies to all files
                result.append(suppression)
            elif file_pattern == file_path or (("*" in file_pattern or "?" in file_pattern) and fnmatch.fnmatch(file_path, file_pattern)):
                result.append(suppression)

        return result

    async def get_for_rule_async(self, rule_id: str) -> list[dict[str, Any]]:
        """Get suppressions for a specific rule."""
        all_suppressions = await self.get_all_async()
        result = []

        for suppression in all_suppressions:
            if not suppression.get("enabled", True):
                continue

            rules = suppression.get("rules", [])
            # Empty rules list means suppress all
            if not rules or rule_id in rules:
                result.append(suppression)

        return result

    # Additional methods for working with SuppressionEntry model

    async def save_entry_async(self, entry: SuppressionEntry) -> SuppressionEntry:
        """Save a SuppressionEntry model."""
        await self.save_async(entry.to_json())
        return entry

    async def get_entry_async(self, id: str) -> SuppressionEntry | None:
        """Get suppression as SuppressionEntry model."""
        data = await self.get_async(id)
        if data is None:
            return None
        return self._dict_to_entry(data)

    async def get_all_entries_async(self) -> list[SuppressionEntry]:
        """Get all suppressions as SuppressionEntry models."""
        all_data = await self.get_all_async()
        return [self._dict_to_entry(d) for d in all_data]

    def _dict_to_entry(self, data: dict[str, Any]) -> SuppressionEntry:
        """Convert dict to SuppressionEntry."""
        type_value = data.get("type", 1)
        if isinstance(type_value, int):
            suppression_type = SuppressionType(type_value)
        else:
            suppression_type = SuppressionType[str(type_value).upper()]

        return SuppressionEntry(
            id=data["id"],
            type=suppression_type,
            rules=data.get("rules", []),
            file=data.get("file"),
            line=data.get("line"),
            reason=data.get("reason"),
            enabled=data.get("enabled", True),
        )
