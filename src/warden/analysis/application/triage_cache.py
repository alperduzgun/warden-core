"""Hash-based triage cache for skipping redundant LLM triage calls.

Stores ``TriageDecision`` results keyed by ``{file_path}:{content_hash}``.
If a file's content hasn't changed, the cached decision is reused.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from warden.analysis.domain.triage_models import TriageDecision

logger = structlog.get_logger(__name__)

# Default limits
MAX_ENTRIES = 5000
CACHE_FILENAME = "triage_cache.json"


class TriageCacheManager:
    """Persistent, hash-based triage decision cache.

    Cache file: ``<project_root>/.warden/cache/triage_cache.json``

    Each entry maps ``file_path:sha256_hex`` to a serialised
    ``TriageDecision``.  On startup the cache is loaded from disk; on
    shutdown (or explicitly) it is flushed back.
    """

    def __init__(self, project_root: Path, *, max_entries: int = MAX_ENTRIES) -> None:
        self._cache_dir = project_root / ".warden" / "cache"
        self._cache_path = self._cache_dir / CACHE_FILENAME
        self._max_entries = max_entries
        self._store: dict[str, dict] = {}
        self._dirty = False
        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @staticmethod
    def cache_key(file_path: str, content: str) -> str:
        """Build a deterministic cache key from path + content hash."""
        content_hash = hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()[:16]
        return f"{file_path}:{content_hash}"

    def get(self, file_path: str, content: str) -> TriageDecision | None:
        """Look up a cached triage decision.  Returns *None* on miss."""
        key = self.cache_key(file_path, content)
        entry = self._store.get(key)
        if entry is None:
            return None

        # Touch for LRU
        entry["_ts"] = time.time()
        self._dirty = True

        try:
            from warden.analysis.domain.triage_models import TriageDecision

            decision = TriageDecision(**entry["decision"])
            decision.is_cached = True
            return decision
        except Exception:
            # Corrupt entry — evict
            self._store.pop(key, None)
            return None

    def put(self, file_path: str, content: str, decision: TriageDecision) -> None:
        """Store a triage decision in the cache."""
        key = self.cache_key(file_path, content)
        self._store[key] = {
            "decision": decision.model_dump(mode="json"),
            "_ts": time.time(),
        }
        self._dirty = True
        self._evict_if_needed()

    def flush(self) -> None:
        """Persist cache to disk (only if dirty)."""
        if not self._dirty:
            return
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            with open(self._cache_path, "w") as f:
                json.dump(self._store, f, separators=(",", ":"))
            self._dirty = False
            logger.debug("triage_cache_flushed", entries=len(self._store))
        except Exception as exc:
            logger.warning("triage_cache_flush_failed", error=str(exc))

    @property
    def size(self) -> int:
        return len(self._store)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if not self._cache_path.exists():
            return
        try:
            with open(self._cache_path) as f:
                data = json.load(f)
            if isinstance(data, dict):
                self._store = data
                logger.debug("triage_cache_loaded", entries=len(self._store))
            else:
                logger.warning("triage_cache_corrupt_reset")
                self._store = {}
        except Exception as exc:
            logger.warning("triage_cache_load_failed", error=str(exc))
            self._store = {}

    def _evict_if_needed(self) -> None:
        """LRU eviction when cache exceeds max size."""
        if len(self._store) <= self._max_entries:
            return
        # Sort by timestamp ascending, remove oldest 20%
        evict_count = len(self._store) - int(self._max_entries * 0.8)
        sorted_keys = sorted(self._store, key=lambda k: self._store[k].get("_ts", 0))
        for key in sorted_keys[:evict_count]:
            del self._store[key]
        logger.debug("triage_cache_evicted", evicted=evict_count, remaining=len(self._store))
