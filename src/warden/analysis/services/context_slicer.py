"""Hyper-curated context slicing for LLM prompts.

Extracts function-level code context instead of file-level truncation.
Uses AST (tree-sitter / native) for function boundary detection and
CodeGraph for caller/callee signature assembly.

Result: ~280 focused tokens instead of ~1800 noisy tokens.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from warden.shared.infrastructure.logging import get_logger

if TYPE_CHECKING:
    from warden.analysis.domain.code_graph import CodeGraph
    from warden.ast.domain.models import ASTNode

logger = get_logger(__name__)


@dataclass
class SlicedContext:
    """Result of context slicing — focused code for LLM consumption."""

    function_body: str = ""
    function_name: str = ""
    start_line: int = 0
    end_line: int = 0
    caller_signatures: list[str] = field(default_factory=list)
    callee_signatures: list[str] = field(default_factory=list)
    import_context: str = ""
    is_fallback: bool = False

    @property
    def total_chars(self) -> int:
        return (
            len(self.function_body)
            + sum(len(s) for s in self.caller_signatures)
            + sum(len(s) for s in self.callee_signatures)
            + len(self.import_context)
        )


def get_ast_and_graph_from_context(
    pipeline_context: object | None,
    file_path: str,
) -> tuple[ASTNode | None, CodeGraph | None]:
    """Extract AST root and CodeGraph from pipeline context.

    Follows dependency chain: PipelineContext → ast_cache → ParseResult → ast_root.
    Fail-fast: returns (None, None) on any missing link.
    """
    ast_root: ASTNode | None = None
    code_graph: CodeGraph | None = None

    if pipeline_context is None:
        return None, None

    # AST root from cache
    ast_cache = getattr(pipeline_context, "ast_cache", None)
    if ast_cache:
        cached_result = ast_cache.get(file_path)
        if cached_result and hasattr(cached_result, "ast_root"):
            ast_root = cached_result.ast_root

    # CodeGraph
    code_graph = getattr(pipeline_context, "code_graph", None)

    return ast_root, code_graph


def _center_around_targets(
    body_text: str,
    target_lines: list[int],
    token_budget: int,
    anchor_start: int = 0,
    signature_lines: int = 5,
) -> str:
    """Center-around truncation: keep function signature + target line context.

    Instead of naive head-truncation, preserves:
    1. Function signature + decorators (first N lines — anchor, never cut)
    2. Lines around each target_line (±window)
    3. Omission markers between gaps

    Args:
        body_text: The extracted function body text.
        target_lines: 1-based line numbers of interest (from the original file).
        token_budget: Maximum tokens for the result.
        anchor_start: 1-based start line of the function body in the original file.
        signature_lines: Number of top lines to always keep (signature + decorators).

    Returns:
        Centered body text fitting within token_budget.
    """
    from warden.shared.utils.token_utils import estimate_tokens

    lines = body_text.splitlines()
    total = len(lines)

    if total == 0:
        return body_text

    # Convert file-level 1-based target_lines to 0-based body-local indices
    local_targets: list[int] = []
    for tl in target_lines:
        idx = tl - anchor_start  # 0-based index within body_text lines
        if 0 <= idx < total:
            local_targets.append(idx)

    # If no targets fall inside the body, keep the signature and trim the rest
    if not local_targets:
        local_targets = [min(signature_lines, total - 1)]

    # Start with a generous context window, shrink until it fits.
    # Also progressively reduce signature anchor if budget is very tight.
    sig_candidates = sorted(set((signature_lines, 3, 2, 1)), reverse=True)
    for sig_count in sig_candidates:
        for window in (20, 15, 10, 7, 5, 3, 2, 1, 0):
            selected: set[int] = set()

            # Anchor: keep the first sig_count lines (decorators + def)
            for i in range(min(sig_count, total)):
                selected.add(i)

            # Add window around each target
            for tidx in local_targets:
                for offset in range(-window, window + 1):
                    line_idx = tidx + offset
                    if 0 <= line_idx < total:
                        selected.add(line_idx)

            # Build output with omission markers
            sorted_indices = sorted(selected)
            result_parts: list[str] = []
            prev_idx = -1

            for idx in sorted_indices:
                if prev_idx >= 0 and idx > prev_idx + 1:
                    gap = idx - prev_idx - 1
                    result_parts.append(f"    ... [{gap} lines omitted] ...")
                result_parts.append(lines[idx])
                prev_idx = idx

            # Trailing omission if we didn't include the last line
            if sorted_indices and sorted_indices[-1] < total - 1:
                gap = total - 1 - sorted_indices[-1]
                result_parts.append(f"    ... [{gap} lines omitted] ...")

            result = "\n".join(result_parts)
            if estimate_tokens(result) <= token_budget:
                return result

    # Last resort: hard truncate from token_utils
    from warden.shared.utils.token_utils import truncate_to_tokens

    return truncate_to_tokens(body_text, token_budget)


class ContextSlicerService:
    """Tree-sitter + CodeGraph context slicer for LLM prompts.

    Extracts the minimal, focused context around target lines:
    - Function body containing the target (via AST)
    - Caller/callee signatures (via CodeGraph)
    - Import context (first N lines)
    """

    def slice_for_function(
        self,
        file_content: str,
        target_lines: list[int],
        ast_root: ASTNode | None = None,
    ) -> SlicedContext:
        """Extract function body containing target lines via AST.

        Args:
            file_content: Full source code.
            target_lines: 1-based line numbers of interest (dangerous calls, sinks).
            ast_root: Pre-parsed AST root (from pipeline cache). If None, falls back.

        Returns:
            SlicedContext with function body or fallback.
        """
        if not file_content or not target_lines:
            logger.debug("slice_fallback", reason="empty_content_or_no_targets")
            return SlicedContext(function_body=file_content[:2000], is_fallback=True)

        if ast_root is None:
            logger.debug("slice_fallback", reason="no_ast_root")
            return SlicedContext(function_body=file_content[:2000], is_fallback=True)

        from warden.ast.domain.enums import ASTNodeType

        # Collect all function/method nodes
        functions = ast_root.find_nodes(ASTNodeType.FUNCTION) + ast_root.find_nodes(ASTNodeType.METHOD)

        if not functions:
            logger.debug("slice_fallback", reason="no_functions_in_ast")
            return SlicedContext(function_body=file_content[:2000], is_fallback=True)

        # Find the function(s) containing target lines
        lines = file_content.splitlines()
        matched_functions: list[ASTNode] = []
        seen_names: set[str] = set()

        for target_line in target_lines:
            best_match: ASTNode | None = None
            best_span = float("inf")

            for func_node in functions:
                loc = func_node.location
                if loc is None:
                    continue
                # Check if target_line falls within this function
                if loc.start_line <= target_line <= loc.end_line:
                    span = loc.end_line - loc.start_line
                    # Prefer the tightest enclosing function (innermost)
                    if span < best_span:
                        best_span = span
                        best_match = func_node

            if best_match and best_match.name not in seen_names:
                matched_functions.append(best_match)
                seen_names.add(best_match.name or "")

        if not matched_functions:
            # No function contains the target — try nearest function
            nearest = self._find_nearest_function(functions, target_lines[0])
            if nearest:
                matched_functions = [nearest]
                logger.debug("slice_nearest_fallback", target=target_lines[0], func=nearest.name)
            else:
                logger.debug("slice_fallback", reason="no_matching_function", targets=target_lines[:5])
                return SlicedContext(function_body=file_content[:2000], is_fallback=True)

        # Extract function bodies
        body_parts: list[str] = []
        first_start = 0
        last_end = 0

        for func_node in matched_functions[:3]:  # Max 3 functions
            loc = func_node.location
            if loc is None:
                continue
            start_idx = max(0, loc.start_line - 1)  # 0-indexed

            # Scan upward for decorator lines (@decorator) — AST-agnostic
            while start_idx > 0 and lines[start_idx - 1].lstrip().startswith("@"):
                start_idx -= 1

            # Scan upward for contiguous comment lines (# comment, // comment, TODO, etc.)
            # preceding the decorators/function def. Stop at blank or non-comment line.
            # Cap at 10 comment lines to prevent token explosion from large headers.
            comment_lines_captured = 0
            max_comment_lines = 10
            while start_idx > 0 and comment_lines_captured < max_comment_lines:
                prev_line = lines[start_idx - 1].lstrip()
                if prev_line.startswith("#") or prev_line.startswith("//"):
                    start_idx -= 1
                    comment_lines_captured += 1
                else:
                    break

            end_idx = min(len(lines), loc.end_line)
            func_body = "\n".join(lines[start_idx:end_idx])
            body_parts.append(func_body)

            effective_start = start_idx + 1  # back to 1-based
            if not first_start or effective_start < first_start:
                first_start = effective_start
            if loc.end_line > last_end:
                last_end = loc.end_line

        func_name = matched_functions[0].name or "unknown"
        combined_body = "\n\n".join(body_parts)

        # Extract import context (first lines up to first function)
        import_lines = self._extract_import_context(lines, functions)

        return SlicedContext(
            function_body=combined_body,
            function_name=func_name,
            start_line=first_start,
            end_line=last_end,
            import_context=import_lines,
            is_fallback=False,
        )

    def get_caller_signatures(
        self,
        file_path: str,
        function_name: str,
        code_graph: CodeGraph | None,
        max_callers: int = 5,
        max_callees: int = 3,
    ) -> tuple[list[str], list[str]]:
        """Get caller/callee function signatures from CodeGraph.

        Args:
            file_path: Path of the file containing the function.
            function_name: Name of the target function.
            code_graph: Project code graph.
            max_callers: Maximum caller signatures to return.
            max_callees: Maximum callee signatures to return.

        Returns:
            Tuple of (caller_signatures, callee_signatures).
        """
        if not code_graph or not function_name:
            return [], []

        from warden.analysis.domain.code_graph import EdgeRelation

        callers: list[str] = []
        callees: list[str] = []

        # Find the target symbol FQN
        target_fqn = self._find_symbol_fqn(code_graph, file_path, function_name)
        if not target_fqn:
            logger.debug("caller_lookup_failed", reason="fqn_not_found", function=function_name)
            return [], []

        # Callers: who calls this function
        caller_edges = [e for e in code_graph.edges if e.target == target_fqn and e.relation == EdgeRelation.CALLS]
        for edge in caller_edges[:max_callers]:
            node = code_graph.nodes.get(edge.source)
            if node:
                sig = f"{node.kind.value} {node.name}"
                if node.file_path:
                    sig += f" ({node.file_path})"
                callers.append(sig)

        # Callees: what this function calls
        callee_edges = [e for e in code_graph.edges if e.source == target_fqn and e.relation == EdgeRelation.CALLS]
        for edge in callee_edges[:max_callees]:
            node = code_graph.nodes.get(edge.target)
            if node:
                sig = f"{node.kind.value} {node.name}"
                if node.file_path:
                    sig += f" ({node.file_path})"
                callees.append(sig)

        return callers, callees

    def build_focused_context(
        self,
        file_content: str,
        file_path: str,
        target_lines: list[int],
        ast_root: ASTNode | None = None,
        code_graph: CodeGraph | None = None,
        token_budget: int = 400,
    ) -> str:
        """Build focused context: function body + caller signatures.

        Budget allocation:
        - 70% target function body (~280 tokens / 400 budget)
        - 20% caller/callee signatures (~80 tokens)
        - 10% import/class context (~40 tokens)

        Falls back to truncate_with_ast_hints if function extraction fails.

        Args:
            file_content: Full source code.
            file_path: File path for CodeGraph lookup.
            target_lines: 1-based line numbers of interest.
            ast_root: Pre-parsed AST root.
            code_graph: Project code graph for caller/callee lookup.
            token_budget: Total token budget.

        Returns:
            Focused context string for LLM.
        """
        from warden.shared.utils.token_utils import estimate_tokens, truncate_to_tokens

        # If content fits in budget, return as-is
        if estimate_tokens(file_content) <= token_budget:
            return file_content

        # Try function-level extraction
        sliced = self.slice_for_function(file_content, target_lines, ast_root)

        if sliced.is_fallback:
            # Fallback to existing truncation
            from warden.shared.utils.token_utils import truncate_with_ast_hints

            return truncate_with_ast_hints(
                file_content,
                max_tokens=token_budget,
                dangerous_lines=target_lines or None,
            )

        # Budget allocation
        body_budget = int(token_budget * 0.70)
        sig_budget = int(token_budget * 0.20)
        import_budget = int(token_budget * 0.10)

        # 1. Function body (70%) — center around target lines if over budget
        body_text = sliced.function_body
        if estimate_tokens(body_text) > body_budget:
            body_text = _center_around_targets(body_text, target_lines, body_budget, anchor_start=sliced.start_line)

        # 2. Caller/callee signatures (20%)
        sig_text = ""
        if code_graph:
            callers, callees = self.get_caller_signatures(file_path, sliced.function_name, code_graph)
            sliced.caller_signatures = callers
            sliced.callee_signatures = callees

            sig_parts: list[str] = []
            if callers:
                sig_parts.append("Callers:")
                for c in callers:
                    sig_parts.append(f"  - {c}")
            if callees:
                sig_parts.append("Callees:")
                for c in callees:
                    sig_parts.append(f"  - {c}")
            sig_text = "\n".join(sig_parts)

            if estimate_tokens(sig_text) > sig_budget:
                sig_text = truncate_to_tokens(sig_text, sig_budget)

        # 3. Import context (10%)
        import_text = sliced.import_context
        if import_text and estimate_tokens(import_text) > import_budget:
            import_text = truncate_to_tokens(import_text, import_budget)

        # Assemble
        parts: list[str] = []
        if import_text:
            parts.append(import_text)
            parts.append("")  # separator
        parts.append(body_text)
        if sig_text:
            parts.append("")
            parts.append(sig_text)

        result = "\n".join(parts)

        logger.debug(
            "context_sliced",
            file=file_path,
            function=sliced.function_name,
            body_tokens=estimate_tokens(body_text),
            total_tokens=estimate_tokens(result),
            budget=token_budget,
            is_fallback=False,
        )

        return result

    def _find_nearest_function(self, functions: list[ASTNode], target_line: int) -> ASTNode | None:
        """Find the function nearest to target_line."""
        best: ASTNode | None = None
        best_dist = float("inf")

        for func in functions:
            loc = func.location
            if loc is None:
                continue
            # Distance from target to function range
            if target_line < loc.start_line:
                dist = loc.start_line - target_line
            elif target_line > loc.end_line:
                dist = target_line - loc.end_line
            else:
                dist = 0
            if dist < best_dist:
                best_dist = dist
                best = func

        return best

    def _extract_import_context(self, lines: list[str], functions: list[ASTNode]) -> str:
        """Extract import lines from the top of the file.

        Takes lines before the first function definition, up to 15 lines max.
        """
        first_func_line: int | None = None
        for func in functions:
            loc = func.location
            if loc and (first_func_line is None or loc.start_line < first_func_line):
                first_func_line = loc.start_line

        if first_func_line is None:
            # All functions lack location — take first 15 lines
            first_func_line = min(16, len(lines) + 1)

        end = min(first_func_line - 1, 15, len(lines))
        if end <= 0:
            return ""

        import_lines = []
        for line in lines[:end]:
            stripped = line.strip()
            if stripped.startswith(("import ", "from ", "require(", "use ", "using ", "#include", "package ")):
                import_lines.append(line)

        return "\n".join(import_lines)

    def _find_symbol_fqn(self, code_graph: CodeGraph, file_path: str, function_name: str) -> str | None:
        """Find the FQN for a function in the code graph."""
        # Try exact match first
        for fqn, node in code_graph.nodes.items():
            if node.name == function_name and (node.file_path == file_path or file_path.endswith(node.file_path)):
                return fqn

        # Try by name only
        matches = code_graph.get_symbols_by_name(function_name)
        if matches:
            return matches[0].fqn

        return None
