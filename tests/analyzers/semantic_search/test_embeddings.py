"""
Tests for embedding generation.

Tests embedding generator, caching, and chunk ID generation.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from warden.analyzers.semantic_search.embeddings import (
    EmbeddingCache,
    EmbeddingGenerator,
)
from warden.analyzers.semantic_search.models import ChunkType, CodeChunk


class TestEmbeddingGenerator:
    """Test EmbeddingGenerator class."""

    def test_initialization_openai(self) -> None:
        """Test initializing with OpenAI provider."""
        generator = EmbeddingGenerator(
            provider="openai",
            model_name="text-embedding-3-small",
            api_key="test-key",
        )

        assert generator.provider == "openai"
        assert generator.model_name == "text-embedding-3-small"
        assert generator.dimensions == 1536

    def test_initialization_azure(self) -> None:
        """Test initializing with Azure OpenAI provider."""
        generator = EmbeddingGenerator(
            provider="azure_openai",
            model_name="text-embedding-3-small",
            api_key="test-key",
            azure_endpoint="https://test.openai.azure.com",
            azure_deployment="test-deployment",
        )

        assert generator.provider == "azure_openai"
        assert generator.azure_deployment == "test-deployment"

    def test_initialization_invalid_provider(self) -> None:
        """Test initialization fails with invalid provider."""
        with pytest.raises(ValueError, match="Unsupported provider"):
            EmbeddingGenerator(
                provider="invalid_provider",
                api_key="test-key",
            )

    def test_initialization_missing_api_key(self) -> None:
        """Test initialization fails without API key."""
        with pytest.raises(ValueError, match="api_key required"):
            EmbeddingGenerator(provider="openai")

    def test_get_default_dimensions(self) -> None:
        """Test default dimensions for different models."""
        generator = EmbeddingGenerator(
            provider="openai",
            api_key="test-key",
        )

        assert generator._get_default_dimensions("text-embedding-3-small") == 1536
        assert generator._get_default_dimensions("text-embedding-3-large") == 3072
        assert generator._get_default_dimensions("unknown-model") == 1536

    @pytest.mark.asyncio
    async def test_generate_embedding(self) -> None:
        """Test embedding generation."""
        generator = EmbeddingGenerator(
            provider="openai",
            api_key="test-key",
        )

        # Mock OpenAI client
        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[0.1] * 1536)]
        mock_response.usage.total_tokens = 50

        with patch.object(
            generator.client.embeddings, "create", new=AsyncMock(return_value=mock_response)
        ):
            embedding, metadata = await generator.generate_embedding("test code")

            assert len(embedding) == 1536
            assert metadata.model_name == "text-embedding-3-small"
            assert metadata.token_count == 50
            assert metadata.provider == "openai"

    @pytest.mark.asyncio
    async def test_generate_chunk_embedding(self) -> None:
        """Test generating embedding for code chunk."""
        generator = EmbeddingGenerator(
            provider="openai",
            api_key="test-key",
        )

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

        # Mock OpenAI client
        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[0.1] * 1536)]
        mock_response.usage.total_tokens = 50

        with patch.object(
            generator.client.embeddings, "create", new=AsyncMock(return_value=mock_response)
        ):
            embedding, metadata = await generator.generate_chunk_embedding(chunk)

            assert len(embedding) == 1536
            assert "chunk_id" in metadata.metadata
            assert metadata.metadata["language"] == "python"

    def test_prepare_chunk_text(self) -> None:
        """Test chunk text preparation for embedding."""
        generator = EmbeddingGenerator(
            provider="openai",
            api_key="test-key",
        )

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

        text = generator._prepare_chunk_text(chunk)

        assert "file.py" in text
        assert "python" in text
        assert "function" in text
        assert "def hello():" in text

    @pytest.mark.asyncio
    async def test_generate_batch_embeddings(self) -> None:
        """Test batch embedding generation."""
        generator = EmbeddingGenerator(
            provider="openai",
            api_key="test-key",
        )

        chunks = [
            CodeChunk(
                id=f"chunk{i}",
                file_path=f"/path/to/file{i}.py",
                relative_path=f"file{i}.py",
                chunk_type=ChunkType.FUNCTION,
                content=f"def func{i}():\n    pass",
                start_line=10,
                end_line=11,
                language="python",
            )
            for i in range(3)
        ]

        # Mock OpenAI client
        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[0.1] * 1536)]
        mock_response.usage.total_tokens = 50

        with patch.object(
            generator.client.embeddings, "create", new=AsyncMock(return_value=mock_response)
        ):
            results = await generator.generate_batch_embeddings(chunks, batch_size=2)

            assert len(results) == 3
            assert all(len(r[1]) == 1536 for r in results)

    def test_generate_chunk_id(self) -> None:
        """Test chunk ID generation is deterministic."""
        chunk1 = CodeChunk(
            id="",
            file_path="/path/to/file.py",
            relative_path="file.py",
            chunk_type=ChunkType.FUNCTION,
            content="def hello():\n    pass",
            start_line=10,
            end_line=11,
            language="python",
        )

        chunk2 = CodeChunk(
            id="",
            file_path="/path/to/file.py",
            relative_path="file.py",
            chunk_type=ChunkType.FUNCTION,
            content="def hello():\n    pass",
            start_line=10,
            end_line=11,
            language="python",
        )

        id1 = EmbeddingGenerator.generate_chunk_id(chunk1)
        id2 = EmbeddingGenerator.generate_chunk_id(chunk2)

        assert id1 == id2  # Same content = same ID
        assert len(id1) == 16  # SHA256 hash truncated to 16 chars


class TestEmbeddingCache:
    """Test EmbeddingCache class."""

    def test_cache_initialization(self) -> None:
        """Test cache initialization."""
        cache = EmbeddingCache(max_size=100)

        assert cache.size == 0
        assert cache.max_size == 100

    def test_cache_set_and_get(self) -> None:
        """Test setting and getting cached embeddings."""
        cache = EmbeddingCache()

        from warden.analyzers.semantic_search.models import EmbeddingMetadata

        embedding = [0.1] * 1536
        metadata = EmbeddingMetadata(
            model_name="test",
            dimensions=1536,
            token_count=50,
            generated_at=datetime.now(),
            provider="openai",
        )

        cache.set("chunk123", embedding, metadata)

        result = cache.get("chunk123")
        assert result is not None
        assert result[0] == embedding
        assert result[1] == metadata

    def test_cache_miss(self) -> None:
        """Test cache miss returns None."""
        cache = EmbeddingCache()

        result = cache.get("nonexistent")
        assert result is None

    def test_cache_eviction(self) -> None:
        """Test cache evicts oldest entry when full."""
        cache = EmbeddingCache(max_size=2)

        from warden.analyzers.semantic_search.models import EmbeddingMetadata

        metadata = EmbeddingMetadata(
            model_name="test",
            dimensions=1536,
            token_count=50,
            generated_at=datetime.now(),
            provider="openai",
        )

        cache.set("chunk1", [0.1] * 1536, metadata)
        cache.set("chunk2", [0.2] * 1536, metadata)
        cache.set("chunk3", [0.3] * 1536, metadata)  # Should evict chunk1

        assert cache.get("chunk1") is None  # Evicted
        assert cache.get("chunk2") is not None
        assert cache.get("chunk3") is not None
        assert cache.size == 2

    def test_cache_clear(self) -> None:
        """Test clearing cache."""
        cache = EmbeddingCache()

        from warden.analyzers.semantic_search.models import EmbeddingMetadata

        metadata = EmbeddingMetadata(
            model_name="test",
            dimensions=1536,
            token_count=50,
            generated_at=datetime.now(),
            provider="openai",
        )

        cache.set("chunk1", [0.1] * 1536, metadata)
        cache.set("chunk2", [0.2] * 1536, metadata)

        assert cache.size == 2

        cache.clear()

        assert cache.size == 0
        assert cache.get("chunk1") is None
