"""
Signal-based Heuristic Inference Engine.

Used as a fallback when an explicit model pack does not match.
Analyzes method/type names and module hints from signals.yaml to infer
whether an expression is a taint source or sink.

Confidence hierarchy:
  Explicit model pack:   0.99 (flask.yaml, django.yaml, etc.)
  Hardcoded constants:   0.90 (TAINT_SOURCES / TAINT_SINKS in taint_analyzer.py)
  Signal inference:      0.60–0.70 (this module, heuristic)

Only used in the Python AST path (_identify_sink / _identify_source in
TaintAnalyzer). JS/Go/Java regex paths use explicit catalog entries.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_CONFIDENCE_BASE_SOURCE = 0.65
_CONFIDENCE_BASE_SINK = 0.60
_CONFIDENCE_BOOST_PARAM = 0.10  # Also used for module boost (same default)
_CONFIDENCE_MAX = 0.90


class SignalInferenceEngine:
    """
    Heuristic inference engine backed by signals.yaml data.

    Args:
        signals_data: Dict loaded from signals.yaml by ModelPackLoader.
                      If None or empty, the engine reports as unavailable.
    """

    def __init__(self, signals_data: dict[str, Any] | None = None, config: dict[str, Any] | None = None) -> None:
        self._sources: list[dict[str, Any]] = []
        self._sinks: list[dict[str, Any]] = []

        # Configurable thresholds (override module-level defaults via config)
        cfg = config or {}
        self._base_source: float = cfg.get("signal_base_source", _CONFIDENCE_BASE_SOURCE)
        self._base_sink: float = cfg.get("signal_base_sink", _CONFIDENCE_BASE_SINK)
        self._boost: float = cfg.get("signal_boost", _CONFIDENCE_BOOST_PARAM)
        self._max: float = cfg.get("signal_max", _CONFIDENCE_MAX)

        if not signals_data:
            return

        raw_sources = signals_data.get("sources") or []
        if isinstance(raw_sources, list):
            self._sources = [s for s in raw_sources if isinstance(s, dict)]

        raw_sinks = signals_data.get("sinks") or []
        if isinstance(raw_sinks, list):
            self._sinks = [s for s in raw_sinks if isinstance(s, dict)]

    def is_available(self) -> bool:
        """Return True if signal data was loaded successfully."""
        return bool(self._sources or self._sinks)

    def infer_sink(
        self,
        func_name: str,
        param_names: list[str] | None = None,
        module_hint: str = "",
    ) -> tuple[str, float] | None:
        """
        Attempt to infer a sink type from function / param / module names.

        Args:
            func_name:   Fully dotted function name (e.g. "db.run_query").
            param_names: List of keyword argument names at the call site.
            module_hint: Module or object prefix (e.g. "subprocess").

        Returns:
            (sink_type, confidence) or None if no signal matches.
        """
        bare_name = func_name.split(".")[-1]
        param_names = param_names or []

        for rule in self._sinks:
            signals = rule.get("signals") or {}
            method_names: list[str] = signals.get("method_names") or []
            param_hints: list[str] = signals.get("param_hints") or []
            module_hints: list[str] = signals.get("module_hints") or []

            if bare_name not in method_names:
                continue

            sink_type = rule.get("type")
            if not sink_type:
                continue

            confidence = float(rule.get("confidence", self._base_sink))

            # Boost if param name hints match
            if param_hints and any(ph in param_names for ph in param_hints):
                confidence = min(confidence + self._boost, self._max)

            # Boost if module hint matches
            if module_hint and module_hints:
                hint_lower = module_hint.lower()
                if any(mh.lower() in hint_lower or hint_lower in mh.lower() for mh in module_hints):
                    confidence = min(confidence + self._boost, self._max)

            logger.debug(
                "signal_inferred_sink func=%s sink_type=%s confidence=%.2f",
                func_name,
                sink_type,
                confidence,
            )
            return (sink_type, confidence)

        return None

    def infer_source(
        self,
        name: str,
        context_module: str = "",
    ) -> tuple[str, float] | None:
        """
        Attempt to infer a source role from an object/method name.

        Args:
            name:           Fully dotted name (e.g. "request.get_json").
            context_module: Module import hint (e.g. "flask").

        Returns:
            (role, confidence) or None if no signal matches.
        """
        segments = name.split(".")
        # Second-to-last segment is type name, last is method name
        type_name = segments[-2] if len(segments) >= 2 else ""
        method_name = segments[-1]

        for rule in self._sources:
            signals = rule.get("signals") or {}
            type_names: list[str] = signals.get("type_names") or []
            method_names: list[str] = signals.get("method_names") or []
            module_hints: list[str] = signals.get("module_hints") or []

            matched = False
            if type_name and type_name in type_names:
                matched = True
            if method_name in method_names:
                matched = True

            if not matched:
                continue

            role = rule.get("role")
            if not role:
                continue

            confidence = float(rule.get("confidence", self._base_source))

            # Boost if module hint matches
            if context_module and module_hints:
                ctx_lower = context_module.lower()
                if any(mh.lower() in ctx_lower or ctx_lower in mh.lower() for mh in module_hints):
                    confidence = min(confidence + self._boost, self._max)

            logger.debug(
                "signal_inferred_source name=%s role=%s confidence=%.2f",
                name,
                role,
                confidence,
            )
            return (role, confidence)

        return None
