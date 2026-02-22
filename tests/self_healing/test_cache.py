"""Tests for HealingCache."""

from __future__ import annotations

import json
import os
import time
from unittest.mock import patch

import pytest

from warden.self_healing.cache import HealingCache, TTL_SECONDS
from warden.self_healing.models import HealingRecord


@pytest.fixture
def cache_dir(tmp_path):
    warden_dir = tmp_path / ".warden" / "cache"
    warden_dir.mkdir(parents=True)
    return tmp_path


class TestHealingCache:
    def test_put_and_get(self, cache_dir):
        cache = HealingCache(cache_dir)
        record = HealingRecord(
            error_key="abc123",
            error_category="import_error",
            strategy_used="import_healer",
            fixed=True,
            action_taken="pip_install:tiktoken",
        )
        cache.put(record)
        result = cache.get("abc123")
        assert result is not None
        assert result.fixed is True
        assert result.strategy_used == "import_healer"

    def test_get_miss_returns_none(self, cache_dir):
        cache = HealingCache(cache_dir)
        assert cache.get("nonexistent") is None

    def test_ttl_expiry(self, cache_dir):
        cache = HealingCache(cache_dir)
        record = HealingRecord(
            error_key="old_key",
            error_category="unknown",
            strategy_used="llm_healer",
            fixed=False,
            action_taken="diagnosis_only",
            timestamp=time.time() - TTL_SECONDS - 1,
        )
        cache._store["old_key"] = record.to_dict()
        assert cache.get("old_key") is None

    def test_flush_and_reload(self, cache_dir):
        cache = HealingCache(cache_dir)
        record = HealingRecord(
            error_key="persist_key",
            error_category="import_error",
            strategy_used="import_healer",
            fixed=True,
            action_taken="pip_install:pyyaml",
        )
        cache.put(record)
        cache.flush()

        # Create new cache instance → should load from disk
        cache2 = HealingCache(cache_dir)
        result = cache2.get("persist_key")
        assert result is not None
        assert result.fixed is True

    def test_eviction_when_full(self, cache_dir):
        cache = HealingCache(cache_dir, max_entries=5)
        for i in range(10):
            record = HealingRecord(
                error_key=f"key_{i}",
                error_category="unknown",
                strategy_used="test",
                fixed=False,
                action_taken="none",
                timestamp=time.time() - (10 - i),  # older entries first
            )
            cache.put(record)

        assert cache.size <= 5

    def test_clear(self, cache_dir):
        cache = HealingCache(cache_dir)
        cache.put(
            HealingRecord(
                error_key="k",
                error_category="unknown",
                strategy_used="t",
                fixed=False,
                action_taken="n",
            )
        )
        cache.clear()
        assert cache.size == 0

    def test_corrupt_entry_evicted(self, cache_dir):
        cache = HealingCache(cache_dir)
        cache._store["bad"] = {"corrupt": "data"}
        assert cache.get("bad") is None
        assert "bad" not in cache._store

    def test_flush_creates_directory(self, tmp_path):
        root = tmp_path / "new_project"
        cache = HealingCache(root)
        cache.put(
            HealingRecord(
                error_key="x",
                error_category="unknown",
                strategy_used="t",
                fixed=False,
                action_taken="n",
            )
        )
        cache.flush()
        assert (root / ".warden" / "cache" / "healing_cache.json").exists()

    def test_load_handles_corrupt_file(self, cache_dir):
        cache_file = cache_dir / ".warden" / "cache" / "healing_cache.json"
        cache_file.write_text("not valid json!!!", encoding="utf-8")
        cache = HealingCache(cache_dir)
        assert cache.size == 0

    def test_cache_atomic_write_survives_crash(self, cache_dir):
        """If os.replace fails, the original cache file should remain intact."""
        cache = HealingCache(cache_dir)
        record = HealingRecord(
            error_key="survive",
            error_category="import_error",
            strategy_used="import_healer",
            fixed=True,
            action_taken="pip_install:pkg",
        )
        cache.put(record)
        cache.flush()

        # Now add another record but make os.replace fail
        cache.put(
            HealingRecord(
                error_key="crash",
                error_category="unknown",
                strategy_used="test",
                fixed=False,
                action_taken="none",
            )
        )

        with patch("os.replace", side_effect=OSError("disk full")):
            cache.flush()  # Should not raise, just log

        # Reload from disk — should still have the first record intact
        cache2 = HealingCache(cache_dir)
        assert cache2.get("survive") is not None

    def test_cache_corrupt_json_auto_cleanup(self, cache_dir):
        """Corrupt JSON file is deleted on load, next flush writes clean data."""
        cache_file = cache_dir / ".warden" / "cache" / "healing_cache.json"
        cache_file.write_text("{corrupt: not json!}", encoding="utf-8")

        cache = HealingCache(cache_dir)
        assert cache.size == 0
        # Corrupt file should have been removed
        assert not cache_file.exists()

    def test_cache_missing_timestamp_treated_as_expired(self, cache_dir):
        """An entry without a timestamp field is treated as expired."""
        cache = HealingCache(cache_dir)
        cache._store["no_ts"] = {
            "error_key": "no_ts",
            "error_category": "unknown",
            "strategy_used": "test",
            "fixed": False,
            "action_taken": "none",
            # no "timestamp" key → defaults to 0 → always expired
        }
        assert cache.get("no_ts") is None

    def test_healing_record_from_dict_string_false(self, cache_dir):
        """String 'false' should deserialize to fixed=False, not True."""
        cache = HealingCache(cache_dir)
        cache._store["str_bool"] = {
            "error_key": "str_bool",
            "error_category": "unknown",
            "strategy_used": "test",
            "fixed": "false",
            "action_taken": "none",
            "timestamp": time.time(),
        }
        result = cache.get("str_bool")
        assert result is not None
        assert result.fixed is False
