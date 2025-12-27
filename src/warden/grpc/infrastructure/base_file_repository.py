"""
Base file repository with common JSON file operations.

Provides thread-safe file I/O and common persistence logic.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Generic, Optional, TypeVar

import aiofiles

# Optional: structured logging
try:
    from warden.shared.infrastructure.logging import get_logger

    logger = get_logger(__name__)
except ImportError:
    import logging

    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)


T = TypeVar("T")


class BaseFileRepository(Generic[T]):
    """
    Base class for file-based JSON repositories.

    Features:
    - Async file I/O with aiofiles
    - Automatic backup before writes
    - Thread-safe with asyncio.Lock
    - Simple cache with configurable TTL
    - Auto-creates .warden/grpc directory
    """

    def __init__(
        self,
        storage_path: Path,
        entity_name: str,
        create_if_missing: bool = True,
        cache_ttl_seconds: int = 5,
    ):
        """
        Initialize file repository.

        Args:
            storage_path: Path to JSON storage file
            entity_name: Entity name for logging
            create_if_missing: Create file if it doesn't exist
            cache_ttl_seconds: Cache time-to-live in seconds
        """
        self.storage_path = storage_path
        self.entity_name = entity_name
        self._lock = asyncio.Lock()
        self._create_if_missing = create_if_missing
        self._cache: Optional[Dict[str, Any]] = None
        self._cache_time: Optional[datetime] = None
        self._cache_ttl_seconds = cache_ttl_seconds

    async def _ensure_storage_exists(self) -> None:
        """Ensure storage directory and file exist."""
        # Create parent directory
        if not self.storage_path.parent.exists():
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            logger.info(
                "storage_directory_created",
                path=str(self.storage_path.parent),
                entity=self.entity_name,
            )

        # Create file with empty structure
        if self._create_if_missing and not self.storage_path.exists():
            await self._write_data(self._get_empty_structure())
            logger.info(
                "storage_file_created",
                path=str(self.storage_path),
                entity=self.entity_name,
            )

    def _get_empty_structure(self) -> Dict[str, Any]:
        """Get empty data structure for new storage file."""
        return {
            "version": "1.0",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "entities": {},
        }

    async def _read_data(self) -> Dict[str, Any]:
        """Read and parse JSON data from storage file."""
        await self._ensure_storage_exists()

        # Check cache
        now = datetime.now()
        if (
            self._cache is not None
            and self._cache_time is not None
            and (now - self._cache_time).total_seconds() < self._cache_ttl_seconds
        ):
            return self._cache

        try:
            async with aiofiles.open(self.storage_path, "r", encoding="utf-8") as f:
                content = await f.read()
                data = (
                    json.loads(content) if content.strip() else self._get_empty_structure()
                )

                # Update cache
                self._cache = data
                self._cache_time = now

                return data
        except json.JSONDecodeError as e:
            logger.error(
                "storage_file_corrupted",
                path=str(self.storage_path),
                error=str(e),
            )
            # Return empty structure on corruption
            return self._get_empty_structure()
        except FileNotFoundError:
            return self._get_empty_structure()

    async def _write_data(self, data: Dict[str, Any]) -> None:
        """Write data to storage file with backup."""
        async with self._lock:
            # Create backup if file exists
            if self.storage_path.exists():
                backup_path = self.storage_path.with_suffix(".json.bak")
                try:
                    # Read current content and write to backup
                    async with aiofiles.open(
                        self.storage_path, "r", encoding="utf-8"
                    ) as f:
                        current_content = await f.read()
                    async with aiofiles.open(backup_path, "w", encoding="utf-8") as f:
                        await f.write(current_content)
                except Exception as e:
                    logger.warning("backup_failed", error=str(e))

            # Update timestamp
            data["updated_at"] = datetime.now().isoformat()

            # Ensure parent directory exists
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)

            # Write new data
            async with aiofiles.open(self.storage_path, "w", encoding="utf-8") as f:
                await f.write(json.dumps(data, indent=2, default=str))

            # Update cache
            self._cache = data
            self._cache_time = datetime.now()

            logger.debug(
                "storage_file_written",
                path=str(self.storage_path),
                entity=self.entity_name,
            )

    def _invalidate_cache(self) -> None:
        """Invalidate the cache."""
        self._cache = None
        self._cache_time = None

    async def clear_all(self) -> None:
        """Clear all entities from storage."""
        data = self._get_empty_structure()
        await self._write_data(data)
        logger.info("storage_cleared", entity=self.entity_name)
