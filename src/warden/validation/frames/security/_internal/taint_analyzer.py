"""
Source-to-Sink Taint Analysis Engine.

Supports:
  - Python: AST-based, interprocedural (single-file) with multi-label taint
  - JavaScript/TypeScript: Regex-based, multi-pass propagation
  - Go: Regex-based, 3-pass propagation
  - Java: Regex-based, 3-pass propagation

Phase 1 interprocedural analysis tracks taint across function boundaries
within a single file via call-graph construction and return-value propagation.

Multi-label taint assigns per-sink-type labels (e.g. {"SQL-value", "HTML-content"})
to tainted variables.  Sanitizers remove specific labels; a variable is clean
only when its label set is empty.
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
    "confidence_threshold": 0.8,  # >= this -> HIGH severity + is_blocker
    "sanitizer_penalty": 0.3,  # multiplied when sanitized (0.0-1.0)
    "propagation_confidence": 0.75,  # confidence assigned to propagated taint
    "signal_base_source": 0.65,  # heuristic source detection base
    "signal_base_sink": 0.60,  # heuristic sink detection base
    "signal_boost": 0.10,  # per param/module hint match
    "signal_max": 0.90,  # heuristic confidence cap
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

        # Type coercion -- accept int/float, reject everything else
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
    taint_labels: set[str] = field(default_factory=set)  # {"SQL-value", "HTML-content", ...}


@dataclass
class TaintSink:
    """A dangerous sink that should not receive tainted data."""

    name: str  # "cursor.execute"
    sink_type: str  # "SQL-value", "CMD-argument", "HTML-content"
    line: int


@dataclass
class TaintPath:
    """A detected taint flow from source to sink.

    Multi-label taint: ``taint_labels`` holds the set of sink-type labels that
    are still active (not yet sanitized) at the point the tainted data reaches
    the sink.  ``is_sanitized`` is now a computed property -- True when the
    sink's own type has been removed from the label set (or when sanitizers
    were applied that cover the sink type).

    For backward compatibility, ``is_sanitized`` can still be passed to
    ``__init__`` as a bool.  When explicitly set to ``True`` the label set
    will be empty, matching legacy behaviour.
    """

    source: TaintSource
    sink: TaintSink
    transformations: list[str] = field(default_factory=list)  # ["f-string", "str.format"]
    sanitizers: list[str] = field(default_factory=list)  # ["html.escape"]
    taint_labels: set[str] = field(default_factory=set)  # active (unsanitized) labels
    confidence: float = 0.0

    # Private backing field for legacy is_sanitized support.
    # When someone passes is_sanitized=True in constructor, we store it
    # and use it as override.  Otherwise computed from taint_labels.
    _is_sanitized_override: bool | None = field(default=None, repr=False, compare=False)

    def __init__(
        self,
        source: TaintSource,
        sink: TaintSink,
        transformations: list[str] | None = None,
        sanitizers: list[str] | None = None,
        is_sanitized: bool | None = None,
        taint_labels: set[str] | None = None,
        confidence: float = 0.0,
    ) -> None:
        self.source = source
        self.sink = sink
        self.transformations = transformations if transformations is not None else []
        self.sanitizers = sanitizers if sanitizers is not None else []
        self.confidence = confidence

        # Multi-label taint: if explicit taint_labels given, use them.
        # Otherwise derive from is_sanitized for backward compatibility.
        if taint_labels is not None:
            self.taint_labels = set(taint_labels)
        elif is_sanitized:
            # Legacy: explicitly sanitized -> empty label set
            self.taint_labels = set()
        else:
            # Default: the sink's own type is the active label
            self.taint_labels = {sink.sink_type}

        # Store legacy override for backward-compat property
        if is_sanitized is not None:
            self._is_sanitized_override = is_sanitized
        else:
            self._is_sanitized_override = None

    @property
    def is_sanitized(self) -> bool:
        """Whether the taint flow is sanitized for the target sink type.

        A flow is sanitized when:
          1. Legacy override was explicitly set to True, OR
          2. The sink's type is not in the active taint_labels set
             (meaning a sanitizer removed it).

        An empty taint_labels set means fully sanitized.
        """
        if self._is_sanitized_override is not None:
            return self._is_sanitized_override
        # If sink type is no longer in taint_labels, it's been sanitized
        return self.sink.sink_type not in self.taint_labels

    def to_json(self) -> dict[str, Any]:
        return {
            "source": {"name": self.source.name, "line": self.source.line, "confidence": self.source.confidence},
            "sink": {"name": self.sink.name, "type": self.sink_type, "line": self.sink.line},
            "transformations": self.transformations,
            "sanitizers": self.sanitizers,
            "is_sanitized": self.is_sanitized,
            "taint_labels": sorted(self.taint_labels),
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
    # HTTP / SSRF sinks (CWE-918) -- user-controlled URLs sent to external services
    "requests.get": "HTTP-request",
    "requests.post": "HTTP-request",
    "requests.put": "HTTP-request",
    "requests.delete": "HTTP-request",
    "requests.patch": "HTTP-request",
    "requests.request": "HTTP-request",
    "requests.head": "HTTP-request",
    "urllib.request.urlopen": "HTTP-request",
    "urllib.request.Request": "HTTP-request",
    "httpx.get": "HTTP-request",
    "httpx.post": "HTTP-request",
    "httpx.put": "HTTP-request",
    "httpx.delete": "HTTP-request",
    "httpx.request": "HTTP-request",
    "httpx.AsyncClient.get": "HTTP-request",
    "httpx.AsyncClient.post": "HTTP-request",
    "aiohttp.ClientSession.get": "HTTP-request",
    "aiohttp.ClientSession.post": "HTTP-request",
    "aiohttp.ClientSession.request": "HTTP-request",
    # LOG-output / PII leak sinks — logging functions that may expose sensitive data
    "logging.info": "LOG-output",
    "logging.debug": "LOG-output",
    "logging.warning": "LOG-output",
    "logging.error": "LOG-output",
    "logging.critical": "LOG-output",
    "logging.exception": "LOG-output",
    "logger.info": "LOG-output",
    "logger.debug": "LOG-output",
    "logger.warning": "LOG-output",
    "logger.error": "LOG-output",
    "logger.critical": "LOG-output",
    "logger.exception": "LOG-output",
    "print": "LOG-output",
}

# Known sanitizers
KNOWN_SANITIZERS: dict[str, set[str]] = {
    "SQL-value": {"parameterized_query", "sqlalchemy.text", "prepared_statement"},
    "CMD-argument": {"shlex.quote", "shlex.split"},
    "HTML-content": {"html.escape", "markupsafe.escape", "bleach.clean"},
    "CODE-execution": set(),  # No sanitizer is safe for eval
    "FILE-path": {"os.path.basename", "pathlib.PurePath"},
    # SSRF mitigation: allowlist / URL validation functions
    "HTTP-request": {"urllib.parse.urlparse", "ipaddress.ip_address", "validators.url"},
    # PII masking / log sanitization
    "LOG-output": {
        "mask_pii",
        "redact",
        "sanitize_log",
        "PIIMaskingFilter",
        "mask_sensitive",
        "scrub",
        "anonymize",
        "re.sub",
    },
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
    # HTML / XSS -- property assignment sinks handled separately
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
    # URL-fetch / SSRF sinks (CWE-918) — user-controlled URLs in JS HTTP clients
    "fetch": "URL-fetch",
    "axios": "URL-fetch",
    "axios.get": "URL-fetch",
    "axios.post": "URL-fetch",
    "axios.put": "URL-fetch",
    "axios.delete": "URL-fetch",
    "axios.request": "URL-fetch",
    "http.request": "URL-fetch",
    "http.get": "URL-fetch",
    "https.request": "URL-fetch",
    "https.get": "URL-fetch",
    "got": "URL-fetch",
    "got.get": "URL-fetch",
    "got.post": "URL-fetch",
    "node-fetch": "URL-fetch",
    "undici.fetch": "URL-fetch",
    "undici.request": "URL-fetch",
    # LOG-output / PII leak sinks — JS logging that may expose sensitive data
    "console.log": "LOG-output",
    "console.error": "LOG-output",
    "console.warn": "LOG-output",
    "console.debug": "LOG-output",
    "console.info": "LOG-output",
    "console.trace": "LOG-output",
    "logger.info": "LOG-output",
    "logger.error": "LOG-output",
    "logger.warn": "LOG-output",
    "logger.debug": "LOG-output",
}

# Property-assignment sinks (element.innerHTML = ...)
_JS_ASSIGN_SINKS: set[str] = {"innerHTML", "outerHTML"}

JS_SANITIZERS: dict[str, set[str]] = {
    "SQL-value": {"db.escape", "connection.escape", "mysql.escape", "sequelize.escape", "knex.escape"},
    "CMD-argument": set(),  # No safe sanitizer exists for shell injection
    "HTML-content": {"DOMPurify.sanitize", "sanitizeHtml", "escapeHtml", "encodeURIComponent", "xss"},
    "CODE-execution": set(),
    "FILE-path": {"path.basename", "path.resolve", "encodeURIComponent"},
    # SSRF mitigation for JS: URL validation / allowlist checking
    "URL-fetch": {"url.parse", "new URL", "validator.isURL", "isValidUrl", "allowedHosts.includes", "URL.canParse"},
    # PII masking / log sanitization for JS
    "LOG-output": {"mask_pii", "redact", "sanitize_log", "mask_sensitive", "scrub", "anonymize"},
}

# ── Regex helpers ───────────────────────────────────────────────────────────

# Matches: (const|let|var) name [: TypeAnnotation] = <expr>;
# TypeScript type annotations like `const id: string = ...` are handled by the optional group.
_RE_ASSIGN = re.compile(r"(?:const|let|var)\s+(\w+)(?:\s*:\s*[\w<>\[\]|&,\s.]+?)?\s*=\s*(.+?)(?:;|$)")
# Matches: const { a, b: c } = <expr>;
_RE_DESTRUCT = re.compile(r"(?:const|let|var)\s+\{([^}]+)\}\s*=\s*(.+?)(?:;|$)")
# Matches template literal holes: ${varName}
_RE_TEMPLATE = re.compile(r"\$\{(\w+)\}")

# ── All known sink types (used to build initial taint label sets) ──────────
ALL_SINK_TYPES: set[str] = {
    "SQL-value",
    "CMD-argument",
    "HTML-content",
    "CODE-execution",
    "FILE-path",
    "HTTP-request",
}


# ── Interprocedural helper dataclass ───────────────────────────────────────


@dataclass
class _FunctionSummary:
    """Summary of taint-relevant information for a single function.

    Built during the first pass of interprocedural analysis.
    """

    name: str
    node: ast.FunctionDef | ast.AsyncFunctionDef
    param_names: list[str] = field(default_factory=list)
    # Which parameter indices receive taint when called with tainted args
    tainted_params: dict[int, TaintSource] = field(default_factory=dict)
    # Whether the function returns tainted data (and which source)
    returns_taint: TaintSource | None = None
    # Taint labels associated with the return value
    return_taint_labels: set[str] = field(default_factory=set)
    # Internal taint paths found within this function
    paths: list[TaintPath] = field(default_factory=list)


class TaintAnalyzer:
    """
    Multi-language source-to-sink taint analyzer.

    - Python: AST-based, interprocedural (single-file) with multi-label taint
    - JavaScript/TypeScript: Regex-based, multi-pass propagation

    Interprocedural analysis (Python only, Phase 1 -- single-file):
      1. Build a function summary for each function in the file.
      2. Build a call graph from function calls within the file.
      3. Propagate taint from callers to callees (argument -> parameter).
      4. Propagate taint from callee return values back to callers.

    Multi-label taint:
      Each tainted variable carries a set of sink-type labels.
      Sanitizers remove specific labels from the set.
      A variable is clean only when its label set is empty.

    Args:
        catalog: TaintCatalog instance with sources/sinks/sanitizers.
                 If None, the built-in default catalog is used.
    """

    def __init__(self, catalog: TaintCatalog | None = None, taint_config: dict[str, Any] | None = None) -> None:
        if catalog is None:
            from warden.validation.frames.security._internal.taint_catalog import (
                TaintCatalog as _TaintCatalog,
            )

            catalog = _TaintCatalog.get_default()
        self._catalog = catalog

        # Validate + clamp config (fail-fast on bad types, fallback to defaults)
        self._taint_config: dict[str, float] = validate_taint_config(taint_config)
        self._propagation_confidence: float = self._taint_config["propagation_confidence"]
        self._sanitizer_penalty: float = self._taint_config["sanitizer_penalty"]

        # Observability: log when non-default config is active
        overrides = {k: v for k, v in self._taint_config.items() if v != TAINT_DEFAULTS[k]}
        if overrides:
            logger.info("taint_config_custom_overrides", overrides=overrides)

        # Load signal inference engine (graceful -- unavailable if signals.yaml missing)
        try:
            from warden.validation.frames.security._internal.model_loader import (
                ModelPackLoader,
            )
            from warden.validation.frames.security._internal.signal_inference import (
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

        paths = self._analyze_python_interprocedural(tree, source_code)

        logger.debug("taint_analysis_complete", paths_found=len(paths))
        return paths

    # ── Python interprocedural analysis ────────────────────────────────────

    def _analyze_python_interprocedural(self, tree: ast.Module, source_code: str) -> list[TaintPath]:
        """Interprocedural taint analysis across all functions in a single file.

        Phase 1 algorithm:
          1. Collect all function definitions and build summaries.
          2. First pass: analyze each function in isolation (intra-procedural).
          3. Build call graph: for each call to a known function in the file,
             propagate taint from caller arguments to callee parameters.
          4. Re-analyze functions whose parameters gained new taint.
          5. Propagate return-value taint back to callers.
          6. Iterate until fixpoint (max 5 rounds).
        """
        # Step 1: Collect all top-level and nested function definitions
        func_nodes: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_nodes.append(node)

        if not func_nodes:
            return []

        # Build name -> summary mapping
        summaries: dict[str, _FunctionSummary] = {}
        for func_node in func_nodes:
            param_names = self._extract_param_names(func_node)
            summary = _FunctionSummary(
                name=func_node.name,
                node=func_node,
                param_names=param_names,
            )
            summaries[func_node.name] = summary

        # Step 2: First pass -- analyze each function in isolation
        # Track tainted variables at the file level for interprocedural sharing.
        # Each function gets its own tainted_vars, but we also maintain a
        # "function return taint" map for cross-function propagation.
        file_tainted_vars: dict[str, TaintSource] = {}
        # Map: function_name -> tainted_vars dict used during analysis
        func_tainted_vars: dict[str, dict[str, TaintSource]] = {}
        # Map: function_name -> taint_labels for each tainted var
        func_taint_labels: dict[str, dict[str, set[str]]] = {}

        all_paths: list[TaintPath] = []

        for fname, summary in summaries.items():
            tainted_vars: dict[str, TaintSource] = {}
            taint_labels: dict[str, set[str]] = {}
            paths = self._analyze_function_multilabel(summary.node, source_code, tainted_vars, taint_labels)
            summary.paths = paths
            func_tainted_vars[fname] = tainted_vars
            func_taint_labels[fname] = taint_labels

            # Check if function returns tainted data
            ret_source, ret_labels = self._check_function_returns(summary.node, tainted_vars, taint_labels)
            if ret_source:
                summary.returns_taint = ret_source
                summary.return_taint_labels = ret_labels

        # Step 3-6: Interprocedural propagation (fixpoint loop)
        for _round in range(5):
            changed = False

            for fname, summary in summaries.items():
                tainted_vars = func_tainted_vars[fname]
                taint_labels = func_taint_labels[fname]

                # Scan calls within this function to other file-local functions
                for node in ast.walk(summary.node):
                    if not isinstance(node, ast.Call):
                        continue

                    callee_name = self._get_dotted_name(node.func)
                    if not callee_name:
                        continue

                    # Resolve method calls: self.process(...) -> process
                    # Also handles direct calls: process(...)
                    resolved_name = callee_name
                    if resolved_name not in summaries:
                        # Try the last segment for method calls (self.foo -> foo)
                        last_segment = resolved_name.rsplit(".", 1)[-1]
                        if last_segment in summaries:
                            resolved_name = last_segment
                        else:
                            continue

                    callee = summaries[resolved_name]

                    # Propagate: caller's tainted args -> callee's params
                    for i, arg in enumerate(node.args):
                        if i >= len(callee.param_names):
                            break
                        tainted_source = self._is_tainted(arg, tainted_vars)
                        if tainted_source:
                            param_name = callee.param_names[i]
                            callee_vars = func_tainted_vars[resolved_name]
                            callee_labels = func_taint_labels[resolved_name]
                            if param_name not in callee_vars:
                                # Propagate taint to callee parameter
                                callee_vars[param_name] = TaintSource(
                                    name=tainted_source.name,
                                    node_type="interprocedural-arg",
                                    line=tainted_source.line,
                                    confidence=tainted_source.confidence * self._propagation_confidence,
                                    taint_labels=set(tainted_source.taint_labels)
                                    if tainted_source.taint_labels
                                    else set(ALL_SINK_TYPES),
                                )
                                # Propagate labels
                                arg_var_name = self._get_var_name(arg)
                                if arg_var_name and arg_var_name in taint_labels:
                                    callee_labels[param_name] = set(taint_labels[arg_var_name])
                                else:
                                    callee_labels[param_name] = set(ALL_SINK_TYPES)
                                changed = True

                    # Propagate: callee's return taint -> caller's assignment
                    if callee.returns_taint:
                        # Find the assignment target: x = callee_func(...)
                        assign_target = self._find_call_assignment_target(summary.node, node)
                        if assign_target and assign_target not in tainted_vars:
                            tainted_vars[assign_target] = TaintSource(
                                name=f"{resolved_name}()",
                                node_type="interprocedural-return",
                                line=getattr(node, "lineno", 0),
                                confidence=callee.returns_taint.confidence * self._propagation_confidence,
                                taint_labels=set(callee.return_taint_labels)
                                if callee.return_taint_labels
                                else set(ALL_SINK_TYPES),
                            )
                            taint_labels[assign_target] = (
                                set(callee.return_taint_labels) if callee.return_taint_labels else set(ALL_SINK_TYPES)
                            )
                            changed = True

            if not changed:
                break

            # Re-analyze functions that gained new taint
            for fname, summary in summaries.items():
                tainted_vars = func_tainted_vars[fname]
                taint_labels = func_taint_labels[fname]
                paths = self._analyze_function_multilabel(summary.node, source_code, tainted_vars, taint_labels)
                summary.paths = paths

                # Re-check return taint
                ret_source, ret_labels = self._check_function_returns(summary.node, tainted_vars, taint_labels)
                if ret_source:
                    summary.returns_taint = ret_source
                    summary.return_taint_labels = ret_labels

        # Collect all paths from all functions
        for summary in summaries.values():
            all_paths.extend(summary.paths)

        return all_paths

    def _extract_param_names(self, func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
        """Extract parameter names from a function definition."""
        params: list[str] = []
        for arg in func_node.args.args:
            if arg.arg != "self" and arg.arg != "cls":
                params.append(arg.arg)
        return params

    def _check_function_returns(
        self,
        func_node: ast.FunctionDef | ast.AsyncFunctionDef,
        tainted_vars: dict[str, TaintSource],
        taint_labels: dict[str, set[str]],
    ) -> tuple[TaintSource | None, set[str]]:
        """Check if a function returns tainted data.

        Returns (TaintSource, taint_labels) if the return value is tainted,
        or (None, set()) otherwise.
        """
        for node in ast.walk(func_node):
            if isinstance(node, ast.Return) and node.value is not None:
                tainted = self._is_tainted(node.value, tainted_vars)
                if tainted:
                    var_name = self._get_var_name(node.value)
                    labels = set()
                    if var_name and var_name in taint_labels:
                        labels = set(taint_labels[var_name])
                    elif tainted.taint_labels:
                        labels = set(tainted.taint_labels)
                    else:
                        labels = set(ALL_SINK_TYPES)
                    return tainted, labels
        return None, set()

    def _find_call_assignment_target(
        self,
        func_node: ast.FunctionDef | ast.AsyncFunctionDef,
        call_node: ast.Call,
    ) -> str | None:
        """Find the variable name assigned from a call expression.

        Given `x = some_func(...)`, returns "x".
        """
        for node in ast.walk(func_node):
            if isinstance(node, ast.Assign):
                if node.value is call_node:
                    if len(node.targets) == 1:
                        return self._get_var_name(node.targets[0])
        return None

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

        # Pass 1 - direct source assignments
        for line_num, line in enumerate(lines, 1):
            self._js_collect_sources(line, line_num, tainted_vars)

        # Pass 2 - propagation (handles `const id = query.id` after `const query = req.query`)
        for _ in range(5):
            changed = False
            for line_num, line in enumerate(lines, 1):
                if self._js_propagate(line, line_num, tainted_vars):
                    changed = True
            if not changed:
                break

        # Pass 3 - sink detection
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
                            name=value_expr,
                            node_type="assignment",
                            line=line_num,
                            taint_labels=set(ALL_SINK_TYPES),
                        )
                    break

        # Destructuring: const { id, name } = req.body
        for m in _RE_DESTRUCT.finditer(stripped):
            value_expr = m.group(2).strip()
            for src in self._catalog.sources.get("javascript", set()):
                if src in value_expr:
                    for raw_field in m.group(1).split(","):
                        # Support `{ a: b }` rename -- take the alias (b)
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
        """Detect tainted variables flowing into JS sinks on a single line."""
        if not tainted_vars:
            return []

        stripped = line.strip()
        paths: list[TaintPath] = []

        for sink_name, sink_type in self._catalog.sinks.items():
            # -- Assignment-style sinks: element.innerHTML = taintedVar --
            if sink_name in self._catalog.assign_sinks:
                pattern = re.compile(r"\." + re.escape(sink_name) + r"\s*=\s*(.+?)(?:;|$)")
                for m in pattern.finditer(stripped):
                    args_str = m.group(1)
                    paths.extend(self._js_check_args(args_str, sink_name, sink_type, line_num, tainted_vars))
                continue

            # -- Call-style sinks: db.query(...), eval(...) --
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
                # Multi-label: compute remaining labels after sanitization
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
        """Detect known JS sanitizer calls in an argument string."""
        sanitizers: list[str] = []
        for san in self._catalog.sanitizers.get(sink_type, set()):
            if san in args_str:
                sanitizers.append(san)
        return sanitizers

    # ── Python AST analysis (multi-label) ──────────────────────────────────

    def _analyze_function_multilabel(
        self,
        func_node: ast.FunctionDef | ast.AsyncFunctionDef,
        source: str,
        tainted_vars: dict[str, TaintSource],
        taint_labels: dict[str, set[str]],
    ) -> list[TaintPath]:
        """Analyze a single function for taint flows with multi-label tracking.

        Args:
            func_node: The function AST node.
            source: Full source code string.
            tainted_vars: Mutable dict of variable name -> TaintSource.
                          Pre-populated with interprocedural taint.
            taint_labels: Mutable dict of variable name -> set of active
                          sink-type labels.  Pre-populated with interprocedural labels.

        Returns:
            List of detected TaintPath objects.
        """
        # Track transformations on tainted data
        transformations: dict[str, list[str]] = {}
        # Find sinks consuming tainted data
        paths: list[TaintPath] = []

        for node in ast.walk(func_node):
            # Detect taint sources in assignments
            if isinstance(node, ast.Assign):
                self._check_assignment_for_sources_multilabel(node, tainted_vars, taint_labels)

            # Detect taint in augmented assignments
            if isinstance(node, ast.AugAssign):
                self._check_aug_assignment_multilabel(node, tainted_vars, taint_labels)

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

                            # Check for sanitizers (per-sink-type)
                            sanitizers = self._detect_sanitizers(arg, sink.sink_type)

                            # Multi-label: compute active labels
                            var_name = self._get_var_name(arg)
                            if var_name and var_name in taint_labels:
                                active_labels = set(taint_labels[var_name])
                            elif tainted_source.taint_labels:
                                active_labels = set(tainted_source.taint_labels)
                            else:
                                active_labels = set(ALL_SINK_TYPES)

                            # Sanitizers remove specific labels
                            if sanitizers:
                                active_labels.discard(sink.sink_type)

                            is_sanitized = sink.sink_type not in active_labels

                            # Get transformations
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
                                taint_labels=active_labels,
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

    def _check_assignment_for_sources_multilabel(
        self,
        node: ast.Assign,
        tainted_vars: dict[str, TaintSource],
        taint_labels: dict[str, set[str]],
    ) -> None:
        """Check if an assignment introduces tainted data (multi-label aware)."""
        source = self._identify_source(node.value)
        if source:
            for target in node.targets:
                var_name = self._get_var_name(target)
                if var_name:
                    tainted_vars[var_name] = source
                    # New source -> all sink types are potential labels
                    if source.taint_labels:
                        taint_labels[var_name] = set(source.taint_labels)
                    else:
                        taint_labels[var_name] = set(ALL_SINK_TYPES)

        # Propagate taint through assignments: x = tainted_var
        if not source:
            tainted = self._is_tainted(node.value, tainted_vars)
            if tainted:
                for target in node.targets:
                    var_name = self._get_var_name(target)
                    if var_name:
                        tainted_vars[var_name] = tainted
                        # Inherit labels from the source variable
                        src_var = self._get_var_name(node.value)
                        if src_var and src_var in taint_labels:
                            taint_labels[var_name] = set(taint_labels[src_var])
                        elif tainted.taint_labels:
                            taint_labels[var_name] = set(tainted.taint_labels)
                        else:
                            taint_labels[var_name] = set(ALL_SINK_TYPES)

                        # Check if the RHS passes through a sanitizer
                        self._apply_sanitizer_labels(node.value, var_name, taint_labels)

    def _apply_sanitizer_labels(
        self,
        node: ast.expr,
        var_name: str,
        taint_labels: dict[str, set[str]],
    ) -> None:
        """If the expression passes through a sanitizer call, remove the
        corresponding label from the variable's taint_labels."""
        if not isinstance(node, ast.Call):
            return
        func_name = self._get_dotted_name(node.func)
        if not func_name:
            return

        for sink_type, sanitizer_set in self._catalog.sanitizers.items():
            for san in sanitizer_set:
                if san in func_name:
                    if var_name in taint_labels:
                        taint_labels[var_name].discard(sink_type)

    def _check_aug_assignment_multilabel(
        self,
        node: ast.AugAssign,
        tainted_vars: dict[str, TaintSource],
        taint_labels: dict[str, set[str]],
    ) -> None:
        """Check augmented assignments (+=, etc.) for taint propagation (multi-label)."""
        var_name = self._get_var_name(node.target)
        if var_name and var_name in tainted_vars:
            return  # Already tainted

        source = self._identify_source(node.value)
        if source and var_name:
            tainted_vars[var_name] = source
            if source.taint_labels:
                taint_labels[var_name] = set(source.taint_labels)
            else:
                taint_labels[var_name] = set(ALL_SINK_TYPES)

    # ── Legacy single-function analysis (kept for reference/fallback) ──────

    def _analyze_function(self, func_node: ast.FunctionDef | ast.AsyncFunctionDef, source: str) -> list[TaintPath]:
        """Analyze a single function for taint flows (legacy, non-multi-label).

        Delegates to the new multi-label implementation with fresh state.
        """
        tainted_vars: dict[str, TaintSource] = {}
        taint_labels: dict[str, set[str]] = {}
        return self._analyze_function_multilabel(func_node, source, tainted_vars, taint_labels)

    def _check_assignment_for_sources(self, node: ast.Assign, tainted_vars: dict[str, TaintSource]) -> None:
        """Check if an assignment introduces tainted data (legacy wrapper)."""
        taint_labels: dict[str, set[str]] = {}
        self._check_assignment_for_sources_multilabel(node, tainted_vars, taint_labels)

    def _check_aug_assignment(self, node: ast.AugAssign, tainted_vars: dict[str, TaintSource]) -> None:
        """Check augmented assignments (+=, etc.) for taint propagation (legacy wrapper)."""
        taint_labels: dict[str, set[str]] = {}
        self._check_aug_assignment_multilabel(node, tainted_vars, taint_labels)

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
                        taint_labels=set(ALL_SINK_TYPES),
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
                            taint_labels=set(ALL_SINK_TYPES),
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
                            taint_labels=set(ALL_SINK_TYPES),
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
                            taint_labels=set(ALL_SINK_TYPES),
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
                            taint_labels=set(ALL_SINK_TYPES),
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
                    taint_labels=set(ALL_SINK_TYPES),
                )

        return None

    def _identify_sink(self, node: ast.Call) -> tuple[str, str] | None:
        """Check if a call is a known sink. Returns (name, sink_type) or None."""
        func_name = self._get_dotted_name(node.func)
        if func_name:
            # Step 1: explicit catalog lookup -- segment-aware matching to prevent
            # false positives like "open" matching "urllib.request.urlopen".
            # Prefer longer (more specific) patterns by checking all, collecting best.
            best: tuple[str, str] | None = None
            for sink_pattern, sink_type in self._catalog.sinks.items():
                # Exact match or dot-boundary suffix (e.g. "cursor.execute" matches
                # "db.cursor.execute" but "open" does NOT match "urlopen").
                if func_name == sink_pattern or func_name.endswith("." + sink_pattern):
                    if best is None or len(sink_pattern) > len(best[0]):
                        best = (sink_pattern, sink_type)
            if best:
                return (func_name, best[1])

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

        # Check function calls: taint flows through call arguments.
        # Handles .format(tainted), html.escape(tainted), any_func(tainted), etc.
        if isinstance(node, ast.Call):
            for arg in node.args:
                result = self._is_tainted(arg, tainted_vars)
                if result:
                    return result
            for kw in node.keywords:
                result = self._is_tainted(kw.value, tainted_vars)
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

        # Pass 1 - direct source assignments
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

        # Pass 2 - propagation
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

        # Pass 3 - sink detection
        paths: list[TaintPath] = []
        for line_num, line in enumerate(lines, 1):
            paths.extend(self._go_find_sinks(line, line_num, tainted_vars))

        logger.debug("go_taint_analysis_complete", paths_found=len(paths))
        return paths

    def _go_find_sinks(self, line: str, line_num: int, tainted_vars: dict[str, TaintSource]) -> list[TaintPath]:
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

        # Pass 1 - direct source assignments
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

        # Pass 2 - propagation
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

        # Pass 3 - sink detection
        paths: list[TaintPath] = []
        for line_num, line in enumerate(lines, 1):
            paths.extend(self._java_find_sinks(line, line_num, tainted_vars))

        logger.debug("java_taint_analysis_complete", paths_found=len(paths))
        return paths

    def _java_find_sinks(self, line: str, line_num: int, tainted_vars: dict[str, TaintSource]) -> list[TaintPath]:
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
