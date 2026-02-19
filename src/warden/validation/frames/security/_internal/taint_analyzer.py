"""
Source-to-Sink Taint Analysis Engine.

Supports:
  - Python: AST-based, single-function scope
  - JavaScript/TypeScript: Regex-based, multi-pass propagation
  - Go: Regex-based, 3-pass propagation
  - Java: Regex-based, 3-pass propagation

Cross-function and cross-file analysis deferred to future iterations.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from typing import Any

from warden.shared.infrastructure.logging import get_logger

# Imported here (not under TYPE_CHECKING) so self._catalog is fully typed.
# taint_catalog imports back from taint_analyzer only lazily (inside get_default()),
# so there is no circular import at module-load time.
from warden.validation.frames.security._internal.taint_catalog import TaintCatalog

logger = get_logger(__name__)

# ── Single source of truth for taint configuration defaults ────────────────
TAINT_DEFAULTS: dict[str, float] = {
    "confidence_threshold": 0.8,   # >= this → HIGH severity + is_blocker
    "sanitizer_penalty": 0.3,      # multiplied when sanitized (0.0–1.0)
    "propagation_confidence": 0.75, # confidence assigned to propagated taint
    "signal_base_source": 0.65,    # heuristic source detection base
    "signal_base_sink": 0.60,      # heuristic sink detection base
    "signal_boost": 0.10,          # per param/module hint match
    "signal_max": 0.90,            # heuristic confidence cap
}


def validate_taint_config(raw: dict[str, Any] | None) -> dict[str, float]:
    """Validate and clamp taint config values. Fail-fast on bad types with warning.

    Returns a clean dict with only valid float values in [0.0, 1.0].
    Invalid or missing keys silently fall back to ``TAINT_DEFAULTS``.
    """
    if not raw:
        return dict(TAINT_DEFAULTS)

    validated: dict[str, float] = {}
    for key, default in TAINT_DEFAULTS.items():
        raw_val = raw.get(key)
        if raw_val is None:
            validated[key] = default
            continue

        # Type coercion — accept int/float, reject everything else
        try:
            val = float(raw_val)
        except (TypeError, ValueError):
            logger.warning(
                "taint_config_invalid_type",
                key=key,
                value=repr(raw_val),
                fallback=default,
            )
            validated[key] = default
            continue

        # Range clamping [0.0, 1.0]
        if val < 0.0 or val > 1.0:
            clamped = max(0.0, min(1.0, val))
            logger.warning(
                "taint_config_out_of_range",
                key=key,
                value=val,
                clamped=clamped,
            )
            validated[key] = clamped
        else:
            validated[key] = val

    return validated


@dataclass
class TaintSource:
    """A source of tainted (user-controlled) data."""

    name: str  # "request.args"
    node_type: str  # "call", "attribute", "subscript"
    line: int
    confidence: float = 0.9


@dataclass
class TaintSink:
    """A dangerous sink that should not receive tainted data."""

    name: str  # "cursor.execute"
    sink_type: str  # "SQL-value", "CMD-argument", "HTML-content"
    line: int


@dataclass
class TaintPath:
    """A detected taint flow from source to sink."""

    source: TaintSource
    sink: TaintSink
    transformations: list[str] = field(default_factory=list)  # ["f-string", "str.format"]
    sanitizers: list[str] = field(default_factory=list)  # ["html.escape"]
    is_sanitized: bool = False
    confidence: float = 0.0

    def to_json(self) -> dict[str, Any]:
        return {
            "source": {"name": self.source.name, "line": self.source.line, "confidence": self.source.confidence},
            "sink": {"name": self.sink.name, "type": self.sink_type, "line": self.sink.line},
            "transformations": self.transformations,
            "sanitizers": self.sanitizers,
            "is_sanitized": self.is_sanitized,
            "confidence": self.confidence,
        }

    @property
    def sink_type(self) -> str:
        return self.sink.sink_type


# Known taint sources (user-controlled input)
TAINT_SOURCES = {
    "request.args",
    "request.form",
    "request.json",
    "request.data",
    "request.values",
    "request.cookies",
    "request.headers",
    "request.get_json",
    "request.files",
    "input",
    "sys.argv",
    "os.environ",
    "os.getenv",
    "stdin",
    "sys.stdin",
}

# Known sinks with their types
TAINT_SINKS: dict[str, str] = {
    # SQL sinks
    "cursor.execute": "SQL-value",
    "cursor.executemany": "SQL-value",
    "connection.execute": "SQL-value",
    "db.execute": "SQL-value",
    "session.execute": "SQL-value",
    "engine.execute": "SQL-value",
    # Command sinks
    "os.system": "CMD-argument",
    "os.popen": "CMD-argument",
    "subprocess.run": "CMD-argument",
    "subprocess.call": "CMD-argument",
    "subprocess.Popen": "CMD-argument",
    # HTML sinks
    "render_template_string": "HTML-content",
    "Markup": "HTML-content",
    # Eval sinks
    "eval": "CODE-execution",
    "exec": "CODE-execution",
    "compile": "CODE-execution",
    # File sinks
    "open": "FILE-path",
    "pathlib.Path": "FILE-path",
}

# Known sanitizers
KNOWN_SANITIZERS: dict[str, set[str]] = {
    "SQL-value": {"parameterized_query", "sqlalchemy.text", "prepared_statement"},
    "CMD-argument": {"shlex.quote", "shlex.split"},
    "HTML-content": {"html.escape", "markupsafe.escape", "bleach.clean"},
    "CODE-execution": set(),  # No sanitizer is safe for eval
    "FILE-path": {"os.path.basename", "pathlib.PurePath"},
}


# ── JavaScript / TypeScript constants ──────────────────────────────────────

# User-controlled input sources in JS/TS
JS_TAINT_SOURCES: set[str] = {
    # Express / Node HTTP
    "req.body",
    "req.query",
    "req.params",
    "req.headers",
    "req.cookies",
    "request.body",
    "request.query",
    "request.params",
    "request.headers",
    "request.cookies",
    # Environment / process
    "process.env",
    # DOM / browser
    "document.cookie",
    "document.location",
    "window.location",
    "location.search",
    "location.hash",
    "location.href",
    "localStorage.getItem",
    "sessionStorage.getItem",
    # WebSocket / events
    "event.data",
}

# Dangerous sinks in JS/TS
JS_TAINT_SINKS: dict[str, str] = {
    # Code execution
    "eval": "CODE-execution",
    "Function": "CODE-execution",
    "setTimeout": "CODE-execution",
    "setInterval": "CODE-execution",
    # Shell
    "exec": "CMD-argument",
    "execSync": "CMD-argument",
    "spawn": "CMD-argument",
    "spawnSync": "CMD-argument",
    "child_process.exec": "CMD-argument",
    "child_process.execSync": "CMD-argument",
    "child_process.spawn": "CMD-argument",
    # SQL
    "db.query": "SQL-value",
    "pool.query": "SQL-value",
    "connection.query": "SQL-value",
    "client.query": "SQL-value",
    "sequelize.query": "SQL-value",
    "knex.raw": "SQL-value",
    # HTML / XSS — property assignment sinks handled separately
    "innerHTML": "HTML-content",
    "outerHTML": "HTML-content",
    "document.write": "HTML-content",
    "document.writeln": "HTML-content",
    "insertAdjacentHTML": "HTML-content",
    # File system
    "fs.readFile": "FILE-path",
    "fs.readFileSync": "FILE-path",
    "fs.writeFile": "FILE-path",
    "fs.writeFileSync": "FILE-path",
}

# Property-assignment sinks (element.innerHTML = ...)
_JS_ASSIGN_SINKS: set[str] = {"innerHTML", "outerHTML"}

JS_SANITIZERS: dict[str, set[str]] = {
    "SQL-value": {"db.escape", "connection.escape", "mysql.escape", "sequelize.escape", "knex.escape"},
    "CMD-argument": set(),  # No safe sanitizer exists for shell injection
    "HTML-content": {"DOMPurify.sanitize", "sanitizeHtml", "escapeHtml", "encodeURIComponent", "xss"},
    "CODE-execution": set(),
    "FILE-path": {"path.basename", "path.resolve", "encodeURIComponent"},
}

# ── Regex helpers ───────────────────────────────────────────────────────────

# Matches: (const|let|var) name [: TypeAnnotation] = <expr>;
# TypeScript type annotations like `const id: string = ...` are handled by the optional group.
_RE_ASSIGN = re.compile(r"(?:const|let|var)\s+(\w+)(?:\s*:\s*[\w<>\[\]|&,\s.]+?)?\s*=\s*(.+?)(?:;|$)")
# Matches: const { a, b: c } = <expr>;
_RE_DESTRUCT = re.compile(r"(?:const|let|var)\s+\{([^}]+)\}\s*=\s*(.+?)(?:;|$)")
# Matches template literal holes: ${varName}
_RE_TEMPLATE = re.compile(r"\$\{(\w+)\}")


class TaintAnalyzer:
    """
    Multi-language source-to-sink taint analyzer.

    - Python: AST-based, single-function scope
    - JavaScript/TypeScript: Regex-based, multi-pass propagation

    Cross-function and cross-file analysis deferred to future iterations.

    Args:
        catalog: TaintCatalog instance with sources/sinks/sanitizers.
                 If None, the built-in default catalog is used.
    """

    def __init__(self, catalog: TaintCatalog | None = None, taint_config: dict[str, Any] | None = None) -> None:
        if catalog is None:
            from warden.validation.frames.security._internal.taint_catalog import (  # noqa: PLC0415
                TaintCatalog as _TaintCatalog,
            )

            catalog = _TaintCatalog.get_default()
        self._catalog = catalog

        # Validate + clamp config (fail-fast on bad types, fallback to defaults)
        self._taint_config: dict[str, float] = validate_taint_config(taint_config)
        self._propagation_confidence: float = self._taint_config["propagation_confidence"]
        self._sanitizer_penalty: float = self._taint_config["sanitizer_penalty"]

        # Observability: log when non-default config is active
        overrides = {
            k: v for k, v in self._taint_config.items() if v != TAINT_DEFAULTS[k]
        }
        if overrides:
            logger.info("taint_config_custom_overrides", overrides=overrides)

        # Load signal inference engine (graceful — unavailable if signals.yaml missing)
        try:
            from warden.validation.frames.security._internal.model_loader import (  # noqa: PLC0415
                ModelPackLoader,
            )
            from warden.validation.frames.security._internal.signal_inference import (  # noqa: PLC0415
                SignalInferenceEngine,
            )

            signals_data = ModelPackLoader.load_signals()
            self._signal_engine: SignalInferenceEngine | None = SignalInferenceEngine(
                signals_data, config=self._taint_config
            )
        except Exception:
            self._signal_engine = None

    def analyze(self, source_code: str, language: str = "python") -> list[TaintPath]:
        """
        Analyze source code for taint paths.

        Args:
            source_code: Source code string
            language: Programming language ("python", "javascript", "typescript",
                      "go", "java")

        Returns:
            List of detected TaintPath objects
        """
        if language in ("javascript", "typescript"):
            return self._analyze_js(source_code)

        if language == "go":
            return self._analyze_go(source_code)

        if language == "java":
            return self._analyze_java(source_code)

        if language != "python":
            logger.debug("taint_analysis_unsupported_language", language=language)
            return []

        try:
            tree = ast.parse(source_code)
        except SyntaxError as e:
            logger.debug("taint_analysis_parse_error", error=str(e))
            return []

        paths: list[TaintPath] = []

        # Analyze each function definition
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_paths = self._analyze_function(node, source_code)
                paths.extend(func_paths)

        logger.debug("taint_analysis_complete", paths_found=len(paths))
        return paths

    # ── JavaScript / TypeScript analysis ───────────────────────────────────

    def _analyze_js(self, source_code: str) -> list[TaintPath]:
        """
        Regex-based taint analysis for JavaScript / TypeScript.

        Three passes:
          1. Find variables directly assigned from known sources.
          2. Propagate taint through re-assignments (up to 5 iterations).
          3. Detect tainted variables flowing into known sinks.
        """
        lines = source_code.splitlines()
        tainted_vars: dict[str, TaintSource] = {}

        # Pass 1 – direct source assignments
        for line_num, line in enumerate(lines, 1):
            self._js_collect_sources(line, line_num, tainted_vars)

        # Pass 2 – propagation (handles `const id = query.id` after `const query = req.query`)
        for _ in range(5):
            changed = False
            for line_num, line in enumerate(lines, 1):
                if self._js_propagate(line, line_num, tainted_vars):
                    changed = True
            if not changed:
                break

        # Pass 3 – sink detection
        paths: list[TaintPath] = []
        for line_num, line in enumerate(lines, 1):
            paths.extend(self._js_find_sinks(line, line_num, tainted_vars))

        logger.debug("js_taint_analysis_complete", paths_found=len(paths))
        return paths

    def _js_collect_sources(self, line: str, line_num: int, tainted_vars: dict[str, TaintSource]) -> None:
        """Detect direct source assignments on a single line."""
        stripped = line.strip()

        # Regular assignment: const userId = req.query.id
        for m in _RE_ASSIGN.finditer(stripped):
            var_name = m.group(1)
            value_expr = m.group(2).strip()
            for src in self._catalog.sources.get("javascript", set()):
                if src in value_expr:
                    if var_name not in tainted_vars:
                        tainted_vars[var_name] = TaintSource(
                            name=value_expr, node_type="assignment", line=line_num
                        )
                    break

        # Destructuring: const { id, name } = req.body
        for m in _RE_DESTRUCT.finditer(stripped):
            value_expr = m.group(2).strip()
            for src in self._catalog.sources.get("javascript", set()):
                if src in value_expr:
                    for raw_field in m.group(1).split(","):
                        # Support `{ a: b }` rename — take the alias (b)
                        parts = raw_field.strip().split(":")
                        field = parts[-1].strip()
                        if field and field not in tainted_vars:
                            tainted_vars[field] = TaintSource(
                                name=f"{value_expr}.{field}",
                                node_type="destructuring",
                                line=line_num,
                            )
                    break

    def _js_propagate(self, line: str, line_num: int, tainted_vars: dict[str, TaintSource]) -> bool:
        """Propagate taint through simple re-assignments. Returns True if new taint added."""
        stripped = line.strip()
        added = False
        for m in _RE_ASSIGN.finditer(stripped):
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
                    added = True
                    break
        return added

    def _js_find_sinks(self, line: str, line_num: int, tainted_vars: dict[str, TaintSource]) -> list[TaintPath]:
        """Detect tainted variables flowing into JS sinks on a single line."""
        if not tainted_vars:
            return []

        stripped = line.strip()
        paths: list[TaintPath] = []

        for sink_name, sink_type in self._catalog.sinks.items():
            # ── Assignment-style sinks: element.innerHTML = taintedVar ──
            if sink_name in self._catalog.assign_sinks:
                pattern = re.compile(r"\." + re.escape(sink_name) + r"\s*=\s*(.+?)(?:;|$)")
                for m in pattern.finditer(stripped):
                    args_str = m.group(1)
                    paths.extend(self._js_check_args(args_str, sink_name, sink_type, line_num, tainted_vars))
                continue

            # ── Call-style sinks: db.query(...), eval(...) ──
            # Match both `sinkName(` and `obj.sinkName(` / `obj.sinkName\n(`
            escaped = re.escape(sink_name)
            call_pat = re.compile(r"(?:^|[^.\w])" + escaped + r"\s*\(([^)]*)\)")
            for m in call_pat.finditer(stripped):
                args_str = m.group(1)
                # Also check template literals inside the args
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
        """Check if any tainted variable appears in an argument string."""
        found: list[TaintPath] = []
        for tv, tainted_src in tainted_vars.items():
            if re.search(r"\b" + re.escape(tv) + r"\b", args_str):
                sanitizers = self._detect_js_sanitizers(args_str, sink_type)
                is_sanitized = len(sanitizers) > 0
                confidence = tainted_src.confidence * (self._sanitizer_penalty if is_sanitized else 1.0)
                found.append(
                    TaintPath(
                        source=tainted_src,
                        sink=TaintSink(name=sink_name, sink_type=sink_type, line=line_num),
                        sanitizers=sanitizers,
                        is_sanitized=is_sanitized,
                        confidence=confidence,
                    )
                )
        return found

    def _detect_js_sanitizers(self, args_str: str, sink_type: str) -> list[str]:
        """Detect known JS sanitizer calls in an argument string."""
        sanitizers: list[str] = []
        for san in self._catalog.sanitizers.get(sink_type, set()):
            if san in args_str:
                sanitizers.append(san)
        return sanitizers

    # ── Python AST analysis ─────────────────────────────────────────────────

    def _analyze_function(self, func_node: ast.FunctionDef | ast.AsyncFunctionDef, source: str) -> list[TaintPath]:
        """Analyze a single function for taint flows."""
        # Step 1: Find all tainted variables (assigned from sources)
        tainted_vars: dict[str, TaintSource] = {}
        # Step 2: Track transformations on tainted data
        transformations: dict[str, list[str]] = {}
        # Step 3: Find sinks consuming tainted data
        paths: list[TaintPath] = []

        for node in ast.walk(func_node):
            # Detect taint sources in assignments
            if isinstance(node, ast.Assign):
                self._check_assignment_for_sources(node, tainted_vars)

            # Detect taint in augmented assignments
            if isinstance(node, ast.AugAssign):
                self._check_aug_assignment(node, tainted_vars)

            # Detect sinks
            if isinstance(node, ast.Call):
                sink_info = self._identify_sink(node)
                if sink_info:
                    # Check if any argument is tainted
                    for arg in node.args:
                        tainted_source = self._is_tainted(arg, tainted_vars)
                        if tainted_source:
                            sink = TaintSink(
                                name=sink_info[0],
                                sink_type=sink_info[1],
                                line=node.lineno,
                            )

                            # Check for sanitizers
                            sanitizers = self._detect_sanitizers(arg, sink.sink_type)
                            is_sanitized = len(sanitizers) > 0

                            # Get transformations
                            var_name = self._get_var_name(arg)
                            xforms = transformations.get(var_name, []) if var_name else []

                            confidence = tainted_source.confidence
                            if is_sanitized:
                                confidence *= self._sanitizer_penalty

                            path = TaintPath(
                                source=tainted_source,
                                sink=sink,
                                transformations=xforms,
                                sanitizers=sanitizers,
                                is_sanitized=is_sanitized,
                                confidence=confidence,
                            )
                            paths.append(path)

                    # Also check keyword arguments
                    for kw in node.keywords:
                        tainted_source = self._is_tainted(kw.value, tainted_vars)
                        if tainted_source:
                            sink = TaintSink(
                                name=sink_info[0],
                                sink_type=sink_info[1],
                                line=node.lineno,
                            )
                            path = TaintPath(
                                source=tainted_source,
                                sink=sink,
                                confidence=tainted_source.confidence,
                            )
                            paths.append(path)

            # Track f-string and format transformations
            if isinstance(node, ast.JoinedStr):  # f-string
                for val in node.values:
                    if isinstance(val, ast.FormattedValue):
                        var_name = self._get_var_name(val.value)
                        if var_name:
                            transformations.setdefault(var_name, []).append("f-string")

        return paths

    def _check_assignment_for_sources(self, node: ast.Assign, tainted_vars: dict[str, TaintSource]) -> None:
        """Check if an assignment introduces tainted data."""
        source = self._identify_source(node.value)
        if source:
            for target in node.targets:
                var_name = self._get_var_name(target)
                if var_name:
                    tainted_vars[var_name] = source

        # Propagate taint through assignments: x = tainted_var
        if not source:
            tainted = self._is_tainted(node.value, tainted_vars)
            if tainted:
                for target in node.targets:
                    var_name = self._get_var_name(target)
                    if var_name:
                        tainted_vars[var_name] = tainted

    def _check_aug_assignment(self, node: ast.AugAssign, tainted_vars: dict[str, TaintSource]) -> None:
        """Check augmented assignments (+=, etc.) for taint propagation."""
        var_name = self._get_var_name(node.target)
        if var_name and var_name in tainted_vars:
            return  # Already tainted

        source = self._identify_source(node.value)
        if source and var_name:
            tainted_vars[var_name] = source

    def _identify_source(self, node: ast.expr) -> TaintSource | None:
        """Check if an expression is a known taint source."""
        py_sources = self._catalog.sources.get("python", set())
        name = self._get_dotted_name(node)
        if name:
            for src_pattern in py_sources:
                if name.startswith(src_pattern) or src_pattern in name:
                    return TaintSource(
                        name=name,
                        node_type=type(node).__name__.lower(),
                        line=getattr(node, "lineno", 0),
                    )

        # Check for call to known source
        if isinstance(node, ast.Call):
            func_name = self._get_dotted_name(node.func)
            if func_name:
                for src_pattern in py_sources:
                    if func_name.startswith(src_pattern) or src_pattern in func_name:
                        return TaintSource(
                            name=func_name,
                            node_type="call",
                            line=getattr(node, "lineno", 0),
                        )
                # Signal inference fallback for calls
                if self._signal_engine and self._signal_engine.is_available():
                    parts = func_name.split(".")
                    module_hint = ".".join(parts[:-1]) if len(parts) > 1 else ""
                    inferred = self._signal_engine.infer_source(func_name, module_hint)
                    if inferred:
                        return TaintSource(
                            name=func_name,
                            node_type="call",
                            line=getattr(node, "lineno", 0),
                            confidence=inferred[1],
                        )

        # Check subscript (e.g., request.args['id'])
        if isinstance(node, ast.Subscript):
            value_name = self._get_dotted_name(node.value)
            if value_name:
                for src_pattern in py_sources:
                    if value_name.startswith(src_pattern):
                        return TaintSource(
                            name=value_name,
                            node_type="subscript",
                            line=getattr(node, "lineno", 0),
                        )
                # Signal inference fallback for subscript
                if self._signal_engine and self._signal_engine.is_available():
                    parts = value_name.split(".")
                    module_hint = ".".join(parts[:-1]) if len(parts) > 1 else ""
                    inferred = self._signal_engine.infer_source(value_name, module_hint)
                    if inferred:
                        return TaintSource(
                            name=value_name,
                            node_type="subscript",
                            line=getattr(node, "lineno", 0),
                            confidence=inferred[1],
                        )

        # Signal inference fallback for attribute access
        if name and self._signal_engine and self._signal_engine.is_available():
            parts = name.split(".")
            module_hint = ".".join(parts[:-1]) if len(parts) > 1 else ""
            inferred = self._signal_engine.infer_source(name, module_hint)
            if inferred:
                return TaintSource(
                    name=name,
                    node_type=type(node).__name__.lower(),
                    line=getattr(node, "lineno", 0),
                    confidence=inferred[1],
                )

        return None

    def _identify_sink(self, node: ast.Call) -> tuple[str, str] | None:
        """Check if a call is a known sink. Returns (name, sink_type) or None."""
        func_name = self._get_dotted_name(node.func)
        if func_name:
            # Step 1: explicit catalog lookup
            for sink_pattern, sink_type in self._catalog.sinks.items():
                if func_name.endswith(sink_pattern) or sink_pattern in func_name:
                    return (func_name, sink_type)

            # Step 2: signal inference fallback
            if self._signal_engine and self._signal_engine.is_available():
                param_names = [kw.arg for kw in node.keywords if kw.arg]
                # Extract module hint from dotted name (everything before the last segment)
                parts = func_name.split(".")
                module_hint = ".".join(parts[:-1]) if len(parts) > 1 else ""
                inferred = self._signal_engine.infer_sink(func_name, param_names, module_hint)
                if inferred:
                    sink_type, _ = inferred
                    return (func_name, sink_type)

        return None

    def _is_tainted(self, node: ast.expr, tainted_vars: dict[str, TaintSource]) -> TaintSource | None:
        """Check if an expression uses tainted data."""
        # Direct variable reference
        var_name = self._get_var_name(node)
        if var_name and var_name in tainted_vars:
            return tainted_vars[var_name]

        # Check if it's a direct source usage
        source = self._identify_source(node)
        if source:
            return source

        # Check f-string components
        if isinstance(node, ast.JoinedStr):
            for val in node.values:
                if isinstance(val, ast.FormattedValue):
                    result = self._is_tainted(val.value, tainted_vars)
                    if result:
                        return result

        # Check binary operations (string concatenation)
        if isinstance(node, ast.BinOp):
            left = self._is_tainted(node.left, tainted_vars)
            if left:
                return left
            right = self._is_tainted(node.right, tainted_vars)
            if right:
                return right

        # Check format calls: "...".format(tainted)
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute) and node.func.attr == "format":
                for arg in node.args:
                    result = self._is_tainted(arg, tainted_vars)
                    if result:
                        return result

        return None

    def _detect_sanitizers(self, node: ast.expr, sink_type: str) -> list[str]:
        """Detect if expression passes through any sanitizers."""
        sanitizers: list[str] = []
        valid_sanitizers = self._catalog.sanitizers.get(sink_type, set())

        if isinstance(node, ast.Call):
            func_name = self._get_dotted_name(node.func)
            if func_name:
                for san in valid_sanitizers:
                    if san in func_name:
                        sanitizers.append(func_name)

        return sanitizers

    def _get_dotted_name(self, node: ast.expr) -> str | None:
        """Get dotted name from AST node (e.g., 'request.args')."""
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            value = self._get_dotted_name(node.value)
            if value:
                return f"{value}.{node.attr}"
            return node.attr
        return None

    def _get_var_name(self, node: ast.expr) -> str | None:
        """Get simple variable name from node."""
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return self._get_dotted_name(node)
        return None

    # ── Go analysis ─────────────────────────────────────────────────────────

    # Go assignment: name := expr  or  name = expr
    _RE_GO_ASSIGN = re.compile(r"(\w+)\s*:?=\s*(.+)")
    # Go function call: funcName(args) or obj.Method(args)
    _RE_GO_CALL = re.compile(r"([\w.]+)\s*\(([^)]*)\)")

    def _analyze_go(self, source_code: str) -> list[TaintPath]:
        """
        Regex-based taint analysis for Go source code.

        Three passes (same approach as _analyze_js):
          1. Find variables assigned from known sources.
          2. Propagate taint through re-assignments.
          3. Detect tainted variables flowing into known sinks.
        """
        lines = source_code.splitlines()
        tainted_vars: dict[str, TaintSource] = {}
        go_sources = self._catalog.sources.get("go", set())

        # Pass 1 – direct source assignments
        for line_num, line in enumerate(lines, 1):
            stripped = line.strip()
            for m in self._RE_GO_ASSIGN.finditer(stripped):
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

        # Pass 2 – propagation
        for _ in range(5):
            changed = False
            for line_num, line in enumerate(lines, 1):
                stripped = line.strip()
                for m in self._RE_GO_ASSIGN.finditer(stripped):
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

        # Pass 3 – sink detection
        paths: list[TaintPath] = []
        for line_num, line in enumerate(lines, 1):
            paths.extend(self._go_find_sinks(line, line_num, tainted_vars))

        logger.debug("go_taint_analysis_complete", paths_found=len(paths))
        return paths

    def _go_find_sinks(
        self, line: str, line_num: int, tainted_vars: dict[str, TaintSource]
    ) -> list[TaintPath]:
        """Detect tainted variables flowing into Go sinks."""
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
        """Detect known Go sanitizer calls in an argument string."""
        sanitizers: list[str] = []
        for san in self._catalog.sanitizers.get(sink_type, set()):
            if san in args_str:
                sanitizers.append(san)
        return sanitizers

    # ── Java analysis ────────────────────────────────────────────────────────

    # Java assignment: Type varName = expr; or varName = expr;
    _RE_JAVA_ASSIGN = re.compile(r"(?:[\w<>\[\]]+\s+)?(\w+)\s*=\s*([^;]+)")

    def _analyze_java(self, source_code: str) -> list[TaintPath]:
        """
        Regex-based taint analysis for Java source code.

        Three passes (same approach as _analyze_js):
          1. Find variables assigned from known sources.
          2. Propagate taint through re-assignments.
          3. Detect tainted variables flowing into known sinks.
        """
        lines = source_code.splitlines()
        tainted_vars: dict[str, TaintSource] = {}
        java_sources = self._catalog.sources.get("java", set())

        # Pass 1 – direct source assignments
        for line_num, line in enumerate(lines, 1):
            stripped = line.strip()
            for m in self._RE_JAVA_ASSIGN.finditer(stripped):
                var_name = m.group(1)
                value_expr = m.group(2).strip()
                for src in java_sources:
                    if src in value_expr:
                        if var_name not in tainted_vars:
                            tainted_vars[var_name] = TaintSource(
                                name=value_expr,
                                node_type="assignment",
                                line=line_num,
                            )
                        break

        # Pass 2 – propagation
        for _ in range(5):
            changed = False
            for line_num, line in enumerate(lines, 1):
                stripped = line.strip()
                for m in self._RE_JAVA_ASSIGN.finditer(stripped):
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

        # Pass 3 – sink detection
        paths: list[TaintPath] = []
        for line_num, line in enumerate(lines, 1):
            paths.extend(self._java_find_sinks(line, line_num, tainted_vars))

        logger.debug("java_taint_analysis_complete", paths_found=len(paths))
        return paths

    def _java_find_sinks(
        self, line: str, line_num: int, tainted_vars: dict[str, TaintSource]
    ) -> list[TaintPath]:
        """Detect tainted variables flowing into Java sinks."""
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
                        sanitizers = self._detect_java_sanitizers(args_str, sink_type)
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

    def _detect_java_sanitizers(self, args_str: str, sink_type: str) -> list[str]:
        """Detect known Java sanitizer calls in an argument string."""
        sanitizers: list[str] = []
        for san in self._catalog.sanitizers.get(sink_type, set()):
            if san in args_str:
                sanitizers.append(san)
        return sanitizers
