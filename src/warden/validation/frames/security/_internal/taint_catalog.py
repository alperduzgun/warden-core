"""
Taint Catalog — default + user-extensible sources/sinks/sanitizers.

The default catalog is built from the hardcoded constants in taint_analyzer.py.
Users can extend (never replace) it via .warden/taint_catalog.yaml.

YAML format (.warden/taint_catalog.yaml):
    sources:
      python:
        - fastapi.Request.query_params
      javascript:
        - ctx.request.body

    sinks:
      SQL-value:
        - prisma.query

    sanitizers:
      HTML-content:
        - yourCustomSanitizer

User entries are UNIONed with built-in defaults — defaults are never replaced.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_CATALOG_FILENAME = "taint_catalog.yaml"
_WARDEN_DIR = ".warden"


@dataclass
class TaintCatalog:
    """
    Taint analysis catalog: sources, sinks, sanitizers.

    sources:      lang → set of source patterns
                  {"python": {"request.args", ...}, "javascript": {"req.body", ...}}
    sinks:        sink_name → sink_type (Python + JS combined)
                  {"cursor.execute": "SQL-value", "eval": "CODE-execution", ...}
    assign_sinks: JS DOM property assignment sinks (innerHTML, outerHTML)
    sanitizers:   sink_type → set of sanitizer functions
                  {"SQL-value": {"parameterized_query", ...}, ...}
    """

    sources: dict[str, set[str]] = field(default_factory=dict)
    sinks: dict[str, str] = field(default_factory=dict)
    assign_sinks: set[str] = field(default_factory=set)
    sanitizers: dict[str, set[str]] = field(default_factory=dict)

    @classmethod
    def get_default(cls) -> TaintCatalog:
        """
        Build a TaintCatalog from hardcoded constants + built-in YAML model packs.

        Load order:
          1. Hardcoded constants (taint_analyzer.py) — always included as baseline
          2. YAML model packs (models/{lang}/*.yaml) — unioned on top

        If the models/ directory is missing or all files fail to load, only the
        hardcoded constants are used (unchanged backward-compatible behaviour).
        """
        # Late import to avoid circular dependency at module level
        from warden.validation.frames.security._internal.taint_analyzer import (  # noqa: PLC0415
            JS_SANITIZERS,
            JS_TAINT_SINKS,
            JS_TAINT_SOURCES,
            KNOWN_SANITIZERS,
            TAINT_SINKS,
            TAINT_SOURCES,
            _JS_ASSIGN_SINKS,
        )

        # ── Baseline from hardcoded constants ─────────────────────────────────
        combined_sinks: dict[str, str] = {}
        combined_sinks.update(TAINT_SINKS)
        combined_sinks.update(JS_TAINT_SINKS)

        combined_sanitizers: dict[str, set[str]] = {}
        for sink_type, sans in KNOWN_SANITIZERS.items():
            combined_sanitizers.setdefault(sink_type, set()).update(sans)
        for sink_type, sans in JS_SANITIZERS.items():
            combined_sanitizers.setdefault(sink_type, set()).update(sans)

        combined_sources: dict[str, set[str]] = {
            "python": set(TAINT_SOURCES),
            "javascript": set(JS_TAINT_SOURCES),
        }
        combined_assign_sinks: set[str] = set(_JS_ASSIGN_SINKS)

        # ── Union with YAML model packs ───────────────────────────────────────
        try:
            from warden.validation.frames.security._internal.model_loader import (  # noqa: PLC0415
                ModelPackLoader,
            )

            pack = ModelPackLoader.load_all()
            if pack:
                # Sources: merge per language
                for lang, patterns in (pack.get("sources") or {}).items():
                    combined_sources.setdefault(lang, set()).update(patterns)

                # Sinks: model pack entries added (constants take precedence via update order)
                for pattern, sink_type in (pack.get("sinks") or {}).items():
                    combined_sinks.setdefault(pattern, sink_type)

                # Assign sinks
                combined_assign_sinks.update(pack.get("assign_sinks") or set())

                # Sanitizers: merge per sink_type
                for sink_type, sans in (pack.get("sanitizers") or {}).items():
                    combined_sanitizers.setdefault(sink_type, set()).update(sans)

        except Exception as exc:
            logger.warning("model_pack_load_error error=%s", exc)

        return cls(
            sources=combined_sources,
            sinks=combined_sinks,
            assign_sinks=combined_assign_sinks,
            sanitizers=combined_sanitizers,
        )

    @classmethod
    def load(cls, project_root: Path) -> TaintCatalog:
        """
        Load .warden/taint_catalog.yaml and UNION with defaults.

        If the file does not exist, is empty, or is malformed, the default
        catalog is returned unchanged.

        User entries are always unioned with built-in defaults — defaults
        are never replaced or removed.
        """
        catalog = cls.get_default()
        catalog_path = project_root / _WARDEN_DIR / _CATALOG_FILENAME

        if not catalog_path.exists():
            return catalog

        try:
            import yaml  # noqa: PLC0415

            with open(catalog_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)

            if not isinstance(data, dict):
                logger.warning("taint_catalog_invalid_format path=%s", str(catalog_path))
                return catalog

            cls._apply_user_data(catalog, data)

        except Exception as exc:
            logger.warning("taint_catalog_load_failed path=%s error=%s", str(catalog_path), str(exc))

        return catalog

    @classmethod
    def _apply_user_data(cls, catalog: TaintCatalog, data: dict[str, Any]) -> None:
        """Apply user-defined YAML data into catalog (union, never replace)."""
        # ── Sources ──────────────────────────────────────────────────────────
        # Format: sources: {lang: [entry, ...]}
        user_sources = data.get("sources") or {}
        if isinstance(user_sources, dict):
            for lang, entries in user_sources.items():
                if isinstance(entries, list):
                    catalog.sources.setdefault(lang, set()).update(
                        e for e in entries if isinstance(e, str) and e.strip()
                    )

        # ── Sinks ────────────────────────────────────────────────────────────
        # Format: sinks: {sink_type: [sink_name, ...]}
        # Each sink_name gets mapped to its sink_type in the combined dict.
        user_sinks = data.get("sinks") or {}
        if isinstance(user_sinks, dict):
            for sink_type, entries in user_sinks.items():
                if isinstance(entries, list):
                    for sink_name in entries:
                        if isinstance(sink_name, str) and sink_name.strip():
                            catalog.sinks[sink_name] = sink_type

        # ── Sanitizers ───────────────────────────────────────────────────────
        # Format: sanitizers: {sink_type: [sanitizer_func, ...]}
        user_sanitizers = data.get("sanitizers") or {}
        if isinstance(user_sanitizers, dict):
            for sink_type, entries in user_sanitizers.items():
                if isinstance(entries, list):
                    catalog.sanitizers.setdefault(sink_type, set()).update(
                        e for e in entries if isinstance(e, str) and e.strip()
                    )
