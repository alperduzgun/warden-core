"""Project profile cache — persist pre-analysis results across scans.

The pre-analysis phase (project type detection, framework detection, file
discovery metadata) is expensive. This module caches its output to
``.warden/cache/project_profile.json`` and reuses it across scans as long
as the cache is younger than TTL_HOURS.

Usage pattern (inside pre_analysis_phase.py)::

    cache = ProjectProfileCache()
    profile = cache.load(project_root)
    if profile:
        logger.info("project_profile_cache_hit")
        # use profile["project_type"], profile["framework"], etc.
    else:
        # run detection …
        cache.save(project_root, {
            "project_type": ...,
            "framework": ...,
            "languages": [...],
            "file_count": ...,
        })
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)

# Path relative to project root
CACHE_FILE = ".warden/cache/project_profile.json"

# Cache time-to-live
TTL_HOURS: int = 24


class ProjectProfileCache:
    """Read/write the project profile cache stored next to other warden caches.

    The cache file stores these fields:
    - ``project_type``: detected project type string (e.g. ``"backend"``)
    - ``framework``:    detected framework string (e.g. ``"fastapi"``)
    - ``languages``:    list of detected language strings
    - ``file_count``:   number of files in the project at scan time
    - ``created_at``:   ISO-8601 UTC timestamp written at save time

    All public methods swallow exceptions and return ``None`` / skip silently
    so a cache failure never breaks a scan.
    """

    def load(self, project_root: Path) -> dict[str, Any] | None:
        """Load the project profile cache if it exists and is within TTL.

        Args:
            project_root: Absolute path to the project root directory.

        Returns:
            Cached profile dict if valid (non-expired), otherwise ``None``.
        """
        cache_path = Path(project_root) / CACHE_FILE
        if not cache_path.exists():
            logger.debug("project_profile_cache_miss", reason="file_not_found", path=str(cache_path))
            return None

        try:
            with open(cache_path, encoding="utf-8") as fh:
                data: dict[str, Any] = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("project_profile_cache_load_error", error=str(exc))
            return None

        created_at_str = data.get("created_at")
        if not created_at_str:
            logger.debug("project_profile_cache_miss", reason="missing_created_at")
            return None

        try:
            created_at = datetime.fromisoformat(created_at_str)
            # Ensure timezone-aware comparison
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            now = datetime.now(tz=timezone.utc)
            age_hours = (now - created_at).total_seconds() / 3600.0
        except (ValueError, TypeError) as exc:
            logger.warning("project_profile_cache_timestamp_error", error=str(exc))
            return None

        if age_hours >= TTL_HOURS:
            logger.info(
                "project_profile_cache_miss",
                reason="expired",
                age_hours=round(age_hours, 2),
                ttl_hours=TTL_HOURS,
            )
            return None

        logger.info(
            "project_profile_cache_hit",
            age_hours=round(age_hours, 2),
            project_type=data.get("project_type"),
            framework=data.get("framework"),
        )
        return data

    def save(self, project_root: Path, profile: dict[str, Any]) -> None:
        """Persist profile to the cache file with a current UTC timestamp.

        Args:
            project_root: Absolute path to the project root directory.
            profile: Dict containing ``project_type``, ``framework``,
                     ``languages``, and ``file_count``.  A ``created_at``
                     key will be added or overwritten with the current time.
        """
        cache_path = Path(project_root) / CACHE_FILE

        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning("project_profile_cache_dir_error", error=str(exc))
            return

        payload: dict[str, Any] = {
            "project_type": profile.get("project_type", "unknown"),
            "framework": profile.get("framework", "none"),
            "languages": profile.get("languages", []),
            "file_count": profile.get("file_count", 0),
            "created_at": datetime.now(tz=timezone.utc).isoformat(),
        }

        try:
            with open(cache_path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2)
            logger.info(
                "project_profile_cache_saved",
                project_type=payload["project_type"],
                framework=payload["framework"],
                file_count=payload["file_count"],
            )
        except OSError as exc:
            logger.warning("project_profile_cache_save_error", error=str(exc))

    def invalidate(self, project_root: Path) -> None:
        """Delete the cache file for the given project root.

        Safe to call even if no cache exists (no-op in that case).

        Args:
            project_root: Absolute path to the project root directory.
        """
        cache_path = Path(project_root) / CACHE_FILE
        try:
            cache_path.unlink(missing_ok=True)
            logger.info("project_profile_cache_invalidated", path=str(cache_path))
        except OSError as exc:
            logger.warning("project_profile_cache_invalidate_error", error=str(exc))
