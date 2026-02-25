"""
DataDependencyBuilder — builds DataDependencyGraph by scanning Python AST.

Walks Python source files and records every attribute access on a known
pipeline-context variable (e.g. ``context.code_graph = …`` as a WriteNode,
``x = context.code_graph`` as a ReadNode).

False-positive suppression
--------------------------
Several access patterns look like context field writes but do **not** constitute
data-flow dependencies:

* ``context.metadata["key"] = value`` — dict-item assignment, not a field write.
* ``context._lock`` — internal threading primitive, not a pipeline field.
* ``context.__class__`` — dunder attribute access, no semantic meaning for DFG.
* ``context.findings.append(x)`` — call on a field (read), not a write.

All of the above are filtered out before creating WriteNode / ReadNode entries.
"""

from __future__ import annotations

import ast
from pathlib import Path

from warden.analysis.domain.data_dependency_graph import (
    DataDependencyGraph,
    ReadNode,
    WriteNode,
)
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Variable names that represent the pipeline context inside frames / executors.
PIPELINE_CTX_NAMES: frozenset[str] = frozenset(
    {
        "context",
        "ctx",
        "pipeline_context",
        "pipe_ctx",
        "pc",
    }
)

# Field name suffixes/patterns that look like context writes but are not
# meaningful pipeline data fields.  Checked via str.startswith / __contains__.
FP_FIELD_PATTERNS: tuple[str, ...] = (
    "_lock",  # threading.Lock — internal implementation detail
    "__",  # dunder attributes — Python internals
    "metadata",  # generic dict, not a typed pipeline field
)

# Glob pattern for PipelineContext source files (used for init_fields extraction)
_PIPELINE_CONTEXT_GLOB: str = "pipeline_context.py"


def _is_fp_field(field_name: str) -> bool:
    """Return True when *field_name* matches a known false-positive pattern.

    Args:
        field_name: The unqualified field name (e.g. ``"_lock"``).

    Returns:
        ``True`` when the field should be ignored.
    """
    for pattern in FP_FIELD_PATTERNS:
        if field_name.startswith(pattern) or pattern in field_name:
            return True
    return False


# ---------------------------------------------------------------------------
# AST Visitor
# ---------------------------------------------------------------------------


