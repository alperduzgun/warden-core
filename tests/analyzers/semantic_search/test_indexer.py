"""
Tests for code indexer.

Tests code chunking and Qdrant indexing operations.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from warden.analyzers.semantic_search.indexer import CodeChunker, CodeIndexer
from warden.analyzers.semantic_search.models import ChunkType


class TestCodeChunker:
    """Test CodeChunker class."""

    def test_initialization(self) -> None:
        """Test chunker initialization."""
        chunker = CodeChunker(max_chunk_size=500)

        assert chunker.max_chunk_size == 500

    def test_chunk_python_file_functions(self) -> None:
        """Test chunking Python file extracts functions."""
        chunker = CodeChunker()

        code = """
def function_one():
    return 1

def function_two():
    return 2

class MyClass:
    def method(self):
        pass
"""

        chunks = chunker.chunk_python_file("/test.py", code)

        # Should extract 2 functions + 1 class
        assert len(chunks) >= 3

        function_chunks = [c for c in chunks if c.chunk_type == ChunkType.FUNCTION]
        class_chunks = [c for c in chunks if c.chunk_type == ChunkType.CLASS]

        assert len(function_chunks) == 2
        assert len(class_chunks) == 1

    def test_chunk_python_file_syntax_error(self) -> None:
        """Test chunking handles syntax errors gracefully."""
        chunker = CodeChunker()

        invalid_code = "def broken(:\n    pass"

        chunks = chunker.chunk_python_file("/test.py", invalid_code)

        # Should fallback to module-level chunk
        assert len(chunks) == 1
        assert chunks[0].chunk_type == ChunkType.MODULE

    def test_chunk_python_file_empty(self) -> None:
        """Test chunking empty file."""
        chunker = CodeChunker()

        chunks = chunker.chunk_python_file("/test.py", "")

        assert len(chunks) == 1
        assert chunks[0].chunk_type == ChunkType.MODULE

    def test_chunk_too_large_skipped(self) -> None:
        """Test large chunks are skipped."""
        chunker = CodeChunker(max_chunk_size=5)

        code = """
def large_function():
    line_1 = 1
    line_2 = 2
    line_3 = 3
    line_4 = 4
    line_5 = 5
    line_6 = 6
    line_7 = 7
    line_8 = 8
    return 9
"""

        chunks = chunker.chunk_python_file("/test.py", code)

        # Large function should be skipped, fallback to module
        assert len(chunks) == 1
        assert chunks[0].chunk_type == ChunkType.MODULE

    def test_extract_function_chunk(self) -> None:
        """Test extracting function chunk."""
        chunker = CodeChunker()

        code = """def hello():
    return "world"
"""

        chunks = chunker.chunk_python_file("/test.py", code)

        assert len(chunks) >= 1
        func_chunk = next((c for c in chunks if c.chunk_type == ChunkType.FUNCTION), None)

        assert func_chunk is not None
        assert "hello" in func_chunk.content
        assert func_chunk.metadata.get("function_name") == "hello"

    def test_extract_class_chunk(self) -> None:
        """Test extracting class chunk."""
        chunker = CodeChunker()

        code = """class MyClass:
    def method(self):
        pass
"""

        chunks = chunker.chunk_python_file("/test.py", code)

        assert len(chunks) >= 1
        class_chunk = next((c for c in chunks if c.chunk_type == ChunkType.CLASS), None)

        assert class_chunk is not None
        assert "MyClass" in class_chunk.content
        assert class_chunk.metadata.get("class_name") == "MyClass"

    def test_chunk_file_non_python(self) -> None:
        """Test chunking non-Python file falls back to module."""
        chunker = CodeChunker()

        with patch("builtins.open", MagicMock(side_effect=Exception("File not found"))):
            chunks = chunker.chunk_file("/test.js", "javascript")

            assert chunks == []


class TestCodeIndexer:
    """Test CodeIndexer class."""

    @pytest.fixture
    def mock_embedding_generator(self) -> MagicMock:
        """Create mock embedding generator."""
        generator = MagicMock()
        generator.dimensions = 1536
        generator.generate_chunk_embedding = AsyncMock(
            return_value=(
                [0.1] * 1536,
                MagicMock(model_name="test", dimensions=1536, token_count=50),
            )
        )
        return generator

    @pytest.fixture
    def mock_qdrant_client(self) -> MagicMock:
        """Create mock Qdrant client."""
        client = MagicMock()
        client.get_collections = AsyncMock(return_value=MagicMock(collections=[]))
        client.create_collection = AsyncMock()
        client.upsert = AsyncMock()
        client.get_collection = AsyncMock(
            return_value=MagicMock(points_count=100)
        )
        return client

    def test_indexer_initialization(self, mock_embedding_generator: MagicMock) -> None:
        """Test indexer initialization."""
        with patch(
            "warden.analyzers.semantic_search.indexer.AsyncQdrantClient"
        ) as mock_client_class:
            mock_client_class.return_value = MagicMock()

            indexer = CodeIndexer(
                qdrant_url="http://localhost:6333",
                qdrant_api_key=None,
                collection_name="test_collection",
                embedding_generator=mock_embedding_generator,
                chunk_size=500,
            )

            assert indexer.collection_name == "test_collection"
            assert indexer.embedding_generator == mock_embedding_generator

    @pytest.mark.asyncio
    async def test_ensure_collection_creates_new(
        self, mock_embedding_generator: MagicMock, mock_qdrant_client: MagicMock
    ) -> None:
        """Test ensure_collection creates new collection."""
        with patch(
            "warden.analyzers.semantic_search.indexer.AsyncQdrantClient",
            return_value=mock_qdrant_client,
        ):
            indexer = CodeIndexer(
                qdrant_url="http://localhost:6333",
                qdrant_api_key=None,
                collection_name="test_collection",
                embedding_generator=mock_embedding_generator,
            )

            await indexer.ensure_collection()

            mock_qdrant_client.create_collection.assert_called_once()

    @pytest.mark.asyncio
    async def test_ensure_collection_exists(
        self, mock_embedding_generator: MagicMock
    ) -> None:
        """Test ensure_collection when collection exists."""
        mock_client = MagicMock()
        existing_collection = MagicMock()
        existing_collection.name = "test_collection"
        mock_client.get_collections = AsyncMock(
            return_value=MagicMock(collections=[existing_collection])
        )

        with patch(
            "warden.analyzers.semantic_search.indexer.AsyncQdrantClient",
            return_value=mock_client,
        ):
            indexer = CodeIndexer(
                qdrant_url="http://localhost:6333",
                qdrant_api_key=None,
                collection_name="test_collection",
                embedding_generator=mock_embedding_generator,
            )

            await indexer.ensure_collection()

            # Should not create collection if it exists
            assert not hasattr(mock_client, "create_collection") or not mock_client.create_collection.called

    @pytest.mark.asyncio
    async def test_get_stats(
        self, mock_embedding_generator: MagicMock, mock_qdrant_client: MagicMock
    ) -> None:
        """Test getting index statistics."""
        with patch(
            "warden.analyzers.semantic_search.indexer.AsyncQdrantClient",
            return_value=mock_qdrant_client,
        ):
            indexer = CodeIndexer(
                qdrant_url="http://localhost:6333",
                qdrant_api_key=None,
                collection_name="test_collection",
                embedding_generator=mock_embedding_generator,
            )

            stats = await indexer.get_stats()

            assert stats.total_chunks == 100
