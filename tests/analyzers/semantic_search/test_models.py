"""
Tests for semantic search models.

Validates model creation, Panel JSON compatibility, and business logic.
"""

from datetime import datetime

import pytest

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


class TestChunkType:
    """Test ChunkType enum."""

    def test_chunk_type_values(self) -> None:
        """Test enum values match expected strings."""
        assert ChunkType.FUNCTION.value == "function"
        assert ChunkType.CLASS.value == "class"
        assert ChunkType.MODULE.value == "module"
        assert ChunkType.BLOCK.value == "block"

    def test_default_size_property(self) -> None:
        """Test default size property for each chunk type."""
        assert ChunkType.FUNCTION.default_size == 100
        assert ChunkType.CLASS.default_size == 200
        assert ChunkType.MODULE.default_size == 500
        assert ChunkType.BLOCK.default_size == 50


class TestCodeChunk:
    """Test CodeChunk model."""

    def test_code_chunk_creation(self) -> None:
        """Test creating a code chunk."""
        chunk = CodeChunk(
            id="chunk123",
            file_path="/path/to/file.py",
            relative_path="file.py",
            chunk_type=ChunkType.FUNCTION,
            content="def hello():\n    pass",
            start_line=10,
            end_line=11,
            language="python",
        )

        assert chunk.id == "chunk123"
        assert chunk.file_path == "/path/to/file.py"
        assert chunk.chunk_type == ChunkType.FUNCTION
        assert chunk.start_line == 10
        assert chunk.end_line == 11

    def test_line_count_property(self) -> None:
        """Test line_count property calculation."""
        chunk = CodeChunk(
            id="chunk123",
            file_path="/path/to/file.py",
            relative_path="file.py",
            chunk_type=ChunkType.FUNCTION,
            content="def hello():\n    pass",
            start_line=10,
            end_line=15,
            language="python",
        )

        assert chunk.line_count == 6  # 15 - 10 + 1

    def test_char_count_property(self) -> None:
        """Test char_count property calculation."""
        content = "def hello():\n    pass"
        chunk = CodeChunk(
            id="chunk123",
            file_path="/path/to/file.py",
            relative_path="file.py",
            chunk_type=ChunkType.FUNCTION,
            content=content,
            start_line=10,
            end_line=11,
            language="python",
        )

        assert chunk.char_count == len(content)

    def test_to_json_camelcase(self) -> None:
        """Test JSON serialization uses camelCase."""
        chunk = CodeChunk(
            id="chunk123",
            file_path="/path/to/file.py",
            relative_path="file.py",
            chunk_type=ChunkType.FUNCTION,
            content="def hello():\n    pass",
            start_line=10,
            end_line=11,
            language="python",
            metadata={"function_name": "hello"},
        )

        json_data = chunk.to_json()

        assert "filePath" in json_data
        assert "relativePath" in json_data
        assert "chunkType" in json_data
        assert "startLine" in json_data
        assert "endLine" in json_data
        assert json_data["chunkType"] == "function"
        assert json_data["startLine"] == 10

    def test_from_json_deserialization(self) -> None:
        """Test Panel JSON deserialization."""
        json_data = {
            "id": "chunk123",
            "filePath": "/path/to/file.py",
            "relativePath": "file.py",
            "chunkType": "function",
            "content": "def hello():\n    pass",
            "startLine": 10,
            "endLine": 11,
            "language": "python",
            "metadata": {"function_name": "hello"},
        }

        chunk = CodeChunk.from_json(json_data)

        assert chunk.id == "chunk123"
        assert chunk.file_path == "/path/to/file.py"
        assert chunk.chunk_type == ChunkType.FUNCTION
        assert chunk.start_line == 10
        assert chunk.metadata["function_name"] == "hello"

    def test_json_roundtrip(self) -> None:
        """Test JSON serialization roundtrip."""
        original = CodeChunk(
            id="chunk123",
            file_path="/path/to/file.py",
            relative_path="file.py",
            chunk_type=ChunkType.FUNCTION,
            content="def hello():\n    pass",
            start_line=10,
            end_line=11,
            language="python",
        )

        json_data = original.to_json()
        restored = CodeChunk.from_json(json_data)

        assert restored.id == original.id
        assert restored.file_path == original.file_path
        assert restored.chunk_type == original.chunk_type
        assert restored.content == original.content


