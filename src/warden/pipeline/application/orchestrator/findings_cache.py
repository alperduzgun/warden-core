"""Cross-scan findings cache for all validation frames.

Stores ``FrameResult`` findings keyed by ``{frame_id}:{file_path}:{content_hash}``.
On a subsequent scan, if a file's content is unchanged, the cached findings are
replayed instead of re-running the LLM — matching the same pattern as
``TriageCacheManager`` for Phase 0.5.

All frame IDs (built-in, hub, and custom) are eligible for caching.  The cache
key includes the frame_id so frames are isolated from each other.  Content-hash
keying ensures that changed files are automatically re-analysed.  To force a
full re-scan (e.g. after frame rule changes), use ``warden scan --no-cache``.

Cache file: ``.warden/cache/findings_cache.json``

Schema versioning: ``CACHE_SCHEMA_VERSION`` is auto-derived from ``Finding``
field signatures.  Any change to the dataclass fields (addition, removal, or
type change) produces a different version string, automatically invalidating
stale cache entries without requiring a manual bump.
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

from warden.shared.utils.schema_version import derive_schema_version
from warden.validation.domain.frame import Finding

logger = structlog.get_logger(__name__)

MAX_ENTRIES = 10_000
CACHE_FILENAME = "findings_cache.json"
# Auto-derived from Finding field signatures — no manual bump needed.
CACHE_SCHEMA_VERSION: str = derive_schema_version(Finding)


class FindingsCache:
    """Persistent, hash-based findings cache for LLM validation frames.

    Each entry maps ``{frame_id}:{file_path}:{content_hash}`` to a list of
    serialised ``Finding`` dicts.  Findings are replayed on cache hit so that
    repeated ``warden scan`` runs on unchanged files skip all LLM calls.

    All frame IDs are cacheable — built-in, hub, and custom frames all benefit
    from incremental scan caching.

    Invalidation:
    - Content changes → different hash → automatic miss
    - Finding field changes → different schema version → automatic miss
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
        import os as _os

        h = FindingsCache.content_hash(content)
        # Normalize to collapse "./" / "../" and duplicate separators so that
        # equivalent paths (e.g. "./src/foo.py" vs "src/foo.py") map to the
        # same cache key and don't cause spurious misses.
        normalized = _os.path.normpath(file_path)
        return f"{frame_id}:{normalized}:{h}"

    def get_findings(self, frame_id: str, file_path: str, content: str) -> list[Finding] | None:
        """Return deserialized ``Finding`` objects on hit, or *None* on miss.

        Returns an empty list if the file was previously scanned clean.
        Returns *None* if there is no cache entry (uncached).
        """
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

    Persists all fields including nested objects (remediation, machine_context,
    exploit_evidence) via their to_json() methods. These are needed for SARIF
    report enrichment and fortification replay on cache hits.
    """
    data: dict[str, Any] = {
        "id": f.id,
        "severity": f.severity,
        "message": f.message,
        "location": f.location,
        "detail": f.detail,
        "code": f.code,
        "line": f.line,
        "column": f.column,
        "is_blocker": f.is_blocker,
        "detection_source": f.detection_source,
    }
    if f.remediation is not None:
        data["remediation"] = f.remediation.to_json()
    if f.machine_context is not None:
        data["machine_context"] = f.machine_context.to_json()
    if f.exploit_evidence is not None:
        data["exploit_evidence"] = f.exploit_evidence.to_json()
    return data


def _deserialize_finding(d: dict[str, Any]) -> Finding:
    """Reconstruct a Finding from a serialized dict.

    Raises ``KeyError`` or ``TypeError`` on missing/wrong-typed required fields
    so callers can catch and skip corrupt entries.
    """
    from warden.validation.domain.frame import ExploitEvidence, MachineContext, Remediation

    remediation = None
    if d.get("remediation"):
        r = d["remediation"]
        remediation = Remediation(
            description=r.get("description", ""),
            code=r.get("code", ""),
            unified_diff=r.get("unified_diff"),
        )

    machine_context = None
    if d.get("machine_context"):
        mc = d["machine_context"]
        machine_context = MachineContext(
            vulnerability_class=mc.get("vulnerability_class", "unknown"),
            source=mc.get("source"),
            sink=mc.get("sink"),
            sink_type=mc.get("sink_type"),
            data_flow_path=mc.get("data_flow_path", []),
            sanitizers_applied=mc.get("sanitizers_applied", []),
            suggested_fix_type=mc.get("suggested_fix_type"),
            related_files=mc.get("related_files", []),
        )

    exploit_evidence = None
    if d.get("exploit_evidence"):
        ee = d["exploit_evidence"]
        exploit_evidence = ExploitEvidence(
            witness_payload=ee.get("witness_payload", ""),
            attack_vector=ee.get("attack_vector", ""),
            data_flow_path=ee.get("data_flow_path", []),
            sink_type=ee.get("sink_type"),
            why_exploitable=ee.get("why_exploitable", ""),
            confidence=float(ee.get("confidence", 0.0)),
        )

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
        detection_source=d.get("detection_source"),
        remediation=remediation,
        machine_context=machine_context,
        exploit_evidence=exploit_evidence,
    )
