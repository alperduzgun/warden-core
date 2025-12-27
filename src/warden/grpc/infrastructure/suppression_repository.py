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
    BaseFileRepository[Dict[str, Any]], ISuppressionRepository
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

    def __init__(self, project_root: Optional[Path] = None):
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

    async def get(self, id: str) -> Optional[Dict[str, Any]]:
        """Get suppression by ID."""
        data = await self._read_data()
        return data.get("entities", {}).get(id)

    async def get_all(self) -> List[Dict[str, Any]]:
        """Get all suppressions."""
        data = await self._read_data()
        return list(data.get("entities", {}).values())

    async def save(self, entity: Dict[str, Any]) -> Dict[str, Any]:
        """Save or update suppression."""
        data = await self._read_data()

        if "entities" not in data:
            data["entities"] = {}

        entity_id = entity.get("id")
        if not entity_id:
            raise ValueError("Suppression entity must have an 'id' field")

        data["entities"][entity_id] = entity

        await self._write_data(data)

        logger.debug("suppression_saved", suppression_id=entity_id)
        return entity

    async def delete(self, id: str) -> bool:
        """Delete suppression by ID."""
        data = await self._read_data()
        entities = data.get("entities", {})

        if id not in entities:
            return False

        del entities[id]
        await self._write_data(data)

        logger.debug("suppression_deleted", suppression_id=id)
        return True

    async def exists(self, id: str) -> bool:
        """Check if suppression exists."""
        data = await self._read_data()
        return id in data.get("entities", {})

    async def count(self) -> int:
        """Get total suppression count."""
        data = await self._read_data()
        return len(data.get("entities", {}))

    async def get_enabled(self) -> List[Dict[str, Any]]:
        """Get all enabled suppressions."""
        all_suppressions = await self.get_all()
        return [s for s in all_suppressions if s.get("enabled", True)]

    async def get_for_file(self, file_path: str) -> List[Dict[str, Any]]:
        """Get suppressions applicable to a file path."""
        import fnmatch

        all_suppressions = await self.get_all()
        result = []

        for suppression in all_suppressions:
            if not suppression.get("enabled", True):
                continue

            file_pattern = suppression.get("file")
            if file_pattern is None:
                # Global suppression, applies to all files
                result.append(suppression)
            elif file_pattern == file_path:
                result.append(suppression)
            elif "*" in file_pattern or "?" in file_pattern:
                if fnmatch.fnmatch(file_path, file_pattern):
                    result.append(suppression)

        return result

    async def get_for_rule(self, rule_id: str) -> List[Dict[str, Any]]:
        """Get suppressions for a specific rule."""
        all_suppressions = await self.get_all()
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

    async def save_entry(self, entry: SuppressionEntry) -> SuppressionEntry:
        """Save a SuppressionEntry model."""
        await self.save(entry.to_json())
        return entry

    async def get_entry(self, id: str) -> Optional[SuppressionEntry]:
        """Get suppression as SuppressionEntry model."""
        data = await self.get(id)
        if data is None:
            return None
        return self._dict_to_entry(data)

    async def get_all_entries(self) -> List[SuppressionEntry]:
        """Get all suppressions as SuppressionEntry models."""
        all_data = await self.get_all()
        return [self._dict_to_entry(d) for d in all_data]

    def _dict_to_entry(self, data: Dict[str, Any]) -> SuppressionEntry:
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