class TestEmbeddingMetadata:
    """Test EmbeddingMetadata model."""

    def test_embedding_metadata_creation(self) -> None:
        """Test creating embedding metadata."""
        now = datetime.now()
        metadata = EmbeddingMetadata(
            model_name="text-embedding-3-small",
            dimensions=1536,
            token_count=100,
            generated_at=now,
            provider="openai",
        )

        assert metadata.model_name == "text-embedding-3-small"
        assert metadata.dimensions == 1536
        assert metadata.token_count == 100
        assert metadata.provider == "openai"

    def test_to_json_camelcase(self) -> None:
        """Test JSON serialization uses camelCase."""
        now = datetime.now()
        metadata = EmbeddingMetadata(
            model_name="text-embedding-3-small",
            dimensions=1536,
            token_count=100,
            generated_at=now,
            provider="openai",
        )

        json_data = metadata.to_json()

        assert "modelName" in json_data
        assert "tokenCount" in json_data
        assert "generatedAt" in json_data
        assert json_data["modelName"] == "text-embedding-3-small"


class TestSearchResult:
    """Test SearchResult model."""

    def test_search_result_creation(self) -> None:
        """Test creating a search result."""
        chunk = CodeChunk(
            id="chunk123",
            file_path="/path/to/file.py",
            relative_path="file.py",
            chunk_type=ChunkType.FUNCTION,
            content="def hello():\n    pass",
            start_line=10,
            end_line=11,
            language="python",
        )

        result = SearchResult(
            chunk=chunk,
            score=0.95,
            rank=1,
        )

        assert result.chunk == chunk
        assert result.score == 0.95
        assert result.rank == 1

    def test_is_high_confidence(self) -> None:
        """Test is_high_confidence property."""
        chunk = CodeChunk(
            id="chunk123",
            file_path="/path/to/file.py",
            relative_path="file.py",
            chunk_type=ChunkType.FUNCTION,
            content="def hello():\n    pass",
            start_line=10,
            end_line=11,
            language="python",
        )

        high_result = SearchResult(chunk=chunk, score=0.85, rank=1)
        low_result = SearchResult(chunk=chunk, score=0.7, rank=2)

        assert high_result.is_high_confidence is True
        assert low_result.is_high_confidence is False

    def test_is_relevant(self) -> None:
        """Test is_relevant property."""
        chunk = CodeChunk(
            id="chunk123",
            file_path="/path/to/file.py",
            relative_path="file.py",
            chunk_type=ChunkType.FUNCTION,
            content="def hello():\n    pass",
            start_line=10,
            end_line=11,
            language="python",
        )

        relevant_result = SearchResult(chunk=chunk, score=0.6, rank=1)
        irrelevant_result = SearchResult(chunk=chunk, score=0.4, rank=2)

        assert relevant_result.is_relevant is True
        assert irrelevant_result.is_relevant is False


class TestSearchQuery:
    """Test SearchQuery model."""

    def test_search_query_creation(self) -> None:
        """Test creating a search query."""
        query = SearchQuery(
            query_text="authentication function",
            limit=10,
            min_score=0.5,
            language_filters=["python"],
        )

        assert query.query_text == "authentication function"
        assert query.limit == 10
        assert query.min_score == 0.5
        assert query.language_filters == ["python"]

    def test_to_json_chunk_type_filters(self) -> None:
        """Test chunk type filters serialization."""
        query = SearchQuery(
            query_text="test",
            chunk_type_filters=[ChunkType.FUNCTION, ChunkType.CLASS],
        )

        json_data = query.to_json()

        assert json_data["chunkTypeFilters"] == ["function", "class"]

    def test_from_json_deserialization(self) -> None:
        """Test deserialization from Panel JSON."""
        json_data = {
            "queryText": "authentication function",
            "limit": 10,
            "minScore": 0.5,
            "languageFilters": ["python"],
            "chunkTypeFilters": ["function"],
            "fileFilters": [],
        }

        query = SearchQuery.from_json(json_data)

        assert query.query_text == "authentication function"
        assert query.limit == 10
        assert query.chunk_type_filters == [ChunkType.FUNCTION]


