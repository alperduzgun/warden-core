"""Cross-file analysis: import graph, value propagation, and taint bridging.

Provides cross-file intelligence to enrich security analysis:
- Import graph: which files import what from where
- Value propagation: track constant values across imports (DEBUG=True, SECRET_KEY='...')
- Cross-file context: structured summaries for LLM prompts
"""

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from warden.shared.infrastructure.logging import get_logger
from warden.validation.domain.frame import CodeFile

logger = get_logger(__name__)


@dataclass
class ImportInfo:
    """A single import relationship."""

    source_file: str  # Importing file
    target_module: str  # Imported module name
    target_file: str | None  # Resolved file path (None if unresolved)
    symbols: list[str]  # Imported symbol names (empty for `import X`)
    is_relative: bool = False


@dataclass
class ExportedValue:
    """A constant value exported from a module."""

    name: str
    value: Any
    value_repr: str  # Human-readable representation
    file_path: str
    line: int
    is_sensitive: bool = False  # True if looks like secret/password/key


@dataclass
class CrossFileContext:
    """Cross-file analysis results for a project."""

    import_graph: dict[str, list[ImportInfo]] = field(default_factory=dict)
    exported_values: dict[str, list[ExportedValue]] = field(default_factory=dict)
    file_summaries: dict[str, str] = field(default_factory=dict)


# Patterns that indicate a sensitive value
_SENSITIVE_PATTERNS = re.compile(
    r"(password|secret|key|token|credential|api_key|db_url|database_url|redis_url)",
    re.IGNORECASE,
)


