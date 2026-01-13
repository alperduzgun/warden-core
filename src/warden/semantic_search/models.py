"""
Semantic search domain models.

Core entities for code indexing and semantic search operations.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from warden.shared.domain.base_model import BaseDomainModel


class ChunkType(Enum):
    """
    Type of code chunk for indexing granularity.

    Determines how code is segmented for semantic search.
    """

    FUNCTION = "function"  # Function/method level
    CLASS = "class"  # Class level
    MODULE = "module"  # Entire file/module
    BLOCK = "block"  # Code block (if/for/while)

    @property
    def default_size(self) -> int:
        """Get default maximum lines for this chunk type."""
        size_map = {
            ChunkType.FUNCTION: 100,
            ChunkType.CLASS: 200,
            ChunkType.MODULE: 500,
            ChunkType.BLOCK: 50,
        }
        return size_map.get(self, 100)


class CodeChunk(BaseDomainModel):
    """
    A code chunk extracted from a file for semantic indexing.

    Represents a semantic unit of code (function, class, module).
    """

    id: str  # Unique chunk ID (hash of content + metadata)
    file_path: str  # Absolute path to source file
    relative_path: str  # Path relative to project root
    chunk_type: ChunkType
    content: str  # Code content
    start_line: int  # Starting line number in file
    end_line: int  # Ending line number in file
    language: str  # Programming language (python, javascript, etc.)
    metadata: Dict[str, Any] = {}  # Additional metadata

    def to_json(self) -> Dict[str, Any]:
        """Convert to Panel-compatible JSON."""
        data = super().to_json()
        data["chunkType"] = self.chunk_type.value
        return data

    @classmethod
    def from_json(cls, data: Dict[str, Any]) -> CodeChunk:
        """Deserialize from Panel JSON."""
        return cls(
            id=data["id"],
            file_path=data["filePath"],
            relative_path=data["relativePath"],
            chunk_type=ChunkType(data["chunkType"]),
            content=data["content"],
            start_line=data["startLine"],
            end_line=data["endLine"],
            language=data["language"],
            metadata=data.get("metadata", {}),
        )

    @property
    def line_count(self) -> int:
        """Calculate number of lines in this chunk."""
        return self.end_line - self.start_line + 1

    @property
    def char_count(self) -> int:
        """Calculate character count of content."""
        return len(self.content)


class EmbeddingMetadata(BaseDomainModel):
    """
    Metadata about generated embeddings.

    Tracks embedding generation details for observability.
    """

    model_name: str  # Embedding model used (text-embedding-3-small, etc.)
    dimensions: int  # Vector dimensions
    token_count: int  # Tokens consumed
    generated_at: datetime
    provider: str  # Provider (openai, azure_openai, local)
    metadata: Dict[str, Any] = {}

    @classmethod
    def from_json(cls, data: Dict[str, Any]) -> EmbeddingMetadata:
        """Deserialize from Panel JSON."""
        return cls(
            model_name=data["modelName"],
            dimensions=data["dimensions"],
            token_count=data["tokenCount"],
            generated_at=datetime.fromisoformat(data["generatedAt"]),
            provider=data["provider"],
            metadata=data.get("metadata", {}),
        )


class SearchResult(BaseDomainModel):
    """
    A single search result from semantic code search.

    Represents a code chunk matching a semantic query.
    """

    chunk: CodeChunk
    score: float  # Similarity score (0.0 to 1.0)
    rank: int  # Result rank in search results
    embedding_metadata: Optional[EmbeddingMetadata] = None
    metadata: Dict[str, Any] = {}

    def to_json(self) -> Dict[str, Any]:
        """Convert to Panel-compatible JSON."""
        data = super().to_json()
        data["chunk"] = self.chunk.to_json()
        if self.embedding_metadata:
            data["embeddingMetadata"] = self.embedding_metadata.to_json()
        return data

    @classmethod
    def from_json(cls, data: Dict[str, Any]) -> SearchResult:
        """Deserialize from Panel JSON."""
        chunk = CodeChunk.from_json(data["chunk"])
        embedding_metadata = None
        if data.get("embeddingMetadata"):
            embedding_metadata = EmbeddingMetadata.from_json(data["embeddingMetadata"])

        return cls(
            chunk=chunk,
            score=data["score"],
            rank=data["rank"],
            embedding_metadata=embedding_metadata,
            metadata=data.get("metadata", {}),
        )

    @property
    def is_high_confidence(self) -> bool:
        """Check if this is a high-confidence match (score > 0.8)."""
        return self.score > 0.8

    @property
    def is_relevant(self) -> bool:
        """Check if this result is likely relevant (score > 0.5)."""
        return self.score > 0.5


class SearchQuery(BaseDomainModel):
    """
    A semantic search query for code.

    Encapsulates search parameters and filters.
    """

    query_text: str  # Natural language or code query
    limit: int = 10  # Maximum results to return
    min_score: float = 0.5  # Minimum similarity score threshold
    file_filters: List[str] = []  # File path patterns to include
    language_filters: List[str] = []  # Languages to search
    chunk_type_filters: List[ChunkType] = []  # Chunk types to include
    metadata: Dict[str, Any] = {}

    def to_json(self) -> Dict[str, Any]:
        """Convert to Panel-compatible JSON."""
        data = super().to_json()
        data["chunkTypeFilters"] = [ct.value for ct in self.chunk_type_filters]
        return data

    @classmethod
    def from_json(cls, data: Dict[str, Any]) -> SearchQuery:
        """Deserialize from Panel JSON."""
        chunk_types = [ChunkType(ct) for ct in data.get("chunkTypeFilters", [])]

        return cls(
            query_text=data["queryText"],
            limit=data.get("limit", 10),
            min_score=data.get("minScore", 0.5),
            file_filters=data.get("fileFilters", []),
            language_filters=data.get("languageFilters", []),
            chunk_type_filters=chunk_types,
            metadata=data.get("metadata", {}),
        )


class SearchResponse(BaseDomainModel):
    """
    Response from semantic search operation.

    Contains all matching results and query metadata.
    """

    query: SearchQuery
    results: List[SearchResult] = []
    total_results: int = 0
    search_duration_seconds: float = 0.0
    metadata: Dict[str, Any] = {}

    def to_json(self) -> Dict[str, Any]:
        """Convert to Panel-compatible JSON."""
        data = super().to_json()
        data["query"] = self.query.to_json()
        data["results"] = [r.to_json() for r in self.results]
        return data

    @classmethod
    def from_json(cls, data: Dict[str, Any]) -> SearchResponse:
        """Deserialize from Panel JSON."""
        query = SearchQuery.from_json(data["query"])
        results = [SearchResult.from_json(r) for r in data.get("results", [])]

        return cls(
            query=query,
            results=results,
            total_results=data.get("totalResults", 0),
            search_duration_seconds=data.get("searchDurationSeconds", 0.0),
            metadata=data.get("metadata", {}),
        )

    @property
    def has_results(self) -> bool:
        """Check if search returned any results."""
        return len(self.results) > 0

    def get_high_confidence_results(self) -> List[SearchResult]:
        """Get only high-confidence results (score > 0.8)."""
        return [r for r in self.results if r.is_high_confidence]


class IndexStats(BaseDomainModel):
    """
    Statistics about the code index.

    Tracks index size and composition.
    """

    total_chunks: int = 0
    chunks_by_language: Dict[str, int] = {}  # language -> count
    chunks_by_type: Dict[str, int] = {}  # chunk_type -> count
    total_files_indexed: int = 0
    index_size_bytes: int = 0
    last_indexed_at: Optional[datetime] = None
    metadata: Dict[str, Any] = {}

    @classmethod
    def from_json(cls, data: Dict[str, Any]) -> IndexStats:
        """Deserialize from Panel JSON."""
        last_indexed = None
        if data.get("lastIndexedAt"):
            last_indexed = datetime.fromisoformat(data["lastIndexedAt"])

        return cls(
            total_chunks=data.get("totalChunks", 0),
            chunks_by_language=data.get("chunksByLanguage", {}),
            chunks_by_type=data.get("chunksByType", {}),
            total_files_indexed=data.get("totalFilesIndexed", 0),
            index_size_bytes=data.get("indexSizeBytes", 0),
            last_indexed_at=last_indexed,
            metadata=data.get("metadata", {}),
        )


class RetrievalContext(BaseDomainModel):
    """
    Context retrieved for LLM analysis.

    Aggregates multiple search results for context-aware analysis.
    """

    query_text: str
    relevant_chunks: List[CodeChunk] = []
    total_tokens: int = 0  # Estimated tokens in context
    total_characters: int = 0
    search_scores: List[float] = []  # Corresponding scores
    metadata: Dict[str, Any] = {}

    def to_json(self) -> Dict[str, Any]:
        """Convert to Panel-compatible JSON."""
        data = super().to_json()
        data["relevantChunks"] = [c.to_json() for c in self.relevant_chunks]
        return data

    @classmethod
    def from_json(cls, data: Dict[str, Any]) -> RetrievalContext:
        """Deserialize from Panel JSON."""
        chunks = [CodeChunk.from_json(c) for c in data.get("relevantChunks", [])]

        return cls(
            query_text=data["queryText"],
            relevant_chunks=chunks,
            total_tokens=data.get("totalTokens", 0),
            total_characters=data.get("totalCharacters", 0),
            search_scores=data.get("searchScores", []),
            metadata=data.get("metadata", {}),
        )

    @property
    def chunk_count(self) -> int:
        """Get number of chunks in context."""
        return len(self.relevant_chunks)

    @property
    def average_score(self) -> float:
        """Calculate average search score."""
        if not self.search_scores:
            return 0.0
        return sum(self.search_scores) / len(self.search_scores)
