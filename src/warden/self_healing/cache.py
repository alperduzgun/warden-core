"""Persistent healing cache backed by .warden/cache/healing_cache.json."""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

from warden.self_healing.models import HealingRecord
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)

MAX_ENTRIES = 1000
TTL_SECONDS = 7 * 24 * 3600  # 7 days
EVICTION_RATIO = 0.2  # Remove oldest 20% when full
CACHE_FILENAME = "healing_cache.json"


class HealingCache:
    """Persistent cache for healing results.

    Stores past healing attempts keyed by error fingerprint.
    Cache HITs with fixed=True allow replaying the fix without re-diagnosis.
    Cache HITs with fixed=False allow skipping that strategy.
    """

    def __init__(self, project_root: Path, *, max_entries: int = MAX_ENTRIES) -> None:
        self._cache_dir = project_root / ".warden" / "cache"
        self._cache_path = self._cache_dir / CACHE_FILENAME
        self._max_entries = max_entries
        self._store: dict[str, dict] = {}
        self._dirty = False
        self._load()

    def get(self, error_key: str) -> HealingRecord | None:
        """Look up a cached healing record. Returns None on miss."""
        entry = self._store.get(error_key)
        if entry is None:
            return None

        # TTL check
        if time.time() - entry.get("timestamp", 0) > TTL_SECONDS:
            self._store.pop(error_key, None)
            self._dirty = True
            return None

        # Touch for LRU
        entry["timestamp"] = time.time()
        self._dirty = True

        try:
            return HealingRecord.from_dict(entry)
        except Exception as e:
            logger.debug(
                "healing_cache_deserialization_failed",
                error_key=error_key,
                error=str(e),
            )
            self._store.pop(error_key, None)
            self._dirty = True
            return None

    def put(self, record: HealingRecord) -> None:
        """Store a healing record."""
        self._store[record.error_key] = record.to_dict()
        self._dirty = True
        self._maybe_evict()

    def flush(self) -> None:
        """Write cache to disk if dirty.

        Uses atomic write (tempfile + os.replace) to prevent partial
        JSON corruption on crashes or concurrent flushes.
        """
        if not self._dirty:
            return

        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            data = json.dumps(self._store, indent=2, default=str)

            # Atomic write: write to temp file in same dir, then rename
            fd, tmp_path = tempfile.mkstemp(dir=str(self._cache_dir), suffix=".tmp")
            closed = False
            try:
                os.write(fd, data.encode("utf-8"))
                os.close(fd)
                closed = True
                os.replace(tmp_path, str(self._cache_path))
            except BaseException:
                if not closed:
                    os.close(fd)
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise

            self._dirty = False
            logger.debug("healing_cache_flushed", entries=len(self._store))
        except Exception as e:
            logger.debug("healing_cache_flush_failed", error=str(e))

    @property
    def size(self) -> int:
        return len(self._store)

    def clear(self) -> None:
        """Clear all entries."""
        self._store = {}
        self._dirty = True

    def _load(self) -> None:
        """Load cache from disk."""
        if not self._cache_path.exists():
            return

        try:
            raw = json.loads(self._cache_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._store = raw
                self._purge_stale()
                logger.debug("healing_cache_loaded", entries=len(self._store))
        except json.JSONDecodeError as e:
            logger.warning(
                "healing_cache_corrupt_json",
                error=str(e),
                path=str(self._cache_path),
            )
            # Remove corrupt file so next flush writes clean data
            try:
                self._cache_path.unlink()
            except OSError:
                pass
            self._store = {}
        except Exception as e:
            logger.debug("healing_cache_load_failed", error=str(e))
            self._store = {}

    def _purge_stale(self) -> None:
        """Remove entries older than TTL."""
        now = time.time()
        stale_keys = [k for k, v in self._store.items() if now - v.get("timestamp", 0) > TTL_SECONDS]
        for key in stale_keys:
            del self._store[key]
        if stale_keys:
            self._dirty = True

    def _maybe_evict(self) -> None:
        """Evict oldest entries if over capacity."""
        if len(self._store) <= self._max_entries:
            return

        sorted_keys = sorted(self._store.keys(), key=lambda k: self._store[k].get("timestamp", 0))
        evict_count = int(len(self._store) * EVICTION_RATIO)
        for key in sorted_keys[:evict_count]:
            del self._store[key]
        self._dirty = True
        logger.debug("healing_cache_evicted", evicted=evict_count, remaining=len(self._store))
