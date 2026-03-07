"""AST-aware file chunker for LLM analysis.

Splits a large source file into semantic units (top-level functions,
class methods) so each unit fits within the LLM token budget.  Falls back
to fixed-size line chunking when no AST is available.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from warden.shared.infrastructure.logging import get_logger
from warden.shared.utils.token_utils import estimate_tokens

from .models import ChunkingConfig, CodeChunk

if TYPE_CHECKING:
    from warden.validation.domain.frame import CodeFile

logger = get_logger(__name__)

# How many __init__ lines to include in class_context (avoids token explosion)
_MAX_INIT_LINES = 20
# How many lines to scan upward for decorators / comment headers
_MAX_DECORATOR_SCAN = 15


def _numbered(lines: list[str], start_line: int) -> str:
    """Return lines joined as 'N: code' strings (1-based start_line)."""
    return "\n".join(f"{start_line + i}: {ln}" for i, ln in enumerate(lines))


def _extract_lines(all_lines: list[str], start_line: int, end_line: int) -> list[str]:
    """Extract 0-indexed slice from all_lines using 1-based boundaries."""
    lo = max(0, start_line - 1)
    hi = min(len(all_lines), end_line)
    return all_lines[lo:hi]


def _scan_up_for_decorators(all_lines: list[str], start_0: int) -> int:
    """Walk upward from start_0 (0-based) to capture decorators and comments."""
    idx = start_0
    captured = 0
    while idx > 0 and captured < _MAX_DECORATOR_SCAN:
        prev = all_lines[idx - 1].lstrip()
        if prev.startswith(("@", "#", "//")):
            idx -= 1
            captured += 1
        else:
            break
    return idx


class ASTChunker:
    """Splits a source file into semantically coherent chunks for LLM analysis."""

    def chunk(
        self,
        code_file: CodeFile,
        ast_cache: dict[str, Any] | None,
        config: ChunkingConfig,
    ) -> list[CodeChunk]:
        """Return an ordered list of CodeChunk objects for *code_file*.

        Returns a single 'full' chunk when the file already fits within the
        token budget — zero chunking overhead in the common case.
        """
        content = code_file.content or ""
        lines = content.splitlines()

        if not lines:
            return []

        # --- Fast path: file fits in budget ---
        if estimate_tokens(content) <= config.max_chunk_tokens:
            return [
                CodeChunk(
                    content=content,
                    start_line=1,
                    end_line=len(lines),
                    file_path=code_file.path,
                    chunk_index=0,
                    total_chunks=1,
                    chunk_type="full",
                )
            ]

        # --- AST path ---
        parse_result = (ast_cache or {}).get(code_file.path)
        if parse_result and getattr(parse_result, "ast_root", None):
            try:
                chunks = self._ast_chunks(code_file.path, lines, parse_result.ast_root, config)
                if chunks:
                    return chunks
            except Exception as exc:
                logger.debug("chunker_ast_failed", file=code_file.path, error=str(exc))

        # --- Line-based fallback ---
        return self._line_chunks(code_file.path, lines, config)

    # ------------------------------------------------------------------
    # AST-based chunking
    # ------------------------------------------------------------------

    def _ast_chunks(
        self,
        file_path: str,
        lines: list[str],
        ast_root: Any,
        config: ChunkingConfig,
    ) -> list[CodeChunk]:
        from warden.ast.domain.enums import ASTNodeType

        func_nodes = ast_root.find_nodes(ASTNodeType.FUNCTION)
        method_nodes = ast_root.find_nodes(ASTNodeType.METHOD)
        class_nodes = ast_root.find_nodes(ASTNodeType.CLASS)

        all_semantic = func_nodes + method_nodes + class_nodes
        if not all_semantic:
            return []

        # Import context: everything before the first semantic node
        first_line = min(
            (n.location.start_line for n in all_semantic if n.location),
            default=1,
        )
        import_context = "\n".join(lines[: first_line - 1])

        # Collect units
        units: list[dict] = []

        # Lines occupied by class bodies — used to skip top-level functions
        # that are actually methods (tree-sitter sometimes surfaces both).
        class_ranges: set[int] = set()
        for cn in class_nodes:
            if cn.location:
                class_ranges.update(range(cn.location.start_line, cn.location.end_line + 1))

        # Top-level functions (not inside any class)
        for fn in func_nodes:
            if not fn.location:
                continue
            if fn.location.start_line in class_ranges:
                continue
            start_0 = _scan_up_for_decorators(lines, fn.location.start_line - 1)
            units.append(
                {
                    "start_line": start_0 + 1,  # back to 1-based
                    "end_line": fn.location.end_line,
                    "name": fn.name or "unknown",
                    "chunk_type": "function",
                    "class_context": None,
                }
            )

        # Class methods
        for cn in class_nodes:
            if not cn.location:
                continue
            class_ctx = self._build_class_context(lines, cn, method_nodes)

            for mn in method_nodes:
                if not mn.location:
                    continue
                if mn.name == "__init__":
                    continue  # already in class_context
                if not (cn.location.start_line <= mn.location.start_line <= cn.location.end_line):
                    continue
                start_0 = _scan_up_for_decorators(lines, mn.location.start_line - 1)
                units.append(
                    {
                        "start_line": start_0 + 1,
                        "end_line": mn.location.end_line,
                        "name": f"{cn.name}.{mn.name}" if cn.name else (mn.name or "unknown"),
                        "chunk_type": "class_method",
                        "class_context": class_ctx,
                    }
                )

        if not units:
            return []

        units.sort(key=lambda u: u["start_line"])

        # Pack units greedily into chunks
        import_tokens = estimate_tokens(import_context)
        chunks: list[CodeChunk] = []
        bucket: list[dict] = []
        bucket_tokens = 0

        for unit in units:
            unit_lines = _extract_lines(lines, unit["start_line"], unit["end_line"])
            if len(unit_lines) < config.min_chunk_lines:
                continue
            unit_tokens = estimate_tokens("\n".join(unit_lines))

            flush_needed = bucket and (bucket_tokens + unit_tokens + import_tokens > config.max_chunk_tokens)
            cap_reached = len(chunks) + (1 if flush_needed else 0) >= config.max_chunks_per_file

            if flush_needed:
                chunks.append(self._build_ast_chunk(lines, bucket, import_context, file_path))
                bucket = []
                bucket_tokens = 0

            if cap_reached:
                break

            bucket.append(unit)
            bucket_tokens += unit_tokens

        if bucket and len(chunks) < config.max_chunks_per_file:
            chunks.append(self._build_ast_chunk(lines, bucket, import_context, file_path))

        # Stamp indices
        total = len(chunks)
        for i, ch in enumerate(chunks):
            ch.chunk_index = i
            ch.total_chunks = total

        return chunks

    def _build_class_context(self, lines: list[str], class_node: Any, method_nodes: list[Any]) -> str:
        """Return class declaration + __init__ body (capped) as context string."""
        decl_line = lines[class_node.location.start_line - 1] if class_node.location else ""

        init_snippet = ""
        for mn in method_nodes:
            if mn.name == "__init__" and mn.location:
                if class_node.location.start_line <= mn.location.start_line <= class_node.location.end_line:
                    init_lines = _extract_lines(lines, mn.location.start_line, mn.location.end_line)
                    init_snippet = "\n".join(init_lines[:_MAX_INIT_LINES])
                    break

        if init_snippet:
            return f"{decl_line}\n    # [other methods omitted]\n{init_snippet}"
        return decl_line

    def _build_ast_chunk(
        self,
        lines: list[str],
        units: list[dict],
        import_context: str,
        file_path: str,
    ) -> CodeChunk:
        start_line = units[0]["start_line"]
        end_line = units[-1]["end_line"]
        chunk_lines = _extract_lines(lines, start_line, end_line)
        content = _numbered(chunk_lines, start_line)

        chunk_type = units[0]["chunk_type"] if len(units) == 1 else "function"
        class_context = units[0]["class_context"] if len(units) == 1 else None
        unit_name = units[0]["name"] if len(units) == 1 else None

        return CodeChunk(
            content=content,
            start_line=start_line,
            end_line=end_line,
            file_path=file_path,
            chunk_index=0,  # stamped later
            total_chunks=0,  # stamped later
            chunk_type=chunk_type,
            import_context=import_context,
            class_context=class_context,
            unit_name=unit_name,
        )

    # ------------------------------------------------------------------
    # Line-based fallback
    # ------------------------------------------------------------------

    def _line_chunks(
        self,
        file_path: str,
        lines: list[str],
        config: ChunkingConfig,
    ) -> list[CodeChunk]:
        """Split file into fixed-size line blocks as a last resort."""
        # Estimate lines-per-chunk from token budget
        avg_tokens_per_line = max(1, estimate_tokens("\n".join(lines)) // max(1, len(lines)))
        lines_per_chunk = max(config.min_chunk_lines, config.max_chunk_tokens // avg_tokens_per_line)

        chunks: list[CodeChunk] = []
        total_lines = len(lines)
        start = 0

        while start < total_lines and len(chunks) < config.max_chunks_per_file:
            end = min(start + lines_per_chunk, total_lines)
            chunk_lines = lines[start:end]
            start_line = start + 1
            end_line = end

            chunks.append(
                CodeChunk(
                    content=_numbered(chunk_lines, start_line),
                    start_line=start_line,
                    end_line=end_line,
                    file_path=file_path,
                    chunk_index=len(chunks),
                    total_chunks=0,  # stamped below
                    chunk_type="lines",
                )
            )
            start = end

        total = len(chunks)
        for ch in chunks:
            ch.total_chunks = total

        return chunks