class DDGVisitor(ast.NodeVisitor):
    """AST visitor that detects ``context.X`` reads and writes.

    Records:
    * Assignments to ``context.X`` → :class:`WriteNode`
    * Attribute reads of ``context.X`` → :class:`ReadNode`

    Special cases handled:
    * ``context.metadata["key"] = value`` — skipped (subscript target).
    * ``context._lock`` / ``context.__dunder__`` — skipped (FP patterns).
    * ``context.findings.append(x)`` — recorded as ReadNode (attribute read),
      not a WriteNode.
    * Nested function / async-function scopes are tracked correctly.
    * ``if`` / ``try`` blocks increment ``_conditional_depth`` so WriteNodes
      inside them are marked ``is_conditional=True``.
    """

    def __init__(self, file_path: str, ddg: DataDependencyGraph) -> None:
        self.file_path = file_path
        self.ddg = ddg
        self._current_func: str = "<module>"
        self._conditional_depth: int = 0
        # Stack to restore function names when exiting nested scopes
        self._func_stack: list[str] = []

    # ------------------------------------------------------------------
    # Function scope tracking
    # ------------------------------------------------------------------

    def _enter_func(self, name: str) -> None:
        self._func_stack.append(self._current_func)
        self._current_func = name

    def _exit_func(self) -> None:
        if self._func_stack:
            self._current_func = self._func_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._enter_func(node.name)
        self.generic_visit(node)
        self._exit_func()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._enter_func(node.name)
        self.generic_visit(node)
        self._exit_func()

    # ------------------------------------------------------------------
    # Conditional depth tracking
    # ------------------------------------------------------------------

    def visit_If(self, node: ast.If) -> None:
        self._conditional_depth += 1
        self.generic_visit(node)
        self._conditional_depth -= 1

    def visit_Try(self, node: ast.Try) -> None:
        self._conditional_depth += 1
        self.generic_visit(node)
        self._conditional_depth -= 1

    # ------------------------------------------------------------------
    # Write detection
    # ------------------------------------------------------------------

    def _try_record_write(self, target: ast.expr) -> None:
        """Attempt to record *target* as a WriteNode if it's ``ctx.field``.

        Skips subscript assignments (``ctx.metadata["key"] = v``) and any
        target that is a chained attribute deeper than one level
        (``ctx.findings.append`` — that would be a call, not handled here).
        """
        if not isinstance(target, ast.Attribute):
            return
        value_node = target.value
        # Must be a plain Name node (not a chained attribute)
        if not isinstance(value_node, ast.Name):
            return
        if value_node.id not in PIPELINE_CTX_NAMES:
            return
        field_name = target.attr
        if _is_fp_field(field_name):
            return
        qualified = f"{value_node.id}.{field_name}"
        write_node = WriteNode(
            field_name=qualified,
            file_path=self.file_path,
            line_no=target.lineno,
            func_name=self._current_func,
            is_conditional=self._conditional_depth > 0,
        )
        self.ddg.writes[qualified].append(write_node)

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            # Skip subscript assignments: ctx.metadata["key"] = val
            # The target would be ast.Subscript here; we only care about
            # ast.Attribute targets.
            if isinstance(target, ast.Subscript):
                # Recurse into value anyway for read detection
                self.visit(target.value)
            else:
                self._try_record_write(target)
        # Visit the right-hand side for reads
        self.visit(node.value)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        # ``ctx.field += value`` — treat as both read and write
        self._try_record_write(node.target)
        self.visit(node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        # ``ctx.field: T = value``
        if node.target is not None:
            self._try_record_write(node.target)
        if node.value is not None:
            self.visit(node.value)

    # ------------------------------------------------------------------
    # Read detection
    # ------------------------------------------------------------------

    def visit_Attribute(self, node: ast.Attribute) -> None:
        """Detect ``ctx.field`` reads.

        Only records the *first* level of attribute access:
        ``ctx.code_graph.method()`` → ReadNode("context.code_graph", ...)
        The deeper ``.method`` is ignored as it belongs to the field's type.
        """
        value_node = node.value
        if isinstance(value_node, ast.Name) and value_node.id in PIPELINE_CTX_NAMES:
            field_name = node.attr
            if not _is_fp_field(field_name):
                qualified = f"{value_node.id}.{field_name}"
                read_node = ReadNode(
                    field_name=qualified,
                    file_path=self.file_path,
                    line_no=node.lineno,
                    func_name=self._current_func,
                )
                self.ddg.reads[qualified].append(read_node)
        # Continue descent so nested reads are also found
        self.generic_visit(node)


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


class DataDependencyBuilder:
    """Builds DataDependencyGraph by scanning Python source files with AST.

    Usage::

        builder = DataDependencyBuilder(project_root)
        ddg = builder.build(file_paths)

    The builder is stateless between ``build`` calls — each call returns a
    fresh :class:`DataDependencyGraph`.

    Args:
        project_root: Root directory of the project.  Used to locate
            ``PipelineContext`` for ``init_fields`` extraction.
    """

    def __init__(self, project_root: str | Path) -> None:
        self.project_root = Path(project_root)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(self, file_paths: list[Path]) -> DataDependencyGraph:
        """Parse all given files and return accumulated DDG.

        Args:
            file_paths: Python source files to analyse.

        Returns:
            A populated :class:`DataDependencyGraph`.
        """
        ddg = DataDependencyGraph()
        for fp in file_paths:
            self._parse_file(fp, ddg)
        ddg.init_fields = self._extract_init_fields()
        return ddg

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parse_file(self, file_path: Path, ddg: DataDependencyGraph) -> None:
        """Parse a single file and accumulate nodes into *ddg*.

        Errors (syntax errors, I/O errors) are logged and silently swallowed
        so that a single bad file does not abort the entire build.

        Args:
            file_path: Python source file to parse.
            ddg: Graph to accumulate results into.
        """
        try:
            source = file_path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=str(file_path))
        except SyntaxError as exc:
            logger.debug(
                "ddg_builder.syntax_error",
                file=str(file_path),
                error=str(exc),
            )
            return
        except OSError as exc:
            logger.debug(
                "ddg_builder.io_error",
                file=str(file_path),
                error=str(exc),
            )
            return

        visitor = DDGVisitor(file_path=str(file_path), ddg=ddg)
        visitor.visit(tree)

    def _extract_init_fields(self) -> set[str]:
        """Extract Optional fields declared in the PipelineContext dataclass.

        Scans the project for ``pipeline_context.py`` and finds field
        declarations matching one of:

        * ``field_name: X | None = None``
        * ``field_name: Optional[X] = None``
        * ``field_name: Any | None = None``

        Returns field names qualified with ``"context."`` prefix, e.g.
        ``{"context.code_graph", "context.gap_report", ...}``.

        Returns:
            Set of qualified field names declared as Optional in PipelineContext.
        """
        init_fields: set[str] = set()
        # Locate pipeline_context.py relative to project root
        candidates = list(self.project_root.rglob(_PIPELINE_CONTEXT_GLOB))
        if not candidates:
            return init_fields

        for pc_file in candidates:
            try:
                source = pc_file.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(source, filename=str(pc_file))
            except (SyntaxError, OSError):
                continue

            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                if node.name != "PipelineContext":
                    continue
                for item in ast.walk(node):
                    if not isinstance(item, ast.AnnAssign):
                        continue
                    # Extract field name
                    target = item.target
                    if not isinstance(target, ast.Name):
                        continue
                    field_id = target.id
                    # Skip private / dunder / non-pipeline fields
                    if _is_fp_field(field_id):
                        continue
                    # Check if annotation indicates Optional (None default or | None)
                    if _is_optional_annotation(item.annotation):
                        init_fields.add(f"context.{field_id}")

        return init_fields


