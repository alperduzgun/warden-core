"""Tests for the thread-safe LRU cache used by PipelineContext.ast_cache."""

import threading

import pytest

from warden.pipeline.domain.lru_cache import LRUCache


class TestLRUCacheBasicOperations:
    """Core dict-like behaviour."""

    def test_set_and_get(self):
        cache = LRUCache(maxsize=10)
        cache["a"] = 1
        assert cache["a"] == 1

    def test_get_missing_key_raises(self):
        cache = LRUCache(maxsize=10)
        with pytest.raises(KeyError):
            _ = cache["missing"]

    def test_get_default(self):
        cache = LRUCache(maxsize=10)
        assert cache.get("missing") is None
        assert cache.get("missing", 42) == 42

    def test_contains(self):
        cache = LRUCache(maxsize=10)
        cache["x"] = 1
        assert "x" in cache
        assert "y" not in cache

    def test_delete(self):
        cache = LRUCache(maxsize=10)
        cache["a"] = 1
        del cache["a"]
        assert "a" not in cache

    def test_delete_missing_raises(self):
        cache = LRUCache(maxsize=10)
        with pytest.raises(KeyError):
            del cache["nope"]

    def test_len(self):
        cache = LRUCache(maxsize=10)
        assert len(cache) == 0
        cache["a"] = 1
        cache["b"] = 2
        assert len(cache) == 2

    def test_bool(self):
        cache = LRUCache(maxsize=10)
        assert not cache
        cache["a"] = 1
        assert cache

    def test_clear(self):
        cache = LRUCache(maxsize=10)
        cache["a"] = 1
        cache["b"] = 2
        cache.clear()
        assert len(cache) == 0
        assert "a" not in cache

    def test_iter_keys(self):
        cache = LRUCache(maxsize=10)
        cache["a"] = 1
        cache["b"] = 2
        assert set(cache) == {"a", "b"}

    def test_keys_values_items(self):
        cache = LRUCache(maxsize=10)
        cache["x"] = 10
        cache["y"] = 20
        assert set(cache.keys()) == {"x", "y"}
        assert set(cache.values()) == {10, 20}
        assert set(cache.items()) == {("x", 10), ("y", 20)}

    def test_overwrite_existing_key(self):
        cache = LRUCache(maxsize=10)
        cache["a"] = 1
        cache["a"] = 2
        assert cache["a"] == 2
        assert len(cache) == 1

    def test_maxsize_property(self):
        cache = LRUCache(maxsize=42)
        assert cache.maxsize == 42

    def test_repr(self):
        cache = LRUCache(maxsize=5)
        cache["a"] = 1
        r = repr(cache)
        assert "LRUCache" in r
        assert "maxsize=5" in r
        assert "len=1" in r


class TestLRUCacheEviction:
    """LRU eviction policy."""

    def test_evicts_lru_on_overflow(self):
        cache = LRUCache(maxsize=3)
        cache["a"] = 1
        cache["b"] = 2
        cache["c"] = 3
        # Cache full: a(LRU), b, c(MRU)
        cache["d"] = 4  # Should evict "a"
        assert "a" not in cache
        assert len(cache) == 3
        assert set(cache.keys()) == {"b", "c", "d"}

    def test_read_promotes_entry(self):
        """Accessing a key makes it MRU, so it survives eviction."""
        cache = LRUCache(maxsize=3)
        cache["a"] = 1
        cache["b"] = 2
        cache["c"] = 3
        # Access "a" to make it MRU
        _ = cache["a"]
        # Now order is: b(LRU), c, a(MRU)
        cache["d"] = 4  # Should evict "b" (not "a")
        assert "a" in cache
        assert "b" not in cache

    def test_get_promotes_entry(self):
        """cache.get() also promotes."""
        cache = LRUCache(maxsize=3)
        cache["a"] = 1
        cache["b"] = 2
        cache["c"] = 3
        cache.get("a")
        cache["d"] = 4
        assert "a" in cache
        assert "b" not in cache

    def test_contains_promotes_entry(self):
        """'in' operator promotes the entry."""
        cache = LRUCache(maxsize=3)
        cache["a"] = 1
        cache["b"] = 2
        cache["c"] = 3
        _ = "a" in cache  # promote a
        cache["d"] = 4
        assert "a" in cache
        assert "b" not in cache

    def test_overwrite_promotes_entry(self):
        """Overwriting an existing key promotes it to MRU."""
        cache = LRUCache(maxsize=3)
        cache["a"] = 1
        cache["b"] = 2
        cache["c"] = 3
        cache["a"] = 99  # overwrite + promote
        cache["d"] = 4  # evicts "b"
        assert "a" in cache
        assert cache["a"] == 99
        assert "b" not in cache

    def test_maxsize_one(self):
        """Edge case: cache with maxsize=1."""
        cache = LRUCache(maxsize=1)
        cache["a"] = 1
        assert len(cache) == 1
        cache["b"] = 2  # evicts "a"
        assert "a" not in cache
        assert cache["b"] == 2

    def test_sequential_evictions(self):
        """Insert N items into size-3 cache; only last 3 survive."""
        cache = LRUCache(maxsize=3)
        for i in range(100):
            cache[f"k{i}"] = i
        assert len(cache) == 3
        # Last 3 should be k97, k98, k99
        assert "k99" in cache
        assert "k98" in cache
        assert "k97" in cache
        assert "k0" not in cache


