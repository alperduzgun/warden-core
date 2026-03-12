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
            from warden.validation.frames.security._internal.taint_js import JsTaintStrategy

            return JsTaintStrategy(self._catalog, self._taint_config).analyze(source_code)

        if language == "go":
            from warden.validation.frames.security._internal.taint_go import GoTaintStrategy

            return GoTaintStrategy(self._catalog, self._taint_config).analyze(source_code)

        if language == "java":
            from warden.validation.frames.security._internal.taint_java import JavaTaintStrategy

            return JavaTaintStrategy(self._catalog, self._taint_config).analyze(source_code)

        if language != "python":
            logger.debug("taint_analysis_unsupported_language", language=language)
            return []

        from warden.validation.frames.security._internal.taint_python import PythonTaintStrategy

        strategy = PythonTaintStrategy(self._catalog, self._taint_config)
        # Share the already-loaded signal engine to avoid double-loading
        strategy._signal_engine = self._signal_engine
        return strategy.analyze(source_code)

