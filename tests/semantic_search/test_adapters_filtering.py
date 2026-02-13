"""
Tests for semantic search adapter filtering capabilities.

Tests the ChromaDB-style where clause translation to Qdrant filters.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch

# Check if qdrant_client is available
try:
    import qdrant_client
    HAS_QDRANT = True
except ImportError:
    HAS_QDRANT = False

from warden.semantic_search.adapters import QdrantAdapter

# Skip all tests in this module if qdrant_client is not installed
pytestmark = pytest.mark.skipif(not HAS_QDRANT, reason="qdrant-client not installed")


class TestQdrantFilterTranslation:
    """Test suite for Qdrant filter translation."""

    @pytest.fixture
    def adapter(self):
        """Create QdrantAdapter with mocked dependencies."""
        with patch('qdrant_client.QdrantClient') as mock_client_class:
            with patch('qdrant_client.http.models'):
                # Setup mocks
                mock_client = Mock()
                mock_client.collection_exists.return_value = True
                mock_client_class.return_value = mock_client

                # Create adapter
                adapter = QdrantAdapter(
                    url="http://localhost:6333",
                    api_key="test-key",
                    collection_name="test-collection"
                )
                return adapter

    def test_translate_simple_equality_filter(self, adapter):
        """Test simple equality filter: {"language": "python"}."""
        where = {"language": "python"}

        with patch('qdrant_client.http.models') as mock_models:
            # Setup mock
            mock_filter = Mock()
            mock_models.Filter.return_value = mock_filter
            mock_models.FieldCondition = Mock(return_value=Mock())
            mock_models.MatchValue = Mock(return_value=Mock())

            result = adapter._translate_where_to_filter(where)

            # Verify Filter was created
            assert mock_models.Filter.called
            # Verify FieldCondition was created with correct key
            assert mock_models.FieldCondition.call_count == 1
            call_kwargs = mock_models.FieldCondition.call_args[1]
            assert call_kwargs['key'] == 'language'

    def test_translate_in_operator(self, adapter):
        """Test $in operator: {"language": {"$in": ["python", "javascript"]}}."""
        where = {"language": {"$in": ["python", "javascript"]}}

        with patch('qdrant_client.http.models') as mock_models:
            mock_models.Filter = Mock(return_value=Mock())
            mock_models.FieldCondition = Mock(return_value=Mock())
            mock_models.MatchAny = Mock(return_value=Mock())

            result = adapter._translate_where_to_filter(where)

            # Verify MatchAny was used
            assert mock_models.MatchAny.called
            call_kwargs = mock_models.MatchAny.call_args[1]
            assert call_kwargs['any'] == ["python", "javascript"]

    def test_translate_and_operator(self, adapter):
        """Test $and operator with multiple conditions."""
        where = {
            "$and": [
                {"language": "python"},
                {"chunk_type": "function"}
            ]
        }

        with patch('qdrant_client.http.models') as mock_models:
            mock_models.Filter = Mock(return_value=Mock())
            mock_models.FieldCondition = Mock(return_value=Mock())
            mock_models.MatchValue = Mock(return_value=Mock())

            result = adapter._translate_where_to_filter(where)

            # Verify multiple FieldConditions were created
            assert mock_models.FieldCondition.call_count == 2

    def test_translate_eq_operator(self, adapter):
        """Test explicit $eq operator: {"language": {"$eq": "python"}}."""
        where = {"language": {"$eq": "python"}}

        with patch('qdrant_client.http.models') as mock_models:
            mock_models.Filter = Mock(return_value=Mock())
            mock_models.FieldCondition = Mock(return_value=Mock())
            mock_models.MatchValue = Mock(return_value=Mock())

            result = adapter._translate_where_to_filter(where)

            # Verify MatchValue was used
            assert mock_models.MatchValue.called

    def test_translate_ne_operator(self, adapter):
        """Test $ne operator: {"language": {"$ne": "unknown"}}."""
        where = {"language": {"$ne": "unknown"}}

        with patch('qdrant_client.http.models') as mock_models:
            mock_models.Filter = Mock(return_value=Mock())
            mock_models.FieldCondition = Mock(return_value=Mock())
            mock_models.MatchExcept = Mock(return_value=Mock())

            result = adapter._translate_where_to_filter(where)

            # Verify MatchExcept was used
            assert mock_models.MatchExcept.called

    def test_translate_empty_filter(self, adapter):
        """Test empty filter returns None."""
        result = adapter._translate_where_to_filter(None)
        assert result is None

        result = adapter._translate_where_to_filter({})
        assert result is None

    def test_translate_complex_filter(self, adapter):
        """Test complex real-world filter."""
        where = {
            "$and": [
                {"language": {"$in": ["python", "javascript"]}},
                {"chunk_type": "function"},
                {"relative_path": "src/main.py"}
            ]
        }

        with patch('qdrant_client.http.models') as mock_models:
            mock_models.Filter = Mock(return_value=Mock())
            mock_models.FieldCondition = Mock(return_value=Mock())
            mock_models.MatchValue = Mock(return_value=Mock())
            mock_models.MatchAny = Mock(return_value=Mock())

            result = adapter._translate_where_to_filter(where)

            # Verify multiple conditions were created
            assert mock_models.FieldCondition.call_count == 3

    def test_translate_unsupported_operator_logs_warning(self, adapter):
        """Test unsupported operator logs warning but doesn't crash."""
        where = {"language": {"$unsupported": "value"}}

        with patch('qdrant_client.http.models') as mock_models:
            with patch('warden.semantic_search.adapters.logger') as mock_logger:
                mock_models.Filter = Mock(return_value=Mock())
                mock_models.FieldCondition = Mock(return_value=Mock())

                result = adapter._translate_where_to_filter(where)

                # Verify warning was logged
                assert mock_logger.warning.called
                call_args = mock_logger.warning.call_args[0]
                assert "unsupported_filter_operator" in call_args

    def test_translate_handles_exceptions_gracefully(self, adapter):
        """Test filter translation handles exceptions and returns None."""
        where = {"language": "python"}

        with patch('qdrant_client.http.models') as mock_models:
            # Make models raise exception
            mock_models.Filter.side_effect = Exception("Test exception")

            with patch('warden.semantic_search.adapters.logger') as mock_logger:
                result = adapter._translate_where_to_filter(where)

                # Should return None on error
                assert result is None
                # Should log warning
                assert mock_logger.warning.called


