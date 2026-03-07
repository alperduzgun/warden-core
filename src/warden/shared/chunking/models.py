"""Domain models for chunk-based LLM analysis."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CodeChunk:
    """A semantic unit of code prepared for a single LLM call.

    The ``content`` field contains the chunk's source lines prefixed with
    their original file line numbers (e.g. ``"151: def process(data):"``).
    This lets the LLM report absolute line numbers directly, avoiding any
    offset arithmetic in the reconciler.

    ``import_context`` and ``class_context`` are provided separately so
    they can be injected into the prompt as reference material without
    introducing fake line numbers into the analyzed code block.
    """

    content: str  # Code lines prefixed with absolute line numbers
    start_line: int  # 1-based start line in the original file
    end_line: int  # 1-based end line in the original file
    file_path: str  # Source file path
    chunk_index: int  # 0-based position within this file's chunks
    total_chunks: int  # Total number of chunks for this file
    chunk_type: str  # "full" | "function" | "class_method" | "lines"
    import_context: str = ""  # File imports for LLM reference (no line numbers)
    class_context: str | None = None  # Class decl + __init__ for method chunks
    unit_name: str | None = None  # Function/class name if known


@dataclass(frozen=True)
class ChunkingConfig:
    """Controls how a frame splits large files into per-chunk LLM calls.

    ``max_chunks_per_file`` should be tier-aware:
    - fast tier (0.5b, ~30 tok/s): 3 — fits within the 45 s Ollama timeout
    - smart tier (3b,  ~5 tok/s):  1 — each chunk already saturates the budget
    """

    max_chunk_tokens: int  # Maximum input tokens allowed per chunk
    max_chunks_per_file: int = 3  # Hard upper bound on LLM calls per file
    min_chunk_lines: int = 5  # Units shorter than this are skipped