# ---------------------------------------------------------------------------
# Annotation helpers
# ---------------------------------------------------------------------------


def _is_optional_annotation(annotation: ast.expr | None) -> bool:
    """Return True when *annotation* represents an Optional type.

    Recognises:
    * ``X | None`` (Python 3.10+ union syntax)
    * ``Optional[X]``
    * ``None`` literal
    * ``Any | None``

    Args:
        annotation: AST node for the type annotation.

    Returns:
        ``True`` when the annotation allows ``None``.
    """
    if annotation is None:
        return False

    # X | None  (ast.BinOp with BitOr)
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        left_is_none = isinstance(annotation.left, ast.Constant) and annotation.left.value is None
        right_is_none = isinstance(annotation.right, ast.Constant) and annotation.right.value is None
        left_is_none_name = isinstance(annotation.left, ast.Name) and annotation.left.id == "None"
        right_is_none_name = isinstance(annotation.right, ast.Name) and annotation.right.id == "None"
        if left_is_none or right_is_none or left_is_none_name or right_is_none_name:
            return True
        # Recurse for deeply nested unions like X | Y | None
        return _is_optional_annotation(annotation.left) or _is_optional_annotation(annotation.right)

    # Optional[X]
    if isinstance(annotation, ast.Subscript):
        slice_value = annotation.value
        if isinstance(slice_value, ast.Name) and slice_value.id == "Optional":
            return True

    # None literal used as annotation (rare but valid)
    if isinstance(annotation, ast.Constant) and annotation.value is None:
        return True
    if isinstance(annotation, ast.Name) and annotation.id == "None":
        return True

    return False
