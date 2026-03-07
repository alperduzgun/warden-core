"""Chunk-based LLM analysis for large files.

Splits large source files into semantic units (functions, methods)
so each LLM call stays within the token budget without truncating
the middle of the file.
"""

from .models import ChunkingConfig, CodeChunk
from .service import ChunkingService

__all__ = ["ChunkingConfig", "CodeChunk", "ChunkingService"]
