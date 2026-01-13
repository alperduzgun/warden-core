"""
Embedding generation for semantic search.

Supports OpenAI and Azure OpenAI embedding models.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import List, Optional

import structlog
import tenacity
from openai import AsyncAzureOpenAI, AsyncOpenAI, RateLimitError

try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    SentenceTransformer = None

from warden.semantic_search.models import CodeChunk, EmbeddingMetadata

logger = structlog.get_logger()


class EmbeddingGenerator:
    """
    Generate embeddings for code chunks using OpenAI/Azure OpenAI.

    Supports multiple embedding models and providers.
    """
    
    provider: str
    model_name: str
    dimensions: int
    device: str
    client: Any
    azure_deployment: Optional[str] = None

    def __init__(
        self,
        provider: str = "openai",
        model_name: str = "text-embedding-3-small",
        api_key: Optional[str] = None,
        azure_endpoint: Optional[str] = None,
        azure_deployment: Optional[str] = None,
        dimensions: Optional[int] = None,
        trust_remote_code: bool = True,
        device: str = "cpu",
    ):
        """
        Initialize embedding generator.

        Args:
            provider: Provider name (openai or azure_openai)
            model_name: Embedding model name
            api_key: OpenAI API key
            azure_endpoint: Azure OpenAI endpoint (for azure_openai provider)
            azure_deployment: Azure deployment name (for azure_openai provider)
            dimensions: Embedding dimensions (optional, model-dependent)
            device: Device to use for local models (default: "cpu" for stability)

        Raises:
            ValueError: If provider is invalid or required params missing
        """
        self.provider = provider
        self.model_name = model_name
        self.dimensions = dimensions or self._get_default_dimensions(model_name)
        self.device = device

        if provider == "openai":
            if not api_key:
                raise ValueError("api_key required for OpenAI provider")
            self.client = AsyncOpenAI(api_key=api_key)

        elif provider == "azure_openai":
            if not api_key or not azure_endpoint or not azure_deployment:
                raise ValueError(
                    "api_key, azure_endpoint, and azure_deployment required for Azure OpenAI"
                )
            self.client = AsyncAzureOpenAI(
                api_key=api_key,
                azure_endpoint=azure_endpoint,
                api_version="2024-02-01",
            )
            self.azure_deployment = azure_deployment

        elif provider == "local":
            if not SentenceTransformer:
                raise ValueError(
                    "sentence-transformers not installed. Please install it with 'pip install sentence-transformers'"
                )
            
            # Initialize local model
            # For Jina embeddings v2, trust_remote_code=True is required
            # Force CPU by default to avoid UI freezes on Mac (MPS issues)
            self.client = SentenceTransformer(
                model_name, 
                trust_remote_code=trust_remote_code,
                device=device
            )
            logger.info("local_embedding_model_loaded", model=model_name, device=device)

        else:
            raise ValueError(f"Unsupported provider: {provider}")

        logger.info(
            "embedding_generator_initialized",
            provider=provider,
            model=model_name,
            dimensions=self.dimensions,
        )

    def _get_default_dimensions(self, model_name: str) -> int:
        """Get default embedding dimensions for model."""
        dimension_map = {
            "text-embedding-3-small": 1536,
            "text-embedding-3-large": 3072,
            "text-embedding-ada-002": 1536,
            "jinaai/jina-embeddings-v2-base-code": 768,
        }
        return dimension_map.get(model_name, 1536)

    @tenacity.retry(
        retry=tenacity.retry_if_exception_type(RateLimitError),
        wait=tenacity.wait_exponential(multiplier=2, min=4, max=60),
        stop=tenacity.stop_after_attempt(5),
        before_sleep=tenacity.before_sleep_log(logger, "info"),
    )
    async def generate_embedding(
        self, text: str, metadata: Optional[dict] = None
    ) -> tuple[List[float], EmbeddingMetadata]:
        """
        Generate embedding vector for text.

        Args:
            text: Input text to embed
            metadata: Optional metadata to include

        Returns:
            Tuple of (embedding_vector, metadata)

        Raises:
            Exception: If embedding generation fails
        """
        try:
            # Generate embedding
            kwargs: dict[str, Any] = {
                "input": text,
            }

            if self.provider == "azure_openai":
                kwargs["model"] = self.azure_deployment
                if self.dimensions and self.dimensions != 1536:
                     kwargs["dimensions"] = self.dimensions
                
                response = await self.client.embeddings.create(**kwargs)
                embedding_vector = response.data[0].embedding
                token_count = response.usage.total_tokens

            elif self.provider == "openai":
                kwargs["model"] = self.model_name
                if self.dimensions and self.dimensions != 1536:
                     kwargs["dimensions"] = self.dimensions

                response = await self.client.embeddings.create(**kwargs)
                embedding_vector = response.data[0].embedding
                token_count = response.usage.total_tokens
            elif self.provider == "local":
                # SentenceTransformer encode is synchronous/blocking. Offload to thread.
                import asyncio
                loop = asyncio.get_running_loop()
                embedding_vector = await loop.run_in_executor(
                    None, 
                    lambda: self.client.encode(text, device=self.device).tolist()
                )
                token_count = len(text.split()) # Rough estimate
            else:
                raise ValueError(f"Invalid provider: {self.provider}")

            # Create metadata
            embedding_metadata = EmbeddingMetadata(
                model_name=self.model_name,
                dimensions=len(embedding_vector),
                token_count=token_count,
                generated_at=datetime.now(),
                provider=self.provider,
                metadata=metadata or {},
            )

            logger.debug(
                "embedding_generated",
                text_length=len(text),
                tokens=token_count,
                dimensions=len(embedding_vector),
            )

            return embedding_vector, embedding_metadata

        except Exception as e:
            logger.error(
                "embedding_generation_failed",
                error=str(e),
                error_type=type(e).__name__,
                text_length=len(text),
            )
            raise

    async def generate_chunk_embedding(
        self, chunk: CodeChunk
    ) -> tuple[List[float], EmbeddingMetadata]:
        """
        Generate embedding for a code chunk.

        Args:
            chunk: Code chunk to embed

        Returns:
            Tuple of (embedding_vector, metadata)
        """
        # Prepare text for embedding (code + metadata)
        embedding_text = self._prepare_chunk_text(chunk)

        # Add chunk metadata
        metadata = {
            "chunk_id": chunk.id,
            "file_path": chunk.relative_path,
            "language": chunk.language,
            "chunk_type": chunk.chunk_type.value,
            "line_range": f"{chunk.start_line}-{chunk.end_line}",
        }

        return await self.generate_embedding(embedding_text, metadata)

    def _prepare_chunk_text(self, chunk: CodeChunk) -> str:
        """
        Prepare chunk content for embedding.

        Adds context to improve semantic search quality.

        Args:
            chunk: Code chunk

        Returns:
            Formatted text for embedding
        """
        # Include file context and metadata for better search
        context_parts = [
            f"File: {chunk.relative_path}",
            f"Language: {chunk.language}",
            f"Type: {chunk.chunk_type.value}",
            f"Lines: {chunk.start_line}-{chunk.end_line}",
            "",
            "Code:",
            chunk.content,
        ]

        return "\n".join(context_parts)

    async def generate_batch_embeddings(
        self, chunks: List[CodeChunk], batch_size: int = 100, max_concurrency: int = 4
    ) -> List[tuple[CodeChunk, List[float], EmbeddingMetadata]]:
        """
        Generate embeddings for multiple chunks in parallel batches.

        Args:
            chunks: List of code chunks
            batch_size: Number of chunks per batch
            max_concurrency: Maximum number of concurrent API calls

        Returns:
            List of (chunk, embedding_vector, metadata) tuples
        """
        import asyncio
        semaphore = asyncio.Semaphore(max_concurrency)
        results = []

        async def _embed_with_semaphore(chunk: CodeChunk):
            async with semaphore:
                try:
                    embedding, metadata = await self.generate_chunk_embedding(chunk)
                    return (chunk, embedding, metadata)
                except Exception as e:
                    logger.error(
                        "chunk_embedding_failed",
                        chunk_id=chunk.id,
                        error=str(e),
                    )
                    return None

        # Process in batches to manage memory and logging
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]

            logger.info(
                "processing_embedding_batch",
                batch_number=i // batch_size + 1,
                batch_size=len(batch),
                total_chunks=len(chunks),
                concurrency=max_concurrency
            )

            # Parallelize within batch
            batch_results = await asyncio.gather(
                *[_embed_with_semaphore(chunk) for chunk in batch]
            )
            
            # Filter failed ones
            results.extend([r for r in batch_results if r is not None])

        logger.info(
            "batch_embedding_completed",
            total_chunks=len(chunks),
            successful=len(results),
            failed=len(chunks) - len(results),
        )

        return results

    @staticmethod
    def generate_chunk_id(chunk: CodeChunk) -> str:
        """
        Generate unique ID for code chunk.

        Uses hash of file path + line range + content.

        Args:
            chunk: Code chunk

        Returns:
            Unique chunk ID
        """
        content = f"{chunk.file_path}:{chunk.start_line}-{chunk.end_line}:{chunk.content}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]


class EmbeddingCache:
    """
    Simple in-memory cache for embeddings.

    Reduces redundant API calls for frequently accessed chunks.
    """

    def __init__(self, max_size: int = 1000):
        """
        Initialize embedding cache.

        Args:
            max_size: Maximum number of cached embeddings
        """
        self.cache: dict[str, tuple[List[float], EmbeddingMetadata]] = {}
        self.max_size = max_size
        logger.info("embedding_cache_initialized", max_size=max_size)

    def get(self, chunk_id: str) -> Optional[tuple[List[float], EmbeddingMetadata]]:
        """
        Get cached embedding.

        Args:
            chunk_id: Chunk ID

        Returns:
            Cached embedding and metadata, or None if not found
        """
        result = self.cache.get(chunk_id)
        if result:
            logger.debug("embedding_cache_hit", chunk_id=chunk_id)
        return result

    def set(self, chunk_id: str, embedding: List[float], metadata: EmbeddingMetadata) -> None:
        """
        Cache embedding.

        Args:
            chunk_id: Chunk ID
            embedding: Embedding vector
            metadata: Embedding metadata
        """
        # Simple LRU eviction if cache is full
        if len(self.cache) >= self.max_size:
            # Remove oldest entry (first item)
            oldest_key = next(iter(self.cache))
            del self.cache[oldest_key]
            logger.debug("embedding_cache_eviction", evicted_key=oldest_key)

        self.cache[chunk_id] = (embedding, metadata)
        logger.debug("embedding_cached", chunk_id=chunk_id)

    def clear(self) -> None:
        """Clear all cached embeddings."""
        self.cache.clear()
        logger.info("embedding_cache_cleared")

    @property
    def size(self) -> int:
        """Get current cache size."""
        return len(self.cache)