class TestSearchResponse:
    """Test SearchResponse model."""

    def test_search_response_creation(self) -> None:
        """Test creating a search response."""
        query = SearchQuery(query_text="test", limit=10)
        chunk = CodeChunk(
            id="chunk123",
            file_path="/path/to/file.py",
            relative_path="file.py",
            chunk_type=ChunkType.FUNCTION,
            content="def hello():\n    pass",
            start_line=10,
            end_line=11,
            language="python",
        )
        result = SearchResult(chunk=chunk, score=0.9, rank=1)

        response = SearchResponse(
            query=query,
            results=[result],
            total_results=1,
            search_duration_seconds=0.5,
        )

        assert response.query == query
        assert len(response.results) == 1
        assert response.total_results == 1
        assert response.search_duration_seconds == 0.5

    def test_has_results(self) -> None:
        """Test has_results property."""
        query = SearchQuery(query_text="test", limit=10)

        empty_response = SearchResponse(query=query, results=[])
        non_empty_response = SearchResponse(
            query=query,
            results=[
                SearchResult(
                    chunk=CodeChunk(
                        id="chunk123",
                        file_path="/path/to/file.py",
                        relative_path="file.py",
                        chunk_type=ChunkType.FUNCTION,
                        content="def hello():\n    pass",
                        start_line=10,
                        end_line=11,
                        language="python",
                    ),
                    score=0.9,
                    rank=1,
                )
            ],
        )

        assert empty_response.has_results is False
        assert non_empty_response.has_results is True

    def test_get_high_confidence_results(self) -> None:
        """Test filtering high-confidence results."""
        query = SearchQuery(query_text="test", limit=10)
        chunk = CodeChunk(
            id="chunk123",
            file_path="/path/to/file.py",
            relative_path="file.py",
            chunk_type=ChunkType.FUNCTION,
            content="def hello():\n    pass",
            start_line=10,
            end_line=11,
            language="python",
        )

        response = SearchResponse(
            query=query,
            results=[
                SearchResult(chunk=chunk, score=0.9, rank=1),
                SearchResult(chunk=chunk, score=0.6, rank=2),
                SearchResult(chunk=chunk, score=0.85, rank=3),
            ],
        )

        high_conf = response.get_high_confidence_results()

        assert len(high_conf) == 2
        assert all(r.score > 0.8 for r in high_conf)


class TestIndexStats:
    """Test IndexStats model."""

    def test_index_stats_creation(self) -> None:
        """Test creating index stats."""
        stats = IndexStats(
            total_chunks=100,
            chunks_by_language={"python": 80, "javascript": 20},
            total_files_indexed=10,
        )

        assert stats.total_chunks == 100
        assert stats.chunks_by_language["python"] == 80
        assert stats.total_files_indexed == 10


class TestRetrievalContext:
    """Test RetrievalContext model."""

    def test_retrieval_context_creation(self) -> None:
        """Test creating retrieval context."""
        chunk = CodeChunk(
            id="chunk123",
            file_path="/path/to/file.py",
            relative_path="file.py",
            chunk_type=ChunkType.FUNCTION,
            content="def hello():\n    pass",
            start_line=10,
            end_line=11,
            language="python",
        )

        context = RetrievalContext(
            query_text="authentication",
            relevant_chunks=[chunk],
            total_tokens=100,
            total_characters=500,
            search_scores=[0.9],
        )

        assert context.query_text == "authentication"
        assert len(context.relevant_chunks) == 1
        assert context.total_tokens == 100

    def test_chunk_count_property(self) -> None:
        """Test chunk_count property."""
        chunk = CodeChunk(
            id="chunk123",
            file_path="/path/to/file.py",
            relative_path="file.py",
            chunk_type=ChunkType.FUNCTION,
            content="def hello():\n    pass",
            start_line=10,
            end_line=11,
            language="python",
        )

        context = RetrievalContext(
            query_text="test",
            relevant_chunks=[chunk, chunk],
            search_scores=[0.9, 0.8],
        )

        assert context.chunk_count == 2

    def test_average_score_property(self) -> None:
        """Test average_score calculation."""
        chunk = CodeChunk(
            id="chunk123",
            file_path="/path/to/file.py",
            relative_path="file.py",
            chunk_type=ChunkType.FUNCTION,
            content="def hello():\n    pass",
            start_line=10,
            end_line=11,
            language="python",
        )

        context = RetrievalContext(
            query_text="test",
            relevant_chunks=[chunk, chunk, chunk],
            search_scores=[0.9, 0.8, 0.7],
        )

        assert context.average_score == pytest.approx(0.8, rel=0.01)

    def test_average_score_empty(self) -> None:
        """Test average_score returns 0 for empty scores."""
        context = RetrievalContext(
            query_text="test",
            relevant_chunks=[],
            search_scores=[],
        )

        assert context.average_score == 0.0
