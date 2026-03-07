"""ChunkingService — public facade for chunk-based LLM analysis.

Frames use this service instead of calling ASTChunker / reconciler
directly.  It is intentionally stateless so frames can instantiate it
inline without any dependency injection.

Usage (inside a frame's execute_async):

    from warden.shared.chunking import ChunkingService, ChunkingConfig

    _config = ChunkingConfig(max_chunk_tokens=700, max_chunks_per_file=3)
    service = ChunkingService()

    if service.should_chunk(code_file, _config):
        chunks = service.chunk(code_file, context.ast_cache if context else None, _config)
        all_findings = []
        for chunk in chunks:
            raw = await _analyze_chunk(chunk)
            all_findings.extend(service.reconcile(chunk, raw, self.frame_id))
    else:
        all_findings = await _analyze_file(code_file)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from warden.shared.utils.token_utils import estimate_tokens

from .ast_chunker import ASTChunker
from .models import ChunkingConfig, CodeChunk
from .reconciler import reconcile_findings

if TYPE_CHECKING:
    from warden.validation.domain.frame import CodeFile


class ChunkingService:
    """Stateless facade: chunk a file, reconcile findings."""

    def __init__(self) -> None:
        self._chunker = ASTChunker()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def should_chunk(self, code_file: CodeFile, config: ChunkingConfig) -> bool:
        """Return True when the file exceeds *config.max_chunk_tokens*."""
        content = code_file.content or ""
        return estimate_tokens(content) > config.max_chunk_tokens

    def chunk(
        self,
        code_file: CodeFile,
        ast_cache: dict[str, Any] | None,
        config: ChunkingConfig,
    ) -> list[CodeChunk]:
        """Split *code_file* into an ordered list of CodeChunk objects.

        Always returns at least one chunk.  If the file fits within the
        budget a single 'full' chunk is returned (zero overhead).
        """
        return self._chunker.chunk(code_file, ast_cache, config)

    def reconcile(
        self,
        chunk: CodeChunk,
        findings: list[Any],
        frame_id: str,
    ) -> list[Any]:
        """Correct line numbers and IDs for *findings* from *chunk*.

        See reconciler.reconcile_findings for the full description.
        """
        return reconcile_findings(chunk, findings, frame_id)

    def build_prompt_header(self, chunk: CodeChunk) -> str:
        """Return a structured header to prepend to the LLM user message.

        Provides the LLM with:
        - import context (for framework/pattern awareness)
        - class context (only for class_method chunks)
        - clear labeling of the code block with absolute line ranges
        """
        parts: list[str] = []

        if chunk.import_context:
            parts.append(f"[IMPORTS — reference only, do not report line numbers from here]\n{chunk.import_context}")

        if chunk.class_context:
            parts.append(f"[CLASS CONTEXT — for understanding self.* attributes]\n{chunk.class_context}")

        label = f"[CODE TO ANALYZE — chunk {chunk.chunk_index + 1}/{chunk.total_chunks}"
        if chunk.unit_name:
            label += f", unit: {chunk.unit_name}"
        label += f" — lines {chunk.start_line}–{chunk.end_line} of {chunk.file_path}]"
        parts.append(label)

        return "\n\n".join(parts) + "\n\n" if parts else ""
