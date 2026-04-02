"""Unit tests for ProjectProfileCache — persist project profile across scans.

Tests cover:
- Cache miss when file is absent
- Cache miss when TTL is expired
- Cache hit when file is fresh
- Save/load round-trip
- Invalidation (file deletion)
- Robustness (corrupt JSON, missing created_at, permission errors)
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from warden.analysis.application.project_profile_cache import (
    CACHE_FILE,
    TTL_HOURS,
    ProjectProfileCache,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_project(tmp_path: Path) -> Path:
    """Return a temporary project root with the warden cache dir pre-created."""
    cache_dir = tmp_path / ".warden" / "cache"
    cache_dir.mkdir(parents=True)
    return tmp_path


def _write_cache(project_root: Path, data: dict) -> None:
    """Write raw JSON to the cache file."""
    cache_path = project_root / CACHE_FILE
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "w") as fh:
        json.dump(data, fh)


def _fresh_profile(**overrides) -> dict:
    """Build a profile dict with a current timestamp."""
    base = {
        "project_type": "backend",
        "framework": "fastapi",
        "languages": ["python"],
        "file_count": 42,
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# load()
# ---------------------------------------------------------------------------

class TestLoad:
    def test_returns_none_when_file_missing(self, tmp_project: Path):
        cache = ProjectProfileCache()
        assert cache.load(tmp_project) is None

    def test_returns_none_when_file_is_corrupt_json(self, tmp_project: Path):
        cache_path = tmp_project / CACHE_FILE
        cache_path.write_text("NOT_JSON{{{")
        cache = ProjectProfileCache()
        assert cache.load(tmp_project) is None

    def test_returns_none_when_created_at_missing(self, tmp_project: Path):
        _write_cache(tmp_project, {"project_type": "backend"})
        cache = ProjectProfileCache()
        assert cache.load(tmp_project) is None

    def test_returns_none_when_created_at_is_invalid(self, tmp_project: Path):
        _write_cache(tmp_project, {"project_type": "backend", "created_at": "not-a-date"})
        cache = ProjectProfileCache()
        assert cache.load(tmp_project) is None

    def test_returns_none_when_cache_expired(self, tmp_project: Path):
        expired_time = datetime.now(tz=timezone.utc) - timedelta(hours=TTL_HOURS + 1)
        _write_cache(tmp_project, _fresh_profile(created_at=expired_time.isoformat()))
        cache = ProjectProfileCache()
        assert cache.load(tmp_project) is None

    def test_returns_profile_when_within_ttl(self, tmp_project: Path):
        _write_cache(tmp_project, _fresh_profile())
        cache = ProjectProfileCache()
        result = cache.load(tmp_project)
        assert result is not None
        assert result["project_type"] == "backend"
        assert result["framework"] == "fastapi"

    def test_returns_none_at_exact_ttl_boundary(self, tmp_project: Path):
        """A profile created exactly TTL_HOURS ago is considered expired (age >= TTL)."""
        exact_boundary = datetime.now(tz=timezone.utc) - timedelta(hours=TTL_HOURS)
        _write_cache(tmp_project, _fresh_profile(created_at=exact_boundary.isoformat()))
        cache = ProjectProfileCache()
        # Exactly at boundary: age_hours == TTL_HOURS which is >= TTL_HOURS → cache miss
        result = cache.load(tmp_project)
        assert result is None

    def test_returns_profile_just_before_expiry(self, tmp_project: Path):
        near_expiry = datetime.now(tz=timezone.utc) - timedelta(hours=TTL_HOURS - 0.5)
        _write_cache(tmp_project, _fresh_profile(created_at=near_expiry.isoformat()))
        cache = ProjectProfileCache()
        assert cache.load(tmp_project) is not None

    def test_naive_timestamp_treated_as_utc(self, tmp_project: Path):
        """Naive timestamps (no tzinfo) should be accepted without crashing."""
        naive_time = datetime.now().isoformat()  # no tzinfo
        _write_cache(tmp_project, _fresh_profile(created_at=naive_time))
        cache = ProjectProfileCache()
        # Should not raise; result depends on system time but must not be None
        # unless somehow expired, which it won't be for a fresh naive timestamp
        result = cache.load(tmp_project)
        assert result is not None


# ---------------------------------------------------------------------------
# save()
# ---------------------------------------------------------------------------

class TestSave:
    def test_creates_cache_file(self, tmp_project: Path):
        cache = ProjectProfileCache()
        cache.save(tmp_project, {
            "project_type": "web",
            "framework": "react",
            "languages": ["javascript"],
            "file_count": 100,
        })
        cache_path = tmp_project / CACHE_FILE
        assert cache_path.exists()

    def test_written_json_is_valid(self, tmp_project: Path):
        cache = ProjectProfileCache()
        cache.save(tmp_project, {
            "project_type": "web",
            "framework": "react",
            "languages": ["javascript"],
            "file_count": 100,
        })
        cache_path = tmp_project / CACHE_FILE
        with open(cache_path) as fh:
            data = json.load(fh)
        assert data["project_type"] == "web"
        assert data["framework"] == "react"
        assert data["languages"] == ["javascript"]
        assert data["file_count"] == 100
        assert "created_at" in data

    def test_created_at_is_recent_utc(self, tmp_project: Path):
        before = datetime.now(tz=timezone.utc)
        cache = ProjectProfileCache()
        cache.save(tmp_project, {
            "project_type": "backend",
            "framework": "django",
            "languages": ["python"],
            "file_count": 30,
        })
        after = datetime.now(tz=timezone.utc)

        cache_path = tmp_project / CACHE_FILE
        with open(cache_path) as fh:
            data = json.load(fh)

        created_at = datetime.fromisoformat(data["created_at"])
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

        assert before <= created_at <= after

    def test_save_creates_missing_parent_dirs(self, tmp_path: Path):
        """save() should create .warden/cache/ if it doesn't exist."""
        cache = ProjectProfileCache()
        cache.save(tmp_path, {
            "project_type": "mobile",
            "framework": "flutter",
            "languages": ["dart"],
            "file_count": 55,
        })
        assert (tmp_path / CACHE_FILE).exists()

    def test_save_uses_defaults_for_missing_keys(self, tmp_project: Path):
        cache = ProjectProfileCache()
        cache.save(tmp_project, {})  # empty profile
        with open(tmp_project / CACHE_FILE) as fh:
            data = json.load(fh)
        assert data["project_type"] == "unknown"
        assert data["framework"] == "none"
        assert data["languages"] == []
        assert data["file_count"] == 0


