import json
import os
from pathlib import Path
from typing import Any

from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)


class RegistryClient:
    """
    Client for interacting with the Warden Hub/Registry.
    Uses a local cache synced from a central Git repository.
    """

    def __init__(self, registry_url: str | None = None, hub_dir: Path | None = None):
        # Priority: Constructor -> Env Var -> Config File -> Default
        self.registry_url = registry_url or os.getenv("WARDEN_HUB_URL")

        self.hub_dir = hub_dir or Path.home() / ".warden" / "hub"
        self.catalog_path = self.hub_dir / "registry.json"

        # Load config if URL not set
        if not self.registry_url:
            self.registry_url = self._load_hub_url_from_config() or "https://github.com/Appnova-EU-OU/warden-hub.git"

        # Ensure hub directory exists
        self.hub_dir.mkdir(parents=True, exist_ok=True)

        # Initial data (empty or loaded from cache)
        self._catalog_cache: list[dict[str, Any]] = self._load_catalog()

    def _load_hub_url_from_config(self) -> str | None:
        """Load hub URL from global config."""
        try:
            config_path = Path.home() / ".warden" / "config.yaml"
            if config_path.exists():
                import yaml

                with open(config_path) as f:
                    config = yaml.safe_load(f)
                    return config.get("hub", {}).get("url")
        except Exception as e:
            logger.warning("config_load_failed", error=str(e))
        return None

    def _load_catalog(self) -> list[dict[str, Any]]:
        """Load catalog from local JSON cache."""
        if not self.catalog_path.exists():
            # Return empty list if no catalog exists yet
            # User needs to run `warden update` to populate this
            return []

        try:
            with open(self.catalog_path) as f:
                return json.load(f)
        except Exception as e:
            logger.error("catalog_load_failed", error=str(e))
            return []

    async def sync_async(self) -> bool:
        """Sync catalog from remote Warden Hub repository."""
        import subprocess

        logger.info("syncing_registry_catalog", url=self.registry_url)

        try:
            timeout_seconds = 10  # Fail Fast principle

            if not (self.hub_dir / ".git").exists():
                # Initial clone
                logger.info("registry_clone_started")
                subprocess.run(
                    ["git", "clone", "--depth", "1", self.registry_url, str(self.hub_dir)],
                    check=True,
                    capture_output=True,
                    timeout=timeout_seconds,
                )
            else:
                # Update existing
                logger.debug("registry_pull_started")
                subprocess.run(
                    ["git", "-C", str(self.hub_dir), "pull", "origin", "master"],
                    check=True,
                    capture_output=True,
                    timeout=timeout_seconds,
                )

            # Refresh cache
            self._catalog_cache = self._load_catalog()
            logger.info("registry_sync_success", frames_count=len(self._catalog_cache))
            return True

        except subprocess.TimeoutExpired:
            logger.warning("registry_sync_timeout", timeout=timeout_seconds, action="using_cached_if_available")
            # Degraded mode: If we have cache, return True (ish) or just log
            return bool(self._catalog_cache)

        except Exception as e:
            logger.error("registry_sync_failed", error=str(e), action="using_cached_if_available")
            # Degraded mode: If we have cache, we are 'okay'
            return bool(self._catalog_cache)

    def search(self, query: str | None = None) -> list[dict[str, Any]]:
        """Search for frames matching the query."""
        if not query:
            return self._catalog_cache

        q = query.lower()
        results = []
        for frame in self._catalog_cache:
            if (
                q in frame["name"].lower()
                or q in frame.get("description", "").lower()
                or q in frame.get("category", "").lower()
            ):
                results.append(frame)
        return results

    def get_details(self, frame_id: str) -> dict[str, Any] | None:
        """Get full details for a specific frame."""
        for frame in self._catalog_cache:
            if frame["id"] == frame_id:
                return frame
        return None

    def get_core_frames(self) -> list[dict[str, Any]]:
        """Get all frames marked as 'core'."""
        return [f for f in self._catalog_cache if f.get("tier") == "core"]

    def suggest_for_language(self, language: str) -> list[str]:
        """
        Smart/Dynamic Frame Discovery based on language.
        Returns a list of frame IDs that match the given language.

        Algorithm:
        1. Exact Match: Language is in 'supported_languages' list (Future Proof).
        2. Heuristic: Language name appears in ID (e.g. 'python_lint' contains 'python').
        3. Heuristic: Language name appears in Category.
        """
        if not language:
            return []

        lang = language.lower()
        suggestions = []

        for frame in self._catalog_cache:
            # Future Proof: If schema supports explicit tags
            if lang in frame.get("supported_languages", []):
                suggestions.append(frame["id"])
                continue

            # Heuristic 1: ID contains lang (e.g. python_lint)
            # We look for word boundaries ideally, but containment is good for MVP
            # 'python' in 'python_lint' -> True
            # 'go' in 'algo_frame' -> True (False Positive Risk).
            # Mitigation: Check explicit start or separator
            fid = frame["id"].lower()
            if fid.startswith(f"{lang}_") or f"_{lang}" in fid:
                suggestions.append(frame["id"])
                continue

            # Heuristic 2: Name contains lang
            fname = frame["name"].lower()
            if f" {lang} " in f" {fname} ":  # Boundary check
                suggestions.append(frame["id"])
                continue

            # Heuristic 3: Check description for "For Python" etc.
            # Keeping it strict for now to avoid noise.

        return list(set(suggestions))  # Unique
