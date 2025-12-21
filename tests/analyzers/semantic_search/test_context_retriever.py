"""
Tests for context retrieval.

Tests LLM context retrieval and optimization.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from warden.analyzers.semantic_search.context_retriever import (
    ContextOptimizer,
    ContextRetriever,
)
from warden.analyzers.semantic_search.models import (
    ChunkType,
    CodeChunk,
    SearchQuery,
    SearchResponse,
    SearchResult,
)


class TestContextRetriever:
    """Test ContextRetriever class."""

    @pytest.fixture
    def mock_searcher(self) -> MagicMock:
        """Create mock semantic searcher."""
        searcher = MagicMock()

        # Create mock search results
        chunk = CodeChunk(
            id="chunk123",
            file_path="/test.py",
            relative_path="test.py",
            chunk_type=ChunkType.FUNCTION,
            content="def hello():\n    return 'world'",
            start_line=1,
            end_line=2,
            language="python",
        )

        result = SearchResult(chunk=chunk, score=0.9, rank=1)

        searcher.search = AsyncMock(
            return_value=SearchResponse(
                query=SearchQuery(query_text="test"),
                results=[result],
                total_results=1,
            )
        )

        return searcher

    def test_retriever_initialization(self, mock_searcher: MagicMock) -> None:
        """Test retriever initialization."""
        retriever = ContextRetriever(
            searcher=mock_searcher,
            max_tokens=4000,
            chars_per_token=4,
        )

        assert retriever.max_tokens == 4000
        assert retriever.chars_per_token == 4
        assert retriever.max_chars == 16000

    @pytest.mark.asyncio
    async def test_retrieve_context(self, mock_searcher: MagicMock) -> None:
        """Test retrieving context."""
        retriever = ContextRetriever(
            searcher=mock_searcher,
            max_tokens=4000,
        )

        context = await retriever.retrieve_context(
            query="authentication function",
            language="python",
            max_chunks=10,
        )

        assert context.query_text == "authentication function"
        assert len(context.relevant_chunks) == 1
        assert context.total_tokens > 0

    @pytest.mark.asyncio
    async def test_retrieve_multi_query_context(self, mock_searcher: MagicMock) -> None:
        """Test retrieving context for multiple queries."""
        retriever = ContextRetriever(
            searcher=mock_searcher,
            max_tokens=4000,
        )

        context = await retriever.retrieve_multi_query_context(
            queries=["authentication", "validation"],
            language="python",
            chunks_per_query=5,
        )

        assert "authentication" in context.query_text
        assert "validation" in context.query_text
        assert context.chunk_count >= 1

    @pytest.mark.asyncio
    async def test_retrieve_file_context(self, mock_searcher: MagicMock) -> None:
        """Test retrieving context for specific file."""
        retriever = ContextRetriever(
            searcher=mock_searcher,
            max_tokens=4000,
        )

        context = await retriever.retrieve_file_context(
            file_path="/test.py",
            max_chunks=10,
        )

        assert "/test.py" in context.query_text
        assert context.chunk_count >= 1

    def test_select_chunks_within_budget(self, mock_searcher: MagicMock) -> None:
        """Test chunk selection within token budget."""
        retriever = ContextRetriever(
            searcher=mock_searcher,
            max_tokens=100,  # Very small budget
            chars_per_token=4,
        )

        # Create chunks
        small_chunk = CodeChunk(
            id="chunk1",
            file_path="/test.py",
            relative_path="test.py",
            chunk_type=ChunkType.FUNCTION,
            content="def a(): pass",
            start_line=1,
            end_line=1,
            language="python",
        )

        large_chunk = CodeChunk(
            id="chunk2",
            file_path="/test.py",
            relative_path="test.py",
            chunk_type=ChunkType.FUNCTION,
            content="def b():\n" + "    " + "x = 1\n" * 1000,  # Very large
            start_line=3,
            end_line=1003,
            language="python",
        )

        results = [
            type("Result", (), {"chunk": small_chunk, "score": 0.9})(),
            type("Result", (), {"chunk": large_chunk, "score": 0.8})(),
        ]

        selected, scores = retriever._select_chunks_within_budget(results, max_chunks=10)

        # Should only select small chunk (large exceeds budget)
        assert len(selected) == 1
        assert selected[0].id == "chunk1"

    def test_format_context_for_llm(self, mock_searcher: MagicMock) -> None:
        """Test formatting context for LLM."""
        retriever = ContextRetriever(searcher=mock_searcher)

        chunk = CodeChunk(
            id="chunk1",
            file_path="/test.py",
            relative_path="test.py",
            chunk_type=ChunkType.FUNCTION,
            content="def hello():\n    return 'world'",
            start_line=1,
            end_line=2,
            language="python",
        )

        from warden.analyzers.semantic_search.models import RetrievalContext

        context = RetrievalContext(
            query_text="test query",
            relevant_chunks=[chunk],
            total_tokens=50,
            total_characters=200,
            search_scores=[0.9],
        )

        formatted = retriever.format_context_for_llm(context)

        assert "test query" in formatted
        assert "test.py" in formatted
        assert "def hello():" in formatted
        assert "Score: 0.90" in formatted


class TestContextOptimizer:
    """Test ContextOptimizer class."""

    def test_deduplicate_chunks(self) -> None:
        """Test chunk deduplication."""
        chunk1 = CodeChunk(
            id="chunk1",
            file_path="/test.py",
            relative_path="test.py",
            chunk_type=ChunkType.FUNCTION,
            content="def a(): pass",
            start_line=1,
            end_line=1,
            language="python",
        )

        chunk2 = CodeChunk(
            id="chunk1",  # Duplicate ID
            file_path="/test.py",
            relative_path="test.py",
            chunk_type=ChunkType.FUNCTION,
            content="def a(): pass",
            start_line=1,
            end_line=1,
            language="python",
        )

        chunk3 = CodeChunk(
            id="chunk3",
            file_path="/test.py",
            relative_path="test.py",
            chunk_type=ChunkType.FUNCTION,
            content="def b(): pass",
            start_line=3,
            end_line=3,
            language="python",
        )

        chunks = [chunk1, chunk2, chunk3]

        unique = ContextOptimizer.deduplicate_chunks(chunks)

        assert len(unique) == 2
        assert unique[0].id == "chunk1"
        assert unique[1].id == "chunk3"

    def test_sort_by_relevance(self) -> None:
        """Test sorting chunks by relevance."""
        chunk1 = CodeChunk(
            id="chunk1",
            file_path="/test.py",
            relative_path="test.py",
            chunk_type=ChunkType.FUNCTION,
            content="def a(): pass",
            start_line=1,
            end_line=1,
            language="python",
        )

        chunk2 = CodeChunk(
            id="chunk2",
            file_path="/test.py",
            relative_path="test.py",
            chunk_type=ChunkType.FUNCTION,
            content="def b(): pass",
            start_line=3,
            end_line=3,
            language="python",
        )

        chunks = [chunk1, chunk2]
        scores = [0.6, 0.9]

        sorted_chunks, sorted_scores = ContextOptimizer.sort_by_relevance(chunks, scores)

        assert sorted_chunks[0].id == "chunk2"  # Higher score first
        assert sorted_scores[0] == 0.9

    def test_filter_by_score(self) -> None:
        """Test filtering chunks by minimum score."""
        chunk1 = CodeChunk(
            id="chunk1",
            file_path="/test.py",
            relative_path="test.py",
            chunk_type=ChunkType.FUNCTION,
            content="def a(): pass",
            start_line=1,
            end_line=1,
            language="python",
        )

        chunk2 = CodeChunk(
            id="chunk2",
            file_path="/test.py",
            relative_path="test.py",
            chunk_type=ChunkType.FUNCTION,
            content="def b(): pass",
            start_line=3,
            end_line=3,
            language="python",
        )

        chunks = [chunk1, chunk2]
        scores = [0.4, 0.9]

        filtered_chunks, filtered_scores = ContextOptimizer.filter_by_score(
            chunks, scores, min_score=0.5
        )

        assert len(filtered_chunks) == 1
        assert filtered_chunks[0].id == "chunk2"
        assert filtered_scores[0] == 0.9

    def test_filter_by_score_none_pass(self) -> None:
        """Test filter returns empty when no chunks pass."""
        chunk1 = CodeChunk(
            id="chunk1",
            file_path="/test.py",
            relative_path="test.py",
            chunk_type=ChunkType.FUNCTION,
            content="def a(): pass",
            start_line=1,
            end_line=1,
            language="python",
        )

        chunks = [chunk1]
        scores = [0.3]

        filtered_chunks, filtered_scores = ContextOptimizer.filter_by_score(
            chunks, scores, min_score=0.5
        )

        assert len(filtered_chunks) == 0
        assert len(filtered_scores) == 0
