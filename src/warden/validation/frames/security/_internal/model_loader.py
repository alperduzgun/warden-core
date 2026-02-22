"""
Model Pack Loader — loads built-in YAML taint model packs.

Three-layer architecture:
  Layer 1  models/signals.yaml       — heuristic inference (fallback)
  Layer 2  models/{lang}/*.yaml      — explicit built-in packs
  Layer 3  .warden/taint_catalog.yaml — user override (handled by TaintCatalog.load)

ModelPackLoader handles Layer 2 + signals.yaml (Layer 1).
It is intentionally dependency-light: stdlib only (yaml, pathlib, logging).

If the models/ directory is missing or a YAML file is malformed, the loader
gracefully returns empty dicts — hardcoded constants in taint_analyzer.py then
serve as the baseline guarantee.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_MODELS_DIR = Path(__file__).parent.parent / "models"

# Language directories inside models/
_LANG_DIRS = ("python", "javascript", "go", "java")


class ModelPackLoader:
    """Loads and merges built-in YAML model pack files."""

    MODELS_DIR: Path = _MODELS_DIR

    @classmethod
    def load_all(cls) -> dict[str, Any]:
        """
        Load all model pack YAML files and merge them.

        Returns a dict with structure:
          {
            "sources":      {lang: set[str]},
            "sinks":        {pattern: sink_type},
            "assign_sinks": set[str],
            "sanitizers":   {sink_type: set[str]},
          }

        If the models/ directory does not exist or all files fail, returns
        an empty dict so callers can fall back to hardcoded constants.
        """
        if not cls.MODELS_DIR.is_dir():
            logger.debug("model_pack_dir_missing dir=%s", cls.MODELS_DIR)
            return {}

        result: dict[str, Any] = {
            "sources": {},
            "sinks": {},
            "assign_sinks": set(),
            "sanitizers": {},
        }
        loaded_any = False

        for lang in _LANG_DIRS:
            lang_dir = cls.MODELS_DIR / lang
            if not lang_dir.is_dir():
                continue
            for yaml_file in sorted(lang_dir.glob("*.yaml")):
                data = cls._load_yaml_file(yaml_file)
                if data is None:
                    continue
                cls._merge_pack(result, data, lang)
                loaded_any = True

        return result if loaded_any else {}

    @classmethod
    def load_signals(cls) -> dict[str, Any]:
        """Load signals.yaml for heuristic inference. Returns {} on failure."""
        signals_path = cls.MODELS_DIR / "signals.yaml"
        if not signals_path.exists():
            logger.debug("signals_yaml_missing path=%s", signals_path)
            return {}
        data = cls._load_yaml_file(signals_path)
        return data or {}

    # ── Internal helpers ────────────────────────────────────────────────────

    @classmethod
    def _load_yaml_file(cls, path: Path) -> dict[str, Any] | None:
        """Load a single YAML file. Returns None on failure."""
        try:
            import yaml

            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if not isinstance(data, dict):
                logger.debug("model_pack_invalid_format path=%s", path)
                return None
            return data
        except Exception as exc:
            logger.debug("model_pack_load_failed path=%s error=%s", path, exc)
            return None

    @classmethod
    def _merge_pack(cls, result: dict[str, Any], data: dict[str, Any], lang: str) -> None:
        """Merge a single model pack dict into the aggregated result."""
        # ── Sources ──────────────────────────────────────────────────────────
        for entry in data.get("sources") or []:
            if not isinstance(entry, dict):
                continue
            pattern = entry.get("pattern")
            if isinstance(pattern, str) and pattern.strip():
                result["sources"].setdefault(lang, set()).add(pattern.strip())

        # ── Sinks ────────────────────────────────────────────────────────────
        for entry in data.get("sinks") or []:
            if not isinstance(entry, dict):
                continue
            pattern = entry.get("pattern")
            sink_type = entry.get("type")
            if isinstance(pattern, str) and isinstance(sink_type, str) and pattern.strip():
                result["sinks"][pattern.strip()] = sink_type.strip()
                # Handle assign_sink flag (e.g., innerHTML in browser.yaml)
                if entry.get("assign_sink"):
                    result["assign_sinks"].add(pattern.strip())

        # ── Sanitizers ───────────────────────────────────────────────────────
        for entry in data.get("sanitizers") or []:
            if not isinstance(entry, dict):
                continue
            pattern = entry.get("pattern")
            clears = entry.get("clears")
            if isinstance(pattern, str) and isinstance(clears, str) and pattern.strip():
                result["sanitizers"].setdefault(clears.strip(), set()).add(pattern.strip())