class CrossFileAnalyzer:
    """Builds cross-file intelligence from project source files."""

    def __init__(self, project_root: Path):
        self.project_root = project_root

    def analyze(self, code_files: list[CodeFile]) -> CrossFileContext:
        """Run full cross-file analysis on all project files."""
        ctx = CrossFileContext()

        # Phase 1: Build import graph
        file_map = {cf.path: cf for cf in code_files}
        for cf in code_files:
            imports = self._extract_imports(cf)
            if imports:
                ctx.import_graph[cf.path] = imports

        # Phase 2: Extract exported constant values
        for cf in code_files:
            values = self._extract_constants(cf)
            if values:
                ctx.exported_values[cf.path] = values

        # Phase 3: Build per-file summaries for LLM context
        for cf in code_files:
            ctx.file_summaries[cf.path] = self._build_file_summary(cf, ctx)

        imports_count = sum(len(v) for v in ctx.import_graph.values())
        values_count = sum(len(v) for v in ctx.exported_values.values())
        logger.info(
            "cross_file_analysis_complete",
            files=len(code_files),
            imports=imports_count,
            exported_values=values_count,
        )

        return ctx

    def _extract_imports(self, code_file: CodeFile) -> list[ImportInfo]:
        """Extract import statements from a Python file via AST."""
        imports: list[ImportInfo] = []
        try:
            tree = ast.parse(code_file.content)
        except SyntaxError:
            return imports

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(ImportInfo(
                        source_file=code_file.path,
                        target_module=alias.name,
                        target_file=self._resolve_module(alias.name, code_file.path),
                        symbols=[],
                    ))
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                is_relative = (node.level or 0) > 0
                symbols = [a.name for a in (node.names or [])]
                resolved = self._resolve_module(module, code_file.path, node.level or 0)
                imports.append(ImportInfo(
                    source_file=code_file.path,
                    target_module=module,
                    target_file=resolved,
                    symbols=symbols,
                    is_relative=is_relative,
                ))

        return imports

    def _resolve_module(self, module_name: str, source_file: str, level: int = 0) -> str | None:
        """Resolve a module name to a file path relative to project root."""
        source_path = Path(source_file)
        if source_path.is_absolute():
            try:
                source_path = source_path.relative_to(self.project_root)
            except ValueError:
                pass

        source_dir = source_path.parent

        if level > 0:
            # Relative import: go up `level` directories from source
            base = source_dir
            for _ in range(level - 1):
                base = base.parent
            if module_name:
                candidate = base / module_name.replace(".", "/")
            else:
                candidate = base
        else:
            # Absolute import: try as relative to project root
            candidate = Path(module_name.replace(".", "/"))

        # Try candidate.py and candidate/__init__.py
        for suffix in [".py", "/__init__.py"]:
            full = self.project_root / f"{candidate}{suffix}"
            if full.exists():
                return str(candidate) + suffix

        # Try just the last part (sibling file)
        parts = module_name.split(".")
        sibling = source_dir / f"{parts[-1]}.py"
        full_sibling = self.project_root / sibling
        if full_sibling.exists():
            return str(sibling)

        return None

    def _extract_constants(self, code_file: CodeFile) -> list[ExportedValue]:
        """Extract top-level constant assignments from a Python file."""
        values: list[ExportedValue] = []
        try:
            tree = ast.parse(code_file.content)
        except SyntaxError:
            return values

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id.isupper():
                        val = self._extract_literal_value(node.value)
                        if val is not None:
                            is_sensitive = bool(_SENSITIVE_PATTERNS.search(target.id))
                            values.append(ExportedValue(
                                name=target.id,
                                value=val,
                                value_repr=repr(val) if len(repr(val)) < 100 else repr(val)[:100] + "...",
                                file_path=code_file.path,
                                line=node.lineno,
                                is_sensitive=is_sensitive,
                            ))

        return values

    def _extract_literal_value(self, node: ast.expr) -> Any:
        """Extract a literal value from an AST expression node."""
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.List):
            return [self._extract_literal_value(e) for e in node.elts]
        if isinstance(node, ast.Dict):
            return {
                self._extract_literal_value(k): self._extract_literal_value(v)
                for k, v in zip(node.keys, node.values)
                if k is not None
            }
        if isinstance(node, ast.Name):
            if node.id == "True":
                return True
            if node.id == "False":
                return False
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            val = self._extract_literal_value(node.operand)
            if isinstance(val, (int, float)):
                return -val
        return None

    def _build_file_summary(self, code_file: CodeFile, ctx: CrossFileContext) -> str:
        """Build a compact summary of a file's security-relevant interface."""
        parts: list[str] = []

        # Exported values
        values = ctx.exported_values.get(code_file.path, [])
        sensitive = [v for v in values if v.is_sensitive]
        if sensitive:
            val_strs = [f"{v.name}={v.value_repr}" for v in sensitive[:5]]
            parts.append(f"Exports: {', '.join(val_strs)}")

        # Functions that accept 'request' or user-input-like params
        try:
            tree = ast.parse(code_file.content)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    params = [a.arg for a in node.args.args]
                    has_input = any(p in ("request", "req", "data", "payload", "user_input", "query")
                                   for p in params)
                    if has_input:
                        parts.append(f"fn {node.name}({', '.join(params[:4])}) → accepts user input")
        except SyntaxError:
            pass

        return "; ".join(parts) if parts else ""

    def format_cross_file_prompt(self, file_path: str, ctx: CrossFileContext, max_tokens: int = 500) -> str:
        """Format cross-file context for inclusion in LLM security prompts."""
        lines: list[str] = []
        lines.append("[CROSS-FILE CONTEXT]:")

        # Resolve target_file to absolute path for matching against exported_values keys
        def _resolve(rel_path: str | None) -> str | None:
            if not rel_path:
                return None
            abs_path = str(self.project_root / rel_path)
            if abs_path in ctx.exported_values or abs_path in ctx.file_summaries:
                return abs_path
            return rel_path  # Fallback to relative

        # What this file imports — only resolved (project-internal) imports
        imports = [i for i in ctx.import_graph.get(file_path, []) if i.target_file]
        for imp in imports[:5]:
            resolved = _resolve(imp.target_file)
            if not resolved:
                continue
            summary = ctx.file_summaries.get(resolved, "")
            if summary:
                symbols_str = f" ({', '.join(imp.symbols[:5])})" if imp.symbols else ""
                lines.append(f"  imports {imp.target_module}{symbols_str}: {summary}")

        # Propagated values that this file uses
        for imp in imports:
            resolved = _resolve(imp.target_file)
            if not resolved:
                continue
            values = ctx.exported_values.get(resolved, [])
            for v in values:
                if v.name in imp.symbols and v.is_sensitive:
                    lines.append(f"  WARNING: {v.name}={v.value_repr} (from {imp.target_module}) — hardcoded sensitive value")

        if len(lines) <= 1:
            return ""

        result = "\n".join(lines)
        # Rough token estimate: 1 token ≈ 4 chars
        if len(result) > max_tokens * 4:
            result = result[: max_tokens * 4] + "\n  ... (truncated)"

        return result
