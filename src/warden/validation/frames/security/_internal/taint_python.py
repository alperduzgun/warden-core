from __future__ import annotations

import ast
from typing import Any

from warden.shared.infrastructure.logging import get_logger
from warden.validation.frames.security._internal.taint_analyzer import (
    ALL_SINK_TYPES,
    TaintPath,
    TaintSink,
    TaintSource,
    _FunctionSummary,
)
from warden.validation.frames.security._internal.taint_catalog import TaintCatalog

logger = get_logger(__name__)


class PythonTaintStrategy:
    def __init__(self, catalog: TaintCatalog, taint_config: dict[str, Any]) -> None:
        self._catalog = catalog
        self._taint_config = taint_config
        self._propagation_confidence: float = taint_config["propagation_confidence"]
        self._sanitizer_penalty: float = taint_config["sanitizer_penalty"]

        try:
            from warden.validation.frames.security._internal.model_loader import (
                ModelPackLoader,
            )
            from warden.validation.frames.security._internal.signal_inference import (
                SignalInferenceEngine,
            )

            signals_data = ModelPackLoader.load_signals()
            self._signal_engine: Any | None = SignalInferenceEngine(
                signals_data, config=self._taint_config
            )
        except Exception:
            self._signal_engine = None

    def analyze(self, source_code: str) -> list[TaintPath]:
        try:
            tree = ast.parse(source_code)
        except SyntaxError as e:
            logger.debug("taint_analysis_parse_error", error=str(e))
            return []

        paths = self._analyze_python_interprocedural(tree, source_code)

        logger.debug("taint_analysis_complete", paths_found=len(paths))
        return paths

    def _analyze_python_interprocedural(self, tree: ast.Module, source_code: str) -> list[TaintPath]:
        func_nodes: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_nodes.append(node)

        if not func_nodes:
            return []

        summaries: dict[str, _FunctionSummary] = {}
        for func_node in func_nodes:
            param_names = self._extract_param_names(func_node)
            summary = _FunctionSummary(
                name=func_node.name,
                node=func_node,
                param_names=param_names,
            )
            summaries[func_node.name] = summary

        file_tainted_vars: dict[str, TaintSource] = {}
        func_tainted_vars: dict[str, dict[str, TaintSource]] = {}
        func_taint_labels: dict[str, dict[str, set[str]]] = {}

        all_paths: list[TaintPath] = []

        for fname, summary in summaries.items():
            tainted_vars: dict[str, TaintSource] = {}
            taint_labels: dict[str, set[str]] = {}
            paths = self._analyze_function_multilabel(summary.node, source_code, tainted_vars, taint_labels)
            summary.paths = paths
            func_tainted_vars[fname] = tainted_vars
            func_taint_labels[fname] = taint_labels

            ret_source, ret_labels = self._check_function_returns(summary.node, tainted_vars, taint_labels)
            if ret_source:
                summary.returns_taint = ret_source
                summary.return_taint_labels = ret_labels

        for _round in range(5):
            changed = False

            for fname, summary in summaries.items():
                tainted_vars = func_tainted_vars[fname]
                taint_labels = func_taint_labels[fname]

                for node in ast.walk(summary.node):
                    if not isinstance(node, ast.Call):
                        continue

                    callee_name = self._get_dotted_name(node.func)
                    if not callee_name:
                        continue

                    resolved_name = callee_name
                    if resolved_name not in summaries:
                        last_segment = resolved_name.rsplit(".", 1)[-1]
                        if last_segment in summaries:
                            resolved_name = last_segment
                        else:
                            continue

                    callee = summaries[resolved_name]

                    for i, arg in enumerate(node.args):
                        if i >= len(callee.param_names):
                            break
                        tainted_source = self._is_tainted(arg, tainted_vars)
                        if tainted_source:
                            param_name = callee.param_names[i]
                            callee_vars = func_tainted_vars[resolved_name]
                            callee_labels = func_taint_labels[resolved_name]
                            if param_name not in callee_vars:
                                callee_vars[param_name] = TaintSource(
                                    name=tainted_source.name,
                                    node_type="interprocedural-arg",
                                    line=tainted_source.line,
                                    confidence=tainted_source.confidence * self._propagation_confidence,
                                    taint_labels=set(tainted_source.taint_labels)
                                    if tainted_source.taint_labels
                                    else set(ALL_SINK_TYPES),
                                )
                                arg_var_name = self._get_var_name(arg)
                                if arg_var_name and arg_var_name in taint_labels:
                                    callee_labels[param_name] = set(taint_labels[arg_var_name])
                                else:
                                    callee_labels[param_name] = set(ALL_SINK_TYPES)
                                changed = True

                    if callee.returns_taint:
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

            for fname, summary in summaries.items():
                tainted_vars = func_tainted_vars[fname]
                taint_labels = func_taint_labels[fname]
                paths = self._analyze_function_multilabel(summary.node, source_code, tainted_vars, taint_labels)
                summary.paths = paths

                ret_source, ret_labels = self._check_function_returns(summary.node, tainted_vars, taint_labels)
                if ret_source:
                    summary.returns_taint = ret_source
                    summary.return_taint_labels = ret_labels

        for summary in summaries.values():
            all_paths.extend(summary.paths)

        return all_paths

    def _extract_param_names(self, func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
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
        for node in ast.walk(func_node):
            if isinstance(node, ast.Assign):
                if node.value is call_node:
                    if len(node.targets) == 1:
                        return self._get_var_name(node.targets[0])
        return None

    def _analyze_function_multilabel(
        self,
        func_node: ast.FunctionDef | ast.AsyncFunctionDef,
        source: str,
        tainted_vars: dict[str, TaintSource],
        taint_labels: dict[str, set[str]],
    ) -> list[TaintPath]:
        transformations: dict[str, list[str]] = {}
        paths: list[TaintPath] = []

        for node in ast.walk(func_node):
            if isinstance(node, ast.Assign):
                self._check_assignment_for_sources_multilabel(node, tainted_vars, taint_labels)

            if isinstance(node, ast.AugAssign):
                self._check_aug_assignment_multilabel(node, tainted_vars, taint_labels)

            if isinstance(node, ast.Call):
                sink_info = self._identify_sink(node)
                if sink_info:
                    for arg in node.args:
                        tainted_source = self._is_tainted(arg, tainted_vars)
                        if tainted_source:
                            sink = TaintSink(
                                name=sink_info[0],
                                sink_type=sink_info[1],
                                line=node.lineno,
                            )

                            sanitizers = self._detect_sanitizers(arg, sink.sink_type)

                            var_name = self._get_var_name(arg)
                            if var_name and var_name in taint_labels:
                                active_labels = set(taint_labels[var_name])
                            elif tainted_source.taint_labels:
                                active_labels = set(tainted_source.taint_labels)
                            else:
                                active_labels = set(ALL_SINK_TYPES)

                            if sanitizers:
                                active_labels.discard(sink.sink_type)

                            is_sanitized = sink.sink_type not in active_labels

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

            if isinstance(node, ast.JoinedStr):
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
        source = self._identify_source(node.value)
        if source:
            for target in node.targets:
                var_name = self._get_var_name(target)
                if var_name:
                    tainted_vars[var_name] = source
                    if source.taint_labels:
                        taint_labels[var_name] = set(source.taint_labels)
                    else:
                        taint_labels[var_name] = set(ALL_SINK_TYPES)

        if not source:
            tainted = self._is_tainted(node.value, tainted_vars)
            if tainted:
                for target in node.targets:
                    var_name = self._get_var_name(target)
                    if var_name:
                        tainted_vars[var_name] = tainted
                        src_var = self._get_var_name(node.value)
                        if src_var and src_var in taint_labels:
                            taint_labels[var_name] = set(taint_labels[src_var])
                        elif tainted.taint_labels:
                            taint_labels[var_name] = set(tainted.taint_labels)
                        else:
                            taint_labels[var_name] = set(ALL_SINK_TYPES)

                        self._apply_sanitizer_labels(node.value, var_name, taint_labels)

    def _apply_sanitizer_labels(
        self,
        node: ast.expr,
        var_name: str,
        taint_labels: dict[str, set[str]],
    ) -> None:
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
        var_name = self._get_var_name(node.target)
        if var_name and var_name in tainted_vars:
            return

        source = self._identify_source(node.value)
        if source and var_name:
            tainted_vars[var_name] = source
            if source.taint_labels:
                taint_labels[var_name] = set(source.taint_labels)
            else:
                taint_labels[var_name] = set(ALL_SINK_TYPES)

    def _analyze_function(self, func_node: ast.FunctionDef | ast.AsyncFunctionDef, source: str) -> list[TaintPath]:
        tainted_vars: dict[str, TaintSource] = {}
        taint_labels: dict[str, set[str]] = {}
        return self._analyze_function_multilabel(func_node, source, tainted_vars, taint_labels)

    def _check_assignment_for_sources(self, node: ast.Assign, tainted_vars: dict[str, TaintSource]) -> None:
        taint_labels: dict[str, set[str]] = {}
        self._check_assignment_for_sources_multilabel(node, tainted_vars, taint_labels)

    def _check_aug_assignment(self, node: ast.AugAssign, tainted_vars: dict[str, TaintSource]) -> None:
        taint_labels: dict[str, set[str]] = {}
        self._check_aug_assignment_multilabel(node, tainted_vars, taint_labels)

    def _identify_source(self, node: ast.expr) -> TaintSource | None:
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
        func_name = self._get_dotted_name(node.func)
        if func_name:
            best: tuple[str, str] | None = None
            for sink_pattern, sink_type in self._catalog.sinks.items():
                if func_name == sink_pattern or func_name.endswith("." + sink_pattern):
                    if best is None or len(sink_pattern) > len(best[0]):
                        best = (sink_pattern, sink_type)
            if best:
                return (func_name, best[1])

            if self._signal_engine and self._signal_engine.is_available():
                param_names = [kw.arg for kw in node.keywords if kw.arg]
                parts = func_name.split(".")
                module_hint = ".".join(parts[:-1]) if len(parts) > 1 else ""
                inferred = self._signal_engine.infer_sink(func_name, param_names, module_hint)
                if inferred:
                    sink_type, _ = inferred
                    return (func_name, sink_type)

        return None

    def _is_tainted(self, node: ast.expr, tainted_vars: dict[str, TaintSource]) -> TaintSource | None:
        var_name = self._get_var_name(node)
        if var_name and var_name in tainted_vars:
            return tainted_vars[var_name]

        source = self._identify_source(node)
        if source:
            return source

        if isinstance(node, ast.JoinedStr):
            for val in node.values:
                if isinstance(val, ast.FormattedValue):
                    result = self._is_tainted(val.value, tainted_vars)
                    if result:
                        return result

        if isinstance(node, ast.BinOp):
            left = self._is_tainted(node.left, tainted_vars)
            if left:
                return left
            right = self._is_tainted(node.right, tainted_vars)
            if right:
                return right

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
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            value = self._get_dotted_name(node.value)
            if value:
                return f"{value}.{node.attr}"
            return node.attr
        return None

    def _get_var_name(self, node: ast.expr) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return self._get_dotted_name(node)
        return None
