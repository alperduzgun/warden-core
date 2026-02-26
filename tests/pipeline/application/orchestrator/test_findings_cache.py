"""Tests for FindingsCache — cross-scan LLM findings persistence.

Covers:
- TestFindingsCacheSerialization:  serialize->deserialize roundtrip, is_blocker fidelity,
                                   missing field raises, wrong type raises
- TestFindingsCacheOperations:     miss/hit, clean-file empty list, non-cacheable frame,
                                   different content is miss, same content different file is miss
- TestFindingsCacheSchema:         schema version mismatch evicts, correct version hits,
                                   auto-derived version is deterministic, version is a string
- TestFindingsCacheFlush:          creates file, atomic (no .tmp orphan), idempotent if not dirty,
                                   reload after flush hits
- TestFindingsCacheEviction:       LRU evict when exceeds max_entries
- TestFindingsCacheStats:          hit_rate=0 on empty, hit_rate after operations
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from warden.pipeline.application.orchestrator.findings_cache import (
    CACHE_SCHEMA_VERSION,
    CACHEABLE_FRAME_IDS,
    FindingsCache,
    _deserialize_finding,
    _serialize_finding,
)
from warden.validation.domain.frame import Finding

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_finding(
    id: str = "F001",
    severity: str = "HIGH",
    message: str = "test message",
    location: str = "src/app.py:10",
    detail: str | None = "some detail",
    code: str | None = "x = eval(input())",
    line: int = 10,
    column: int = 0,
    is_blocker: bool = False,
) -> Finding:
    return Finding(
        id=id,
        severity=severity,
        message=message,
        location=location,
        detail=detail,
        code=code,
        line=line,
        column=column,
        is_blocker=is_blocker,
    )


def _make_cache(tmp_path: Path, max_entries: int = 100) -> FindingsCache:
    return FindingsCache(tmp_path, max_entries=max_entries)


# First cacheable frame ID for convenience
_FRAME = next(iter(sorted(CACHEABLE_FRAME_IDS)))
_NON_CACHEABLE = "unknown_frame_xyz"


# ===========================================================================
# TestFindingsCacheSerialization
# ===========================================================================


class TestFindingsCacheSerialization:
    """Serialize -> deserialize roundtrips and field fidelity."""

    def test_serialize_roundtrip_basic_fields(self) -> None:
        f = _make_finding()
        d = _serialize_finding(f)
        restored = _deserialize_finding(d)

        assert restored.id == f.id
        assert restored.severity == f.severity
        assert restored.message == f.message
        assert restored.location == f.location
        assert restored.detail == f.detail
        assert restored.code == f.code
        assert restored.line == f.line
        assert restored.column == f.column

    def test_serialize_preserves_is_blocker_true(self) -> None:
        f = _make_finding(is_blocker=True)
        d = _serialize_finding(f)
        assert d["is_blocker"] is True

        restored = _deserialize_finding(d)
        assert restored.is_blocker is True

    def test_serialize_preserves_is_blocker_false(self) -> None:
        f = _make_finding(is_blocker=False)
        d = _serialize_finding(f)
        assert d["is_blocker"] is False

        restored = _deserialize_finding(d)
        assert restored.is_blocker is False

    def test_deserialize_missing_required_field_raises(self) -> None:
        d = _serialize_finding(_make_finding())
        del d["id"]  # Remove required field
        with pytest.raises((KeyError, TypeError)):
            _deserialize_finding(d)

    def test_deserialize_missing_message_raises(self) -> None:
        d = _serialize_finding(_make_finding())
        del d["message"]
        with pytest.raises((KeyError, TypeError)):
            _deserialize_finding(d)


# ===========================================================================
# TestFindingsCacheOperations
# ===========================================================================


class TestFindingsCacheOperations:
    """get / put / miss / hit / cacheable guard."""

    def test_get_miss_returns_none(self, tmp_path: Path) -> None:
        cache = _make_cache(tmp_path)
        result = cache.get_findings(_FRAME, "src/app.py", "content")
        assert result is None

    def test_put_then_get_hit(self, tmp_path: Path) -> None:
        cache = _make_cache(tmp_path)
        findings = [_make_finding()]
        cache.put_findings(_FRAME, "src/app.py", "hello", findings)

        result = cache.get_findings(_FRAME, "src/app.py", "hello")
        assert result is not None
        assert len(result) == 1
        assert result[0].id == "F001"

    def test_get_clean_file_returns_empty_list(self, tmp_path: Path) -> None:
        """A file scanned with zero findings should return [] (not None) on hit."""
        cache = _make_cache(tmp_path)
        cache.put_findings(_FRAME, "src/clean.py", "clean", [])

        result = cache.get_findings(_FRAME, "src/clean.py", "clean")
        assert result is not None
        assert result == []

    def test_noncacheable_frame_always_miss(self, tmp_path: Path) -> None:
        cache = _make_cache(tmp_path)
        findings = [_make_finding()]
        # put should silently skip non-cacheable frames
        cache.put_findings(_NON_CACHEABLE, "src/app.py", "content", findings)

        result = cache.get_findings(_NON_CACHEABLE, "src/app.py", "content")
        assert result is None

    def test_different_content_is_cache_miss(self, tmp_path: Path) -> None:
        cache = _make_cache(tmp_path)
        cache.put_findings(_FRAME, "src/app.py", "version_1", [_make_finding()])

        # Different content -> different hash -> miss
        result = cache.get_findings(_FRAME, "src/app.py", "version_2")
        assert result is None

    def test_same_content_different_file_is_miss(self, tmp_path: Path) -> None:
        cache = _make_cache(tmp_path)
        cache.put_findings(_FRAME, "src/a.py", "shared content", [_make_finding()])

        # Same content but different path -> miss
        result = cache.get_findings(_FRAME, "src/b.py", "shared content")
        assert result is None

    def test_multiple_findings_preserved(self, tmp_path: Path) -> None:
        cache = _make_cache(tmp_path)
        findings = [
            _make_finding(id="F001", line=1),
            _make_finding(id="F002", line=5, is_blocker=True),
            _make_finding(id="F003", line=10),
        ]
        cache.put_findings(_FRAME, "src/app.py", "content", findings)

        result = cache.get_findings(_FRAME, "src/app.py", "content")
        assert result is not None
        assert len(result) == 3
        ids = {f.id for f in result}
        assert ids == {"F001", "F002", "F003"}
        # Blocker status preserved
        blockers = [f for f in result if f.is_blocker]
        assert len(blockers) == 1
        assert blockers[0].id == "F002"


# ===========================================================================
# TestFindingsCacheSchema
# ===========================================================================


class TestFindingsCacheSchema:
    """Schema version guard — stale entries are evicted."""

    def test_schema_version_is_auto_derived_string(self) -> None:
        """CACHE_SCHEMA_VERSION should be a hex string, not a manual int."""
        assert isinstance(CACHE_SCHEMA_VERSION, str)
        assert len(CACHE_SCHEMA_VERSION) == 8
        # Must be valid hex
        int(CACHE_SCHEMA_VERSION, 16)

    def test_schema_version_is_deterministic(self) -> None:
        """Calling derive_schema_version twice yields the same result."""
        from warden.shared.utils.schema_version import derive_schema_version

        v1 = derive_schema_version(Finding)
        v2 = derive_schema_version(Finding)
        assert v1 == v2
        assert v1 == CACHE_SCHEMA_VERSION

    def test_correct_schema_version_hits(self, tmp_path: Path) -> None:
        cache = _make_cache(tmp_path)
        cache.put_findings(_FRAME, "src/app.py", "content", [_make_finding()])

        result = cache.get_findings(_FRAME, "src/app.py", "content")
        assert result is not None

    def test_schema_version_mismatch_evicts_entry(self, tmp_path: Path) -> None:
        """Manually inject a stale schema version; get should return None and delete entry."""
        cache = _make_cache(tmp_path)
        content = "some content"

        # Build a valid entry then corrupt its schema version
        cache.put_findings(_FRAME, "src/app.py", content, [_make_finding()])
        key = FindingsCache.cache_key(_FRAME, "src/app.py", content)

        # Corrupt the schema version in internal store
        cache._store[key]["_schema_v"] = "stale000"

        result = cache.get_findings(_FRAME, "src/app.py", content)
        assert result is None

        # Entry must have been evicted from store
        assert key not in cache._store


# ===========================================================================
# TestFindingsCacheFlush
# ===========================================================================


class TestFindingsCacheFlush:
    """Disk persistence: atomic write, idempotent, reload."""

    def test_flush_creates_file(self, tmp_path: Path) -> None:
        cache = _make_cache(tmp_path)
        cache.put_findings(_FRAME, "src/app.py", "content", [_make_finding()])
        cache.flush()

        cache_file = tmp_path / ".warden" / "cache" / "findings_cache.json"
        assert cache_file.exists()

    def test_flush_atomic_no_tmp_orphans(self, tmp_path: Path) -> None:
        """After flush, no .tmp files should be left in cache dir."""
        cache = _make_cache(tmp_path)
        cache.put_findings(_FRAME, "src/app.py", "content", [_make_finding()])
        cache.flush()

        cache_dir = tmp_path / ".warden" / "cache"
        tmp_files = list(cache_dir.glob("*.tmp"))
        assert tmp_files == [], f"Orphan .tmp files found: {tmp_files}"

    def test_flush_idempotent_if_not_dirty(self, tmp_path: Path) -> None:
        """Calling flush() twice without changes should not re-write the file."""
        cache = _make_cache(tmp_path)
        cache.put_findings(_FRAME, "src/app.py", "content", [_make_finding()])
        cache.flush()

        cache_file = tmp_path / ".warden" / "cache" / "findings_cache.json"
        mtime_first = cache_file.stat().st_mtime

        # Second flush -- not dirty, file must not change
        cache.flush()
        mtime_second = cache_file.stat().st_mtime
        assert mtime_first == mtime_second

    def test_reload_after_flush_hits(self, tmp_path: Path) -> None:
        """A flushed cache can be read by a fresh instance."""
        cache1 = _make_cache(tmp_path)
        cache1.put_findings(_FRAME, "src/app.py", "persistent", [_make_finding(id="PERSIST")])
        cache1.flush()

        # New instance loads from disk
        cache2 = _make_cache(tmp_path)
        result = cache2.get_findings(_FRAME, "src/app.py", "persistent")
        assert result is not None
        assert len(result) == 1
        assert result[0].id == "PERSIST"

    def test_reload_preserves_is_blocker(self, tmp_path: Path) -> None:
        """is_blocker=True survives flush -> reload cycle."""
        cache1 = _make_cache(tmp_path)
        cache1.put_findings(_FRAME, "src/app.py", "c", [_make_finding(is_blocker=True)])
        cache1.flush()

        cache2 = _make_cache(tmp_path)
        result = cache2.get_findings(_FRAME, "src/app.py", "c")
        assert result is not None
        assert result[0].is_blocker is True

    def test_corrupt_cache_file_resets_to_empty(self, tmp_path: Path) -> None:
        """A corrupt JSON file should not crash; cache starts empty."""
        cache_dir = tmp_path / ".warden" / "cache"
        cache_dir.mkdir(parents=True)
        (cache_dir / "findings_cache.json").write_text("NOT JSON {{{{")

        cache = _make_cache(tmp_path)
        assert cache.size == 0
        assert cache.get_findings(_FRAME, "src/app.py", "content") is None


# ===========================================================================
# TestFindingsCacheEviction
# ===========================================================================


class TestFindingsCacheEviction:
    """LRU eviction when store exceeds max_entries."""

    def test_lru_evict_when_exceeds_max_entries(self, tmp_path: Path) -> None:
        max_entries = 10
        cache = _make_cache(tmp_path, max_entries=max_entries)

        # Insert 15 entries across different files
        for i in range(15):
            cache.put_findings(_FRAME, f"src/f{i}.py", f"content_{i}", [_make_finding(id=f"F{i:03d}")])

        # After eviction, size must be <= max_entries
        assert cache.size <= max_entries

    def test_eviction_keeps_recent_entries(self, tmp_path: Path) -> None:
        """After LRU eviction, recently inserted entries should still be cached."""
        max_entries = 5
        cache = _make_cache(tmp_path, max_entries=max_entries)

        # Insert old entries with low timestamps
        for i in range(5):
            cache.put_findings(_FRAME, f"src/old{i}.py", f"old_{i}", [])
            # Force old _ts on internal entries
            key = FindingsCache.cache_key(_FRAME, f"src/old{i}.py", f"old_{i}")
            cache._store[key]["_ts"] = time.time() - 10000

        # Insert 2 more recent entries (will trigger eviction)
        cache.put_findings(_FRAME, "src/recent_a.py", "recent_a", [_make_finding(id="RA")])
        cache.put_findings(_FRAME, "src/recent_b.py", "recent_b", [_make_finding(id="RB")])

        # Size capped
        assert cache.size <= max_entries

        # Recent entries should survive
        result_a = cache.get_findings(_FRAME, "src/recent_a.py", "recent_a")
        result_b = cache.get_findings(_FRAME, "src/recent_b.py", "recent_b")
        assert result_a is not None
        assert result_b is not None


# ===========================================================================
# TestFindingsCacheStats
# ===========================================================================


class TestFindingsCacheStats:
    """hit_rate and size properties."""

    def test_hit_rate_zero_on_empty(self, tmp_path: Path) -> None:
        cache = _make_cache(tmp_path)
        assert cache.hit_rate == 0.0

    def test_size_zero_on_empty(self, tmp_path: Path) -> None:
        cache = _make_cache(tmp_path)
        assert cache.size == 0

    def test_hit_rate_after_operations(self, tmp_path: Path) -> None:
        cache = _make_cache(tmp_path)
        cache.put_findings(_FRAME, "src/app.py", "content", [_make_finding()])

        # 1 miss
        cache.get_findings(_FRAME, "src/other.py", "content")
        # 1 hit
        cache.get_findings(_FRAME, "src/app.py", "content")

        # 1 hit out of 2 total = 50%
        assert cache.hit_rate == pytest.approx(0.5)

    def test_size_increases_with_puts(self, tmp_path: Path) -> None:
        cache = _make_cache(tmp_path)
        assert cache.size == 0

        cache.put_findings(_FRAME, "src/a.py", "c1", [])
        assert cache.size == 1

        cache.put_findings(_FRAME, "src/b.py", "c2", [])
        assert cache.size == 2

    def test_put_same_key_does_not_grow_size(self, tmp_path: Path) -> None:
        """Updating the same key should not increase cache size."""
        cache = _make_cache(tmp_path)
        cache.put_findings(_FRAME, "src/a.py", "same", [])
        cache.put_findings(_FRAME, "src/a.py", "same", [_make_finding()])
        assert cache.size == 1

    def test_content_hash_is_deterministic(self) -> None:
        h1 = FindingsCache.content_hash("hello world")
        h2 = FindingsCache.content_hash("hello world")
        assert h1 == h2

    def test_content_hash_differs_for_different_content(self) -> None:
        h1 = FindingsCache.content_hash("hello")
        h2 = FindingsCache.content_hash("world")
        assert h1 != h2

    def test_cache_key_differs_for_different_frames(self) -> None:
        k1 = FindingsCache.cache_key("security", "src/a.py", "content")
        k2 = FindingsCache.cache_key("resilience", "src/a.py", "content")
        assert k1 != k2

    def test_cache_key_differs_for_different_files(self) -> None:
        k1 = FindingsCache.cache_key(_FRAME, "src/a.py", "content")
        k2 = FindingsCache.cache_key(_FRAME, "src/b.py", "content")
        assert k1 != k2