# ---------------------------------------------------------------------------
# Round-trip: save then load
# ---------------------------------------------------------------------------

class TestRoundTrip:
    def test_save_then_load_returns_same_profile(self, tmp_project: Path):
        cache = ProjectProfileCache()
        profile = {
            "project_type": "backend",
            "framework": "fastapi",
            "languages": ["python", "sql"],
            "file_count": 78,
        }
        cache.save(tmp_project, profile)
        loaded = cache.load(tmp_project)

        assert loaded is not None
        assert loaded["project_type"] == profile["project_type"]
        assert loaded["framework"] == profile["framework"]
        assert loaded["languages"] == profile["languages"]
        assert loaded["file_count"] == profile["file_count"]

    def test_multiple_saves_overwrite_previous(self, tmp_project: Path):
        cache = ProjectProfileCache()
        cache.save(tmp_project, {"project_type": "web", "framework": "react"})
        cache.save(tmp_project, {"project_type": "backend", "framework": "fastapi"})

        loaded = cache.load(tmp_project)
        assert loaded is not None
        assert loaded["project_type"] == "backend"
        assert loaded["framework"] == "fastapi"


# ---------------------------------------------------------------------------
# invalidate()
# ---------------------------------------------------------------------------

class TestInvalidate:
    def test_deletes_existing_cache_file(self, tmp_project: Path):
        _write_cache(tmp_project, _fresh_profile())
        cache = ProjectProfileCache()
        cache.invalidate(tmp_project)
        assert not (tmp_project / CACHE_FILE).exists()

    def test_no_error_when_file_missing(self, tmp_project: Path):
        """Calling invalidate when there is no cache should be a silent no-op."""
        cache = ProjectProfileCache()
        cache.invalidate(tmp_project)  # should not raise

    def test_load_returns_none_after_invalidation(self, tmp_project: Path):
        cache = ProjectProfileCache()
        cache.save(tmp_project, _fresh_profile())
        cache.invalidate(tmp_project)
        assert cache.load(tmp_project) is None


# ---------------------------------------------------------------------------
# Edge cases / robustness
# ---------------------------------------------------------------------------

class TestRobustness:
    def test_load_swallows_os_error(self, tmp_project: Path, monkeypatch):
        """load() should return None instead of raising on unexpected OS errors."""
        _write_cache(tmp_project, _fresh_profile())
        cache = ProjectProfileCache()

        # Patch Path.exists to return True but json.load to raise
        import json as _json
        monkeypatch.setattr(_json, "load", lambda *a, **kw: (_ for _ in ()).throw(OSError("permission denied")))
        result = cache.load(tmp_project)
        assert result is None

    def test_save_swallows_os_error(self, tmp_project: Path, monkeypatch):
        """save() should not raise even if writing fails."""
        cache = ProjectProfileCache()

        import builtins
        real_open = builtins.open

        def _bad_open(path, mode="r", *args, **kwargs):
            if "w" in mode and CACHE_FILE.replace("/", "") in str(path):
                raise OSError("disk full")
            return real_open(path, mode, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", _bad_open)
        cache.save(tmp_project, {"project_type": "backend"})  # should not raise
