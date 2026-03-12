from __future__ import annotations

import re
from typing import Any

from warden.shared.infrastructure.logging import get_logger
from warden.validation.frames.security._internal.taint_analyzer import (
    ALL_SINK_TYPES,
    TaintPath,
    TaintSink,
    TaintSource,
    _RE_ASSIGN,
    _RE_DESTRUCT,
    _RE_TEMPLATE,
)
from warden.validation.frames.security._internal.taint_catalog import TaintCatalog

logger = get_logger(__name__)


class JsTaintStrategy:
    def __init__(self, catalog: TaintCatalog, taint_config: dict[str, Any]) -> None:
        self._catalog = catalog
        self._taint_config = taint_config
        self._propagation_confidence: float = taint_config["propagation_confidence"]
        self._sanitizer_penalty: float = taint_config["sanitizer_penalty"]

    def analyze(self, source_code: str) -> list[TaintPath]:
        lines = source_code.splitlines()
        tainted_vars: dict[str, TaintSource] = {}

        for line_num, line in enumerate(lines, 1):
            self._js_collect_sources(line, line_num, tainted_vars)

        for _ in range(5):
            changed = False
            for line_num, line in enumerate(lines, 1):
                if self._js_propagate(line, line_num, tainted_vars):
                    changed = True
            if not changed:
                break

        paths: list[TaintPath] = []
        for line_num, line in enumerate(lines, 1):
            paths.extend(self._js_find_sinks(line, line_num, tainted_vars))

        logger.debug("js_taint_analysis_complete", paths_found=len(paths))
        return paths

    def _js_collect_sources(self, line: str, line_num: int, tainted_vars: dict[str, TaintSource]) -> None:
        stripped = line.strip()

        for m in _RE_ASSIGN.finditer(stripped):
            var_name = m.group(1)
            value_expr = m.group(2).strip()
            for src in self._catalog.sources.get("javascript", set()):
                if src in value_expr:
                    if var_name not in tainted_vars:
                        tainted_vars[var_name] = TaintSource(
                            name=value_expr,
                            node_type="assignment",
                            line=line_num,
                            taint_labels=set(ALL_SINK_TYPES),
                        )
                    break

        for m in _RE_DESTRUCT.finditer(stripped):
            value_expr = m.group(2).strip()
            for src in self._catalog.sources.get("javascript", set()):
                if src in value_expr:
                    for raw_field in m.group(1).split(","):
                        parts = raw_field.strip().split(":")
                        field_name = parts[-1].strip()
                        if field_name and field_name not in tainted_vars:
                            tainted_vars[field_name] = TaintSource(
                                name=f"{value_expr}.{field_name}",
                                node_type="destructuring",
                                line=line_num,
                                taint_labels=set(ALL_SINK_TYPES),
                            )
                    break

    def _js_propagate(self, line: str, line_num: int, tainted_vars: dict[str, TaintSource]) -> bool:
        stripped = line.strip()
        added = False
        for m in _RE_ASSIGN.finditer(stripped):
            var_name = m.group(1)
            value_expr = m.group(2).strip()
            if var_name in tainted_vars:
                continue
            for tv in tainted_vars:
                if re.search(r"\b" + re.escape(tv) + r"\b", value_expr):
                    parent_labels = tainted_vars[tv].taint_labels
                    tainted_vars[var_name] = TaintSource(
                        name=value_expr,
                        node_type="propagation",
                        line=line_num,
                        confidence=self._propagation_confidence,
                        taint_labels=set(parent_labels) if parent_labels else set(ALL_SINK_TYPES),
                    )
                    added = True
                    break
        return added

    def _js_find_sinks(self, line: str, line_num: int, tainted_vars: dict[str, TaintSource]) -> list[TaintPath]:
        if not tainted_vars:
            return []

        stripped = line.strip()
        paths: list[TaintPath] = []

        for sink_name, sink_type in self._catalog.sinks.items():
            if sink_name in self._catalog.assign_sinks:
                pattern = re.compile(r"\." + re.escape(sink_name) + r"\s*=\s*(.+?)(?:;|$)")
                for m in pattern.finditer(stripped):
                    args_str = m.group(1)
                    paths.extend(self._js_check_args(args_str, sink_name, sink_type, line_num, tainted_vars))
                continue

            escaped = re.escape(sink_name)
            call_pat = re.compile(r"(?:^|[^.\w])" + escaped + r"\s*\(([^)]*)\)")
            for m in call_pat.finditer(stripped):
                args_str = m.group(1)
                expanded = _RE_TEMPLATE.sub(lambda x: x.group(1), args_str)
                paths.extend(self._js_check_args(expanded, sink_name, sink_type, line_num, tainted_vars))

        return paths

    def _js_check_args(
        self,
        args_str: str,
        sink_name: str,
        sink_type: str,
        line_num: int,
        tainted_vars: dict[str, TaintSource],
    ) -> list[TaintPath]:
        found: list[TaintPath] = []
        for tv, tainted_src in tainted_vars.items():
            if re.search(r"\b" + re.escape(tv) + r"\b", args_str):
                sanitizers = self._detect_js_sanitizers(args_str, sink_type)
                active_labels = set(tainted_src.taint_labels) if tainted_src.taint_labels else set(ALL_SINK_TYPES)
                if sanitizers:
                    active_labels.discard(sink_type)
                is_sanitized = sink_type not in active_labels
                confidence = tainted_src.confidence * (self._sanitizer_penalty if is_sanitized else 1.0)
                found.append(
                    TaintPath(
                        source=tainted_src,
                        sink=TaintSink(name=sink_name, sink_type=sink_type, line=line_num),
                        sanitizers=sanitizers,
                        is_sanitized=is_sanitized,
                        taint_labels=active_labels,
                        confidence=confidence,
                    )
                )
        return found

    def _detect_js_sanitizers(self, args_str: str, sink_type: str) -> list[str]:
        sanitizers: list[str] = []
        for san in self._catalog.sanitizers.get(sink_type, set()):
            if san in args_str:
                sanitizers.append(san)
        return sanitizers