class TestQdrantQueryWithFilters:
    """Test suite for Qdrant query with filtering."""

    @pytest.fixture
    def adapter(self):
        """Create QdrantAdapter with mocked dependencies."""
        with patch('qdrant_client.QdrantClient') as mock_client_class:
            with patch('qdrant_client.http.models'):
                # Setup mocks
                mock_client = Mock()
                mock_client.collection_exists.return_value = True
                mock_client_class.return_value = mock_client

                # Create adapter
                adapter = QdrantAdapter(
                    url="http://localhost:6333",
                    api_key="test-key",
                    collection_name="test-collection"
                )
                return adapter

    @pytest.mark.asyncio
    async def test_query_with_filter(self, adapter):
        """Test query uses translated filter."""
        # Setup mock response
        mock_point = Mock()
        mock_point.id = "test-id"
        mock_point.payload = {"language": "python", "document": "test content"}
        mock_point.score = 0.95

        mock_result = Mock()
        mock_result.points = [mock_point]
        adapter.client.query_points.return_value = mock_result

        # Execute query with filter
        query_embeddings = [[0.1] * 768]
        where = {"language": "python"}

        with patch('qdrant_client.http.models'):
            result = await adapter.query(
                query_embeddings=query_embeddings,
                n_results=5,
                where=where
            )

        # Verify result format
        assert "ids" in result
        assert "metadatas" in result
        assert "documents" in result
        assert "distances" in result

        # Verify data
        assert result["ids"][0][0] == "test-id"
        assert result["documents"][0][0] == "test content"

    @pytest.mark.asyncio
    async def test_query_without_filter(self, adapter):
        """Test query works without filter."""
        # Setup mock response
        mock_point = Mock()
        mock_point.id = "test-id"
        mock_point.payload = {"document": "test content"}
        mock_point.score = 0.95

        mock_result = Mock()
        mock_result.points = [mock_point]
        adapter.client.query_points.return_value = mock_result

        # Execute query without filter
        query_embeddings = [[0.1] * 768]

        with patch('qdrant_client.http.models'):
            result = await adapter.query(
                query_embeddings=query_embeddings,
                n_results=5,
                where=None
            )

        # Verify query was called with None filter
        assert adapter.client.query_points.called
        call_kwargs = adapter.client.query_points.call_args[1]
        assert call_kwargs.get('query_filter') is None

    @pytest.mark.asyncio
    async def test_query_fallback_on_filter_error(self, adapter):
        """Test query falls back to unfiltered search on filter error."""
        # First call fails, second succeeds
        mock_point = Mock()
        mock_point.id = "test-id"
        mock_point.payload = {"document": "test content"}
        mock_point.score = 0.95

        mock_result = Mock()
        mock_result.points = [mock_point]

        # First call with filter fails, second without filter succeeds
        adapter.client.query_points.side_effect = [
            Exception("Filter error"),
            mock_result
        ]

        query_embeddings = [[0.1] * 768]
        where = {"language": "python"}

        with patch('qdrant_client.http.models'):
            with patch('warden.semantic_search.adapters.logger'):
                result = await adapter.query(
                    query_embeddings=query_embeddings,
                    n_results=5,
                    where=where
                )

        # Should have tried twice
        assert adapter.client.query_points.call_count == 2
        # Should return fallback results
        assert result["ids"][0][0] == "test-id"

    @pytest.mark.asyncio
    async def test_query_returns_empty_on_complete_failure(self, adapter):
        """Test query returns empty dict on complete failure."""
        # All calls fail
        adapter.client.query_points.side_effect = Exception("Complete failure")

        query_embeddings = [[0.1] * 768]
        where = {"language": "python"}

        with patch('qdrant_client.http.models'):
            with patch('warden.semantic_search.adapters.logger'):
                result = await adapter.query(
                    query_embeddings=query_embeddings,
                    n_results=5,
                    where=where
                )

        # Should return empty dict
        assert result == {}
