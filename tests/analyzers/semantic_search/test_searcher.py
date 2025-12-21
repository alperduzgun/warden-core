"""
Tests for semantic searcher.

Tests vector similarity search operations.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from warden.analyzers.semantic_search.models import ChunkType, SearchQuery
from warden.analyzers.semantic_search.searcher import SemanticSearcher


class TestSemanticSearcher:
    """Test SemanticSearcher class."""

    @pytest.fixture
    def mock_embedding_generator(self) -> MagicMock:
        """Create mock embedding generator."""
        generator = MagicMock()
        generator.generate_embedding = AsyncMock(
            return_value=(
                [0.1] * 1536,
                MagicMock(),
            )
        )
        return generator

    @pytest.fixture
    def mock_qdrant_client(self) -> MagicMock:
        """Create mock Qdrant client."""
        client = MagicMock()

        # Mock search response
        mock_point = MagicMock()
        mock_point.id = 1
        mock_point.score = 0.9
        mock_point.payload = {
            "chunk_id": "chunk123",
            "file_path": "/test.py",
            "relative_path": "test.py",
            "chunk_type": "function",
            "content": "def hello():\n    pass",
            "start_line": 10,
            "end_line": 11,
            "language": "python",
            "metadata": {},
        }

        client.search = AsyncMock(return_value=[mock_point])
        return client

    def test_searcher_initialization(self, mock_embedding_generator: MagicMock) -> None:
        """Test searcher initialization."""
        with patch(
            "warden.analyzers.semantic_search.searcher.AsyncQdrantClient"
        ) as mock_client_class:
            mock_client_class.return_value = MagicMock()

            searcher = SemanticSearcher(
                qdrant_url="http://localhost:6333",
                qdrant_api_key=None,
                collection_name="test_collection",
                embedding_generator=mock_embedding_generator,
            )

            assert searcher.collection_name == "test_collection"
            assert searcher.embedding_generator == mock_embedding_generator

    @pytest.mark.asyncio
    async def test_search(
        self, mock_embedding_generator: MagicMock, mock_qdrant_client: MagicMock
    ) -> None:
        """Test basic search."""
        with patch(
            "warden.analyzers.semantic_search.searcher.AsyncQdrantClient",
            return_value=mock_qdrant_client,
        ):
            searcher = SemanticSearcher(
                qdrant_url="http://localhost:6333",
                qdrant_api_key=None,
                collection_name="test_collection",
                embedding_generator=mock_embedding_generator,
            )

            query = SearchQuery(
                query_text="authentication function",
                limit=10,
                min_score=0.5,
            )

            response = await searcher.search(query)

            assert response.total_results == 1
            assert len(response.results) == 1
            assert response.results[0].score == 0.9
            assert response.results[0].chunk.language == "python"

    @pytest.mark.asyncio
    async def test_search_similar_code(
        self, mock_embedding_generator: MagicMock, mock_qdrant_client: MagicMock
    ) -> None:
        """Test searching for similar code."""
        with patch(
            "warden.analyzers.semantic_search.searcher.AsyncQdrantClient",
            return_value=mock_qdrant_client,
        ):
            searcher = SemanticSearcher(
                qdrant_url="http://localhost:6333",
                qdrant_api_key=None,
                collection_name="test_collection",
                embedding_generator=mock_embedding_generator,
            )

            results = await searcher.search_similar_code(
                code_snippet="def test():\n    pass",
                language="python",
                limit=5,
            )

            assert len(results) == 1
            assert results[0].chunk.language == "python"

    @pytest.mark.asyncio
    async def test_search_by_description(
        self, mock_embedding_generator: MagicMock, mock_qdrant_client: MagicMock
    ) -> None:
        """Test searching by natural language description."""
        with patch(
            "warden.analyzers.semantic_search.searcher.AsyncQdrantClient",
            return_value=mock_qdrant_client,
        ):
            searcher = SemanticSearcher(
                qdrant_url="http://localhost:6333",
                qdrant_api_key=None,
                collection_name="test_collection",
                embedding_generator=mock_embedding_generator,
            )

            results = await searcher.search_by_description(
                description="user authentication with JWT",
                language="python",
                limit=5,
            )

            assert len(results) == 1

    @pytest.mark.asyncio
    async def test_find_function_implementations(
        self, mock_embedding_generator: MagicMock, mock_qdrant_client: MagicMock
    ) -> None:
        """Test finding function implementations."""
        with patch(
            "warden.analyzers.semantic_search.searcher.AsyncQdrantClient",
            return_value=mock_qdrant_client,
        ):
            searcher = SemanticSearcher(
                qdrant_url="http://localhost:6333",
                qdrant_api_key=None,
                collection_name="test_collection",
                embedding_generator=mock_embedding_generator,
            )

            results = await searcher.find_function_implementations(
                function_description="validate email address",
                language="python",
            )

            assert len(results) == 1

    def test_build_filter_language(self, mock_embedding_generator: MagicMock) -> None:
        """Test building filter with language."""
        with patch(
            "warden.analyzers.semantic_search.searcher.AsyncQdrantClient"
        ) as mock_client_class:
            mock_client_class.return_value = MagicMock()

            searcher = SemanticSearcher(
                qdrant_url="http://localhost:6333",
                qdrant_api_key=None,
                collection_name="test_collection",
                embedding_generator=mock_embedding_generator,
            )

            query = SearchQuery(
                query_text="test",
                language_filters=["python", "javascript"],
            )

            qdrant_filter = searcher._build_filter(query)

            assert qdrant_filter is not None

    def test_build_filter_chunk_type(self, mock_embedding_generator: MagicMock) -> None:
        """Test building filter with chunk type."""
        with patch(
            "warden.analyzers.semantic_search.searcher.AsyncQdrantClient"
        ) as mock_client_class:
            mock_client_class.return_value = MagicMock()

            searcher = SemanticSearcher(
                qdrant_url="http://localhost:6333",
                qdrant_api_key=None,
                collection_name="test_collection",
                embedding_generator=mock_embedding_generator,
            )

            query = SearchQuery(
                query_text="test",
                chunk_type_filters=[ChunkType.FUNCTION],
            )

            qdrant_filter = searcher._build_filter(query)

            assert qdrant_filter is not None

    def test_build_filter_empty(self, mock_embedding_generator: MagicMock) -> None:
        """Test building filter with no filters."""
        with patch(
            "warden.analyzers.semantic_search.searcher.AsyncQdrantClient"
        ) as mock_client_class:
            mock_client_class.return_value = MagicMock()

            searcher = SemanticSearcher(
                qdrant_url="http://localhost:6333",
                qdrant_api_key=None,
                collection_name="test_collection",
                embedding_generator=mock_embedding_generator,
            )

            query = SearchQuery(query_text="test")

            qdrant_filter = searcher._build_filter(query)

            assert qdrant_filter is None
