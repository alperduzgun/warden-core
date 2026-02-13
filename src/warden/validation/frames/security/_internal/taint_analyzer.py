"""
Source-to-Sink Taint Analysis Engine.

Pareto cut: Single-function scope taint tracking.
Cross-function and cross-file analysis deferred to future iterations.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Any

from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)


@dataclass
class TaintSource:
    """A source of tainted (user-controlled) data."""
    name: str           # "request.args"
    node_type: str      # "call", "attribute", "subscript"
    line: int
    confidence: float = 0.9


@dataclass
class TaintSink:
    """A dangerous sink that should not receive tainted data."""
    name: str           # "cursor.execute"
    sink_type: str      # "SQL-value", "CMD-argument", "HTML-content"
    line: int


@dataclass
class TaintPath:
    """A detected taint flow from source to sink."""
    source: TaintSource
    sink: TaintSink
    transformations: list[str] = field(default_factory=list)    # ["f-string", "str.format"]
    sanitizers: list[str] = field(default_factory=list)         # ["html.escape"]
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
    "request.args", "request.form", "request.json", "request.data",
    "request.values", "request.cookies", "request.headers",
    "request.get_json", "request.files",
    "input", "sys.argv", "os.environ", "os.getenv",
    "stdin", "sys.stdin",
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


class TaintAnalyzer:
    """
    Single-function scope taint analyzer using Python AST.

    Analyzes Python source code for taint flows from sources to sinks
    within individual function bodies. Does NOT track cross-function
    or cross-file flows (deferred to future iterations).
    """

    def analyze(self, source_code: str, language: str = "python") -> list[TaintPath]:
        """
        Analyze source code for taint paths.

        Args:
            source_code: Source code string
            language: Programming language (currently only "python" supported)

        Returns:
            List of detected TaintPath objects
        """
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

    def _analyze_function(
        self, func_node: ast.FunctionDef | ast.AsyncFunctionDef, source: str
    ) -> list[TaintPath]:
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
                                confidence *= 0.3  # Reduce confidence if sanitized

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

    def _check_assignment_for_sources(
        self, node: ast.Assign, tainted_vars: dict[str, TaintSource]
    ) -> None:
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

    def _check_aug_assignment(
        self, node: ast.AugAssign, tainted_vars: dict[str, TaintSource]
    ) -> None:
        """Check augmented assignments (+=, etc.) for taint propagation."""
        var_name = self._get_var_name(node.target)
        if var_name and var_name in tainted_vars:
            return  # Already tainted

        source = self._identify_source(node.value)
        if source and var_name:
            tainted_vars[var_name] = source

    def _identify_source(self, node: ast.expr) -> TaintSource | None:
        """Check if an expression is a known taint source."""
        name = self._get_dotted_name(node)
        if name:
            for src_pattern in TAINT_SOURCES:
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
                for src_pattern in TAINT_SOURCES:
                    if func_name.startswith(src_pattern) or src_pattern in func_name:
                        return TaintSource(
                            name=func_name,
                            node_type="call",
                            line=getattr(node, "lineno", 0),
                        )

        # Check subscript (e.g., request.args['id'])
        if isinstance(node, ast.Subscript):
            value_name = self._get_dotted_name(node.value)
            if value_name:
                for src_pattern in TAINT_SOURCES:
                    if value_name.startswith(src_pattern):
                        return TaintSource(
                            name=value_name,
                            node_type="subscript",
                            line=getattr(node, "lineno", 0),
                        )

        return None

    def _identify_sink(self, node: ast.Call) -> tuple[str, str] | None:
        """Check if a call is a known sink. Returns (name, sink_type) or None."""
        func_name = self._get_dotted_name(node.func)
        if func_name:
            for sink_pattern, sink_type in TAINT_SINKS.items():
                if func_name.endswith(sink_pattern) or sink_pattern in func_name:
                    return (func_name, sink_type)
        return None

    def _is_tainted(
        self, node: ast.expr, tainted_vars: dict[str, TaintSource]
    ) -> TaintSource | None:
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
        valid_sanitizers = KNOWN_SANITIZERS.get(sink_type, set())

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
