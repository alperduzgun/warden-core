"""Cross-scan findings cache for SecurityFrame and other LLM-heavy frames.

Stores ``FrameResult`` findings keyed by ``{frame_id}:{file_path}:{content_hash}``.
On a subsequent scan, if a file's content is unchanged, the cached findings are
replayed instead of re-running the LLM — matching the same pattern as
``TriageCacheManager`` for Phase 0.5.

Cache file: ``.warden/cache/findings_cache.json``

Schema versioning: bump ``CACHE_SCHEMA_VERSION`` whenever ``Finding`` fields
change to prevent stale entries from deserialising incorrectly.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

import structlog

from warden.validation.domain.frame import Finding

logger = structlog.get_logger(__name__)

MAX_ENTRIES = 10_000
CACHE_FILENAME = "findings_cache.json"
# Bump this when Finding schema changes to auto-invalidate stale caches.
CACHE_SCHEMA_VERSION = 1

# Frame IDs eligible for cross-scan caching.  Only deterministic LLM frames
# should be listed here; frames with side-effects or that depend on external
# state should be excluded.
CACHEABLE_FRAME_IDS: frozenset[str] = frozenset(
    {
        "security",
        "resilience",
        "spec",
        "property",
        "orphan",
        "fuzz",
        "architecture",
    }
)


class FindingsCache:
    """Persistent, hash-based findings cache for LLM validation frames.

    Each entry maps ``{frame_id}:{file_path}:{content_hash}`` to a list of
    serialised ``Finding`` dicts.  Findings are replayed on cache hit so that
    repeated ``warden scan`` runs on unchanged files skip all LLM calls.

    Invalidation:
    - Content changes → different hash → automatic miss
    - Frame rule changes → use ``warden scan --no-cache`` (sets ``force_scan``)
    """

    def __init__(self, project_root: Path, *, max_entries: int = MAX_ENTRIES) -> None:
        self._cache_dir = project_root / ".warden" / "cache"
        self._cache_path = self._cache_dir / CACHE_FILENAME
        self._max_entries = max_entries
        self._store: dict[str, dict[str, Any]] = {}
        self._dirty = False
        self._hits = 0
        self._misses = 0
        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @staticmethod
    def content_hash(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()[:16]

    @staticmethod
    def cache_key(frame_id: str, file_path: str, content: str) -> str:
        h = FindingsCache.content_hash(content)
        return f"{frame_id}:{file_path}:{h}"

    def get_findings(self, frame_id: str, file_path: str, content: str) -> list[Finding] | None:
        """Return deserialized ``Finding`` objects on hit, or *None* on miss.

        Returns an empty list if the file was previously scanned clean.
        Returns *None* if there is no cache entry (uncached).
        """
        if frame_id not in CACHEABLE_FRAME_IDS:
            return None

        key = self.cache_key(frame_id, file_path, content)
        entry = self._store.get(key)
        if entry is None:
            self._misses += 1
            return None

        # Schema version guard — stale entries are silently evicted
        if entry.get("_schema_v") != CACHE_SCHEMA_VERSION:
            del self._store[key]
            self._dirty = True
            self._misses += 1
            logger.debug("findings_cache_schema_mismatch", frame=frame_id, file=file_path)
            return None

        # Touch for LRU
        entry["_ts"] = time.time()
        self._dirty = True
        self._hits += 1

        findings: list[Finding] = []
        for fd in entry.get("findings", []):
            try:
                findings.append(_deserialize_finding(fd))
            except Exception as exc:
                logger.debug("findings_cache_deserialize_error", error=str(exc))
        return findings

    def put_findings(self, frame_id: str, file_path: str, content: str, findings: list[Finding]) -> None:
        """Serialize and store findings for a (frame, file) pair."""
        if frame_id not in CACHEABLE_FRAME_IDS:
            return

        key = self.cache_key(frame_id, file_path, content)
        self._store[key] = {
            "findings": [_serialize_finding(f) for f in findings],
            "_ts": time.time(),
            "_schema_v": CACHE_SCHEMA_VERSION,
        }
        self._dirty = True
        self._evict_if_needed()

    def flush(self) -> None:
        """Persist cache to disk atomically (write-then-rename, only if dirty).

        Atomic write prevents corruption if the process is killed mid-write.
        """
        if not self._dirty:
            return
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            # Write to a temp file in the same directory, then rename atomically.
            fd, tmp_path = tempfile.mkstemp(dir=self._cache_dir, suffix=".tmp")
            try:
                with os.fdopen(fd, "w") as f:
                    json.dump(self._store, f, separators=(",", ":"))
                os.replace(tmp_path, self._cache_path)  # atomic on POSIX
            except Exception:
                # Clean up temp file on failure
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
            self._dirty = False
            logger.debug(
                "findings_cache_flushed",
                entries=len(self._store),
                hits=self._hits,
                misses=self._misses,
            )
        except Exception as exc:
            logger.warning("findings_cache_flush_failed", error=str(exc))

    @property
    def size(self) -> int:
        return len(self._store)

    @property
    def hit_rate(self) -> float:
        total = self._hits + self._misses
        return self._hits / total if total else 0.0

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
                logger.debug("findings_cache_loaded", entries=len(self._store))
            else:
                logger.warning("findings_cache_corrupt_reset")
                self._store = {}
        except Exception as exc:
            logger.warning("findings_cache_load_failed", error=str(exc))
            self._store = {}

    def _evict_if_needed(self) -> None:
        """LRU eviction when cache exceeds max size (evict oldest 20%)."""
        if len(self._store) <= self._max_entries:
            return
        evict_count = len(self._store) - int(self._max_entries * 0.8)
        sorted_keys = sorted(self._store, key=lambda k: self._store[k].get("_ts", 0))
        for key in sorted_keys[:evict_count]:
            del self._store[key]
        self._dirty = True
        logger.debug("findings_cache_evicted", evicted=evict_count, remaining=len(self._store))


# ---------------------------------------------------------------------------
# Private serialization helpers — keeps Finding schema changes localised here
# ---------------------------------------------------------------------------


def _serialize_finding(f: Finding) -> dict[str, Any]:
    """Serialize a Finding to a plain dict using snake_case field names.

    Only primitive/scalar fields are persisted. Complex nested objects
    (Remediation, MachineContext, ExploitEvidence) are intentionally dropped:
    they are regenerated on the next LLM call and are not needed for
    cache-hit replay (findings are used for dedup/reporting, not for
    deep remediation replay).
    """
    return {
        "id": f.id,
        "severity": f.severity,
        "message": f.message,
        "location": f.location,
        "detail": f.detail,
        "code": f.code,
        "line": f.line,
        "column": f.column,
        "is_blocker": f.is_blocker,
    }


def _deserialize_finding(d: dict[str, Any]) -> Finding:
    """Reconstruct a Finding from a serialized dict.

    Raises ``KeyError`` or ``TypeError`` on missing/wrong-typed required fields
    so callers can catch and skip corrupt entries.
    """
    return Finding(
        id=str(d["id"]),
        severity=str(d["severity"]),
        message=str(d["message"]),
        location=str(d["location"]),
        detail=d.get("detail"),
        code=d.get("code"),
        line=int(d.get("line", 0)),
        column=int(d.get("column", 0)),
        is_blocker=bool(d.get("is_blocker", False)),
    )