class TestLRUCacheValidation:
    """Input validation."""

    def test_maxsize_zero_raises(self):
        with pytest.raises(ValueError, match="maxsize must be >= 1"):
            LRUCache(maxsize=0)

    def test_maxsize_negative_raises(self):
        with pytest.raises(ValueError, match="maxsize must be >= 1"):
            LRUCache(maxsize=-5)


class TestLRUCacheThreadSafety:
    """Concurrent access does not corrupt the cache."""

    def test_concurrent_writes(self):
        cache = LRUCache(maxsize=50)
        errors = []

        def writer(start: int):
            try:
                for i in range(100):
                    cache[f"t{start}-{i}"] = i
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(cache) <= 50

    def test_concurrent_reads_and_writes(self):
        cache = LRUCache(maxsize=100)
        # Pre-populate
        for i in range(100):
            cache[f"k{i}"] = i

        errors = []

        def reader():
            try:
                for i in range(100):
                    cache.get(f"k{i}")
            except Exception as exc:
                errors.append(exc)

        def writer():
            try:
                for i in range(100, 200):
                    cache[f"k{i}"] = i
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=reader) for _ in range(5)]
        threads += [threading.Thread(target=writer) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(cache) <= 100


class TestPipelineContextASTCacheIsLRU:
    """Verify PipelineContext.ast_cache is an LRUCache instance."""

    def test_default_ast_cache_is_lru(self):
        from datetime import datetime
        from pathlib import Path

        from warden.pipeline.domain.pipeline_context import (
            DEFAULT_MAX_AST_CACHE_ENTRIES,
            PipelineContext,
        )

        ctx = PipelineContext(
            pipeline_id="test",
            started_at=datetime.now(),
            file_path=Path("/tmp/test"),
            source_code="",
        )
        assert isinstance(ctx.ast_cache, LRUCache)
        assert ctx.ast_cache.maxsize == DEFAULT_MAX_AST_CACHE_ENTRIES

    def test_custom_ast_cache_size(self):
        from datetime import datetime
        from pathlib import Path

        from warden.pipeline.domain.pipeline_context import PipelineContext

        ctx = PipelineContext(
            pipeline_id="test",
            started_at=datetime.now(),
            file_path=Path("/tmp/test"),
            source_code="",
            max_ast_cache_entries=42,
        )
        assert ctx.ast_cache.maxsize == 42

    def test_ast_cache_dict_like_usage(self):
        """Existing code that uses dict-like access still works."""
        from datetime import datetime
        from pathlib import Path

        from warden.pipeline.domain.pipeline_context import PipelineContext

        ctx = PipelineContext(
            pipeline_id="test",
            started_at=datetime.now(),
            file_path=Path("/tmp/test"),
            source_code="",
            max_ast_cache_entries=3,
        )
        ctx.ast_cache["file1.py"] = "ast1"
        ctx.ast_cache["file2.py"] = "ast2"
        assert ctx.ast_cache.get("file1.py") == "ast1"
        assert "file2.py" in ctx.ast_cache
        assert len(ctx.ast_cache) == 2
