"""
Semantic search analyzer for Warden.

Provides code indexing and semantic search capabilities using vector embeddings.

Features:
- Code chunking (function/class/module level)
- Embedding generation (OpenAI/Azure OpenAI)
- Vector indexing (Qdrant)
- Semantic similarity search
- Context retrieval for LLM analysis

Example:
    ```python
    from warden.analyzers.semantic_search import (
        EmbeddingGenerator,
        CodeIndexer,
        SemanticSearcher,
        ContextRetriever,
    )

    # Initialize components
    embedding_gen = EmbeddingGenerator(
        provider="openai",
        api_key="sk-...",
        model_name="text-embedding-3-small"
    )

    indexer = CodeIndexer(
        qdrant_url="http://localhost:6333",
        qdrant_api_key=None,
        collection_name="warden_code_index",
        embedding_generator=embedding_gen
    )

    # Index codebase
    await indexer.index_files(
        file_paths=["src/main.py", "src/utils.py"],
        languages={"src/main.py": "python", "src/utils.py": "python"}
    )

    # Search
    searcher = SemanticSearcher(
        qdrant_url="http://localhost:6333",
        qdrant_api_key=None,
        collection_name="warden_code_index",
        embedding_generator=embedding_gen
    )

    results = await searcher.search_by_description(
        "authentication function with JWT validation",
        language="python"
    )
    ```
"""

from warden.analyzers.semantic_search.context_retriever import (
    ContextOptimizer,
    ContextRetriever,
)
from warden.analyzers.semantic_search.embeddings import (
    EmbeddingCache,
    EmbeddingGenerator,
)
from warden.analyzers.semantic_search.indexer import CodeChunker, CodeIndexer
from warden.analyzers.semantic_search.models import (
    ChunkType,
    CodeChunk,
    EmbeddingMetadata,
    IndexStats,
    RetrievalContext,
    SearchQuery,
    SearchResponse,
    SearchResult,
)
from warden.analyzers.semantic_search.searcher import SemanticSearcher

__all__ = [
    # Models
    "ChunkType",
    "CodeChunk",
    "EmbeddingMetadata",
    "SearchResult",
    "SearchQuery",
    "SearchResponse",
    "IndexStats",
    "RetrievalContext",
    # Embeddings
    "EmbeddingGenerator",
    "EmbeddingCache",
    # Indexing
    "CodeChunker",
    "CodeIndexer",
    # Searching
    "SemanticSearcher",
    # Context Retrieval
    "ContextRetriever",
    "ContextOptimizer",
]
