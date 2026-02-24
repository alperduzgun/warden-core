"""
Classification result cache.

Caches the selected frame IDs for a given set of files + project state so
that the expensive LLM classification call can be skipped on repeat scans
of unchanged files.

Cache key = SHA256 of:
  - sorted (file_path, SHA256(content)) pairs
  - sorted available frame IDs
  - warden.yaml/config.yaml content hash (if present)

Cache is stored as a JSON file under .warden/cache/classification_cache.json
with a maximum of MAX_ENTRIES entries (FIFO eviction, oldest first).
"""

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from warden.shared.infrastructure.logging import get_logger
from warden.validation.domain.frame import CodeFile

logger = get_logger(__name__)

_MAX_ENTRIES = 500
_TTL_SECONDS = 7 * 24 * 3600  # 7 days


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]


class ClassificationCache:
    """
    Disk-backed cache for classification results.

    Thread-safety note: only asyncio (cooperative) callers — no locking needed.
    """

    def __init__(self, project_root: Path) -> None:
        self._path = project_root / ".warden" / "cache" / "classification_cache.json"
        self._data: dict[str, Any] = {}
        self._loaded = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, key: str) -> list[str] | None:
        """Return cached frame list or None on miss / expiry."""
        self._load()
        entry = self._data.get(key)
        if entry is None:
            return None
        if time.time() - entry["ts"] > _TTL_SECONDS:
            del self._data[key]
            return None
        logger.debug("classification_cache_hit", key=key[:12])
        return entry["frames"]

    def put(self, key: str, frames: list[str]) -> None:
        """Store classification result, evicting oldest entries when full."""
        self._load()
        self._data[key] = {"frames": frames, "ts": time.time()}
        # FIFO eviction
        if len(self._data) > _MAX_ENTRIES:
            oldest = sorted(self._data.items(), key=lambda kv: kv[1]["ts"])
            for k, _ in oldest[: len(self._data) - _MAX_ENTRIES]:
                del self._data[k]
        self._flush()

    def invalidate_all(self) -> None:
        """Wipe the cache (e.g. after new frames are installed)."""
        self._data = {}
        self._flush()

    # ------------------------------------------------------------------
    # Key construction helpers
    # ------------------------------------------------------------------

    @staticmethod
    def make_key(
        code_files: list[CodeFile],
        available_frame_ids: list[str],
        project_root: Path | None = None,
    ) -> str:
        """
        Build a stable cache key from inputs.

        Including warden config hash ensures the key changes when the user
        edits warden.yaml (which may alter which frames are loaded).
        """
        # File fingerprints — sort for determinism
        file_parts = sorted(f"{cf.path}:{_content_hash(cf.content or '')}" for cf in code_files)
        frame_part = ",".join(sorted(str(fid) for fid in available_frame_ids))

        config_hash = ""
        if project_root:
            for cfg_name in ("warden.yaml", ".warden/config.yaml"):
                cfg_path = project_root / cfg_name
                if cfg_path.exists():
                    try:
                        config_hash = _content_hash(cfg_path.read_text())
                    except OSError:
                        pass
                    break

        raw = "|".join([*file_parts, frame_part, config_hash])
        return hashlib.sha256(raw.encode()).hexdigest()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self._path.exists():
            return
        try:
            with open(self._path) as fh:
                self._data = json.load(fh)
        except Exception as exc:
            logger.warning("classification_cache_load_error", error=str(exc))
            self._data = {}

    def _flush(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "w") as fh:
                json.dump(self._data, fh, separators=(",", ":"))
        except Exception as exc:
            logger.warning("classification_cache_flush_error", error=str(exc))
