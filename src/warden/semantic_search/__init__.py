"""
Semantic search analyzer for Warden.

Provides code indexing and semantic search capabilities using vector embeddings.

Features:
- Code chunking (function/class/module level)
- Embedding generation (OpenAI/Azure OpenAI)
- Vector indexing (ChromaDB)
- Semantic similarity search
- Context retrieval for LLM analysis

Note:
    Requires optional dependencies: pip install warden-core[semantic]
    (chromadb, sentence-transformers, tiktoken)
"""

import importlib
import logging

_logger = logging.getLogger(__name__)

# Lazy imports - these modules depend on optional packages (chromadb, sentence-transformers).
# Importing eagerly would crash for users who installed warden-core without [semantic] extra.
# We use module-level __getattr__ for deferred import.

_LAZY_IMPORTS = {
    "ContextOptimizer": "warden.semantic_search.context_retriever",
    "ContextRetriever": "warden.semantic_search.context_retriever",
    "EmbeddingCache": "warden.semantic_search.embeddings",
    "EmbeddingGenerator": "warden.semantic_search.embeddings",
    "CodeChunker": "warden.semantic_search.indexer",
    "CodeIndexer": "warden.semantic_search.indexer",
    "ChunkType": "warden.semantic_search.models",
    "CodeChunk": "warden.semantic_search.models",
    "EmbeddingMetadata": "warden.semantic_search.models",
    "IndexStats": "warden.semantic_search.models",
    "RetrievalContext": "warden.semantic_search.models",
    "SearchQuery": "warden.semantic_search.models",
    "SearchResponse": "warden.semantic_search.models",
    "SearchResult": "warden.semantic_search.models",
    "SemanticSearcher": "warden.semantic_search.searcher",
}

__all__ = list(_LAZY_IMPORTS.keys())


def __getattr__(name: str):
    if name in _LAZY_IMPORTS:
        module_path = _LAZY_IMPORTS[name]
        try:
            module = importlib.import_module(module_path)
            return getattr(module, name)
        except ImportError as e:
            raise ImportError(
                f"'{name}' requires optional dependencies. "
                f"Install with: pip install warden-core[semantic]"
            ) from e
    raise AttributeError(f"module 'warden.semantic_search' has no attribute '{name}'")
