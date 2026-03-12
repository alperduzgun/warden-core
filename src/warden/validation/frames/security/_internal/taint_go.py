from __future__ import annotations

import re
from typing import Any

from warden.shared.infrastructure.logging import get_logger
from warden.validation.frames.security._internal.taint_analyzer import (
    TaintPath,
    TaintSink,
    TaintSource,
)
from warden.validation.frames.security._internal.taint_catalog import TaintCatalog

logger = get_logger(__name__)

_RE_GO_ASSIGN = re.compile(r"(\w+)\s*:?=\s*(.+)")
_RE_GO_CALL = re.compile(r"([\w.]+)\s*\(([^)]*)\)")


class GoTaintStrategy:
    def __init__(self, catalog: TaintCatalog, taint_config: dict[str, Any]) -> None:
        self._catalog = catalog
        self._taint_config = taint_config
        self._propagation_confidence: float = taint_config["propagation_confidence"]
        self._sanitizer_penalty: float = taint_config["sanitizer_penalty"]

    def analyze(self, source_code: str) -> list[TaintPath]:
        lines = source_code.splitlines()
        tainted_vars: dict[str, TaintSource] = {}
        go_sources = self._catalog.sources.get("go", set())

        for line_num, line in enumerate(lines, 1):
            stripped = line.strip()
            for m in _RE_GO_ASSIGN.finditer(stripped):
                var_name = m.group(1)
                value_expr = m.group(2).strip()
                for src in go_sources:
                    if src in value_expr:
                        if var_name not in tainted_vars:
                            tainted_vars[var_name] = TaintSource(
                                name=value_expr,
                                node_type="assignment",
                                line=line_num,
                            )
                        break

        for _ in range(5):
            changed = False
            for line_num, line in enumerate(lines, 1):
                stripped = line.strip()
                for m in _RE_GO_ASSIGN.finditer(stripped):
                    var_name = m.group(1)
                    value_expr = m.group(2).strip()
                    if var_name in tainted_vars:
                        continue
                    for tv in tainted_vars:
                        if re.search(r"\b" + re.escape(tv) + r"\b", value_expr):
                            tainted_vars[var_name] = TaintSource(
                                name=value_expr,
                                node_type="propagation",
                                line=line_num,
                                confidence=self._propagation_confidence,
                            )
                            changed = True
                            break
            if not changed:
                break

        paths: list[TaintPath] = []
        for line_num, line in enumerate(lines, 1):
            paths.extend(self._go_find_sinks(line, line_num, tainted_vars))

        logger.debug("go_taint_analysis_complete", paths_found=len(paths))
        return paths

    def _go_find_sinks(self, line: str, line_num: int, tainted_vars: dict[str, TaintSource]) -> list[TaintPath]:
        if not tainted_vars:
            return []

        stripped = line.strip()
        paths: list[TaintPath] = []

        for sink_name, sink_type in self._catalog.sinks.items():
            escaped = re.escape(sink_name)
            call_pat = re.compile(r"(?:^|[^.\w])" + escaped + r"\s*\(([^)]*)\)")
            for m in call_pat.finditer(stripped):
                args_str = m.group(1)
                for tv, tainted_src in tainted_vars.items():
                    if re.search(r"\b" + re.escape(tv) + r"\b", args_str):
                        sanitizers = self._detect_go_sanitizers(args_str, sink_type)
                        is_sanitized = len(sanitizers) > 0
                        paths.append(
                            TaintPath(
                                source=tainted_src,
                                sink=TaintSink(name=sink_name, sink_type=sink_type, line=line_num),
                                sanitizers=sanitizers,
                                is_sanitized=is_sanitized,
                                confidence=tainted_src.confidence * (self._sanitizer_penalty if is_sanitized else 1.0),
                            )
                        )
        return paths

    def _detect_go_sanitizers(self, args_str: str, sink_type: str) -> list[str]:
        sanitizers: list[str] = []
        for san in self._catalog.sanitizers.get(sink_type, set()):
            if san in args_str:
                sanitizers.append(san)
        return sanitizers
