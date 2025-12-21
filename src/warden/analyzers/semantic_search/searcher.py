"""
Semantic code searcher.

Performs vector similarity search on indexed code.
"""

from __future__ import annotations

import time
from typing import List, Optional

import structlog
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue, ScoredPoint

from warden.analyzers.semantic_search.embeddings import EmbeddingGenerator
from warden.analyzers.semantic_search.models import (
    ChunkType,
    CodeChunk,
    SearchQuery,
    SearchResponse,
    SearchResult,
)

logger = structlog.get_logger()


class SemanticSearcher:
    """
    Semantic code search using Qdrant vector database.

    Provides similarity-based code search.
    """

    def __init__(
        self,
        qdrant_url: str,
        qdrant_api_key: Optional[str],
        collection_name: str,
        embedding_generator: EmbeddingGenerator,
    ):
        """
        Initialize semantic searcher.

        Args:
            qdrant_url: Qdrant server URL
            qdrant_api_key: Qdrant API key (optional for local)
            collection_name: Qdrant collection name
            embedding_generator: Embedding generator instance
        """
        self.qdrant_url = qdrant_url
        self.collection_name = collection_name
        self.embedding_generator = embedding_generator

        # Initialize Qdrant client
        self.client = AsyncQdrantClient(
            url=qdrant_url,
            api_key=qdrant_api_key,
        )

        logger.info(
            "semantic_searcher_initialized",
            qdrant_url=qdrant_url,
            collection=collection_name,
        )

    async def search(self, query: SearchQuery) -> SearchResponse:
        """
        Perform semantic search for code.

        Args:
            query: Search query with filters

        Returns:
            Search response with results
        """
        start_time = time.perf_counter()

        try:
            # Generate query embedding
            query_embedding, _ = await self.embedding_generator.generate_embedding(
                query.query_text
            )

            # Build Qdrant filter
            qdrant_filter = self._build_filter(query)

            # Search Qdrant
            logger.info(
                "executing_semantic_search",
                query=query.query_text[:100],
                limit=query.limit,
                min_score=query.min_score,
            )

            search_results = await self.client.search(
                collection_name=self.collection_name,
                query_vector=query_embedding,
                limit=query.limit,
                score_threshold=query.min_score,
                query_filter=qdrant_filter,
            )

            # Convert to SearchResult objects
            results = self._convert_results(search_results)

            duration = time.perf_counter() - start_time

            logger.info(
                "search_completed",
                results=len(results),
                duration_seconds=duration,
            )

            return SearchResponse(
                query=query,
                results=results,
                total_results=len(results),
                search_duration_seconds=duration,
            )

        except Exception as e:
            logger.error(
                "search_failed",
                query=query.query_text[:100],
                error=str(e),
                error_type=type(e).__name__,
            )
            raise

    def _build_filter(self, query: SearchQuery) -> Optional[Filter]:
        """
        Build Qdrant filter from search query.

        Args:
            query: Search query

        Returns:
            Qdrant filter or None
        """
        conditions = []

        # Language filters
        if query.language_filters:
            for language in query.language_filters:
                conditions.append(
                    FieldCondition(
                        key="language",
                        match=MatchValue(value=language),
                    )
                )

        # Chunk type filters
        if query.chunk_type_filters:
            for chunk_type in query.chunk_type_filters:
                conditions.append(
                    FieldCondition(
                        key="chunk_type",
                        match=MatchValue(value=chunk_type.value),
                    )
                )

        # File path filters (simple contains check)
        if query.file_filters:
            # Note: Qdrant doesn't support contains, so this is exact match
            # For production, consider pre-processing or using metadata
            for file_pattern in query.file_filters:
                conditions.append(
                    FieldCondition(
                        key="relative_path",
                        match=MatchValue(value=file_pattern),
                    )
                )

        if not conditions:
            return None

        return Filter(should=conditions)  # OR logic

    def _convert_results(self, scored_points: List[ScoredPoint]) -> List[SearchResult]:
        """
        Convert Qdrant scored points to SearchResult objects.

        Args:
            scored_points: Qdrant search results

        Returns:
            List of search results
        """
        results = []

        for rank, point in enumerate(scored_points, start=1):
            try:
                payload = point.payload

                # Reconstruct CodeChunk
                chunk = CodeChunk(
                    id=payload["chunk_id"],
                    file_path=payload["file_path"],
                    relative_path=payload["relative_path"],
                    chunk_type=ChunkType(payload["chunk_type"]),
                    content=payload["content"],
                    start_line=payload["start_line"],
                    end_line=payload["end_line"],
                    language=payload["language"],
                    metadata=payload.get("metadata", {}),
                )

                # Create SearchResult
                result = SearchResult(
                    chunk=chunk,
                    score=point.score,
                    rank=rank,
                    metadata={
                        "indexed_at": payload.get("indexed_at"),
                    },
                )

                results.append(result)

            except Exception as e:
                logger.warning(
                    "result_conversion_failed",
                    point_id=point.id,
                    error=str(e),
                )

        return results

    async def search_similar_code(
        self,
        code_snippet: str,
        language: Optional[str] = None,
        limit: int = 10,
        min_score: float = 0.5,
    ) -> List[SearchResult]:
        """
        Find code similar to the given snippet.

        Args:
            code_snippet: Code to find similar matches for
            language: Filter by programming language
            limit: Maximum results
            min_score: Minimum similarity score

        Returns:
            List of similar code results
        """
        query = SearchQuery(
            query_text=code_snippet,
            limit=limit,
            min_score=min_score,
            language_filters=[language] if language else [],
        )

        response = await self.search(query)
        return response.results

    async def search_by_description(
        self,
        description: str,
        language: Optional[str] = None,
        chunk_types: Optional[List[ChunkType]] = None,
        limit: int = 10,
    ) -> List[SearchResult]:
        """
        Find code matching a natural language description.

        Args:
            description: Natural language description of desired code
            language: Filter by programming language
            chunk_types: Filter by chunk types
            limit: Maximum results

        Returns:
            List of matching code results
        """
        query = SearchQuery(
            query_text=description,
            limit=limit,
            min_score=0.5,
            language_filters=[language] if language else [],
            chunk_type_filters=chunk_types or [],
        )

        response = await self.search(query)
        return response.results

    async def find_function_implementations(
        self,
        function_description: str,
        language: Optional[str] = None,
        limit: int = 5,
    ) -> List[SearchResult]:
        """
        Find function implementations matching description.

        Args:
            function_description: Description of desired function
            language: Filter by programming language
            limit: Maximum results

        Returns:
            List of function implementations
        """
        return await self.search_by_description(
            description=function_description,
            language=language,
            chunk_types=[ChunkType.FUNCTION],
            limit=limit,
        )

    async def find_class_definitions(
        self,
        class_description: str,
        language: Optional[str] = None,
        limit: int = 5,
    ) -> List[SearchResult]:
        """
        Find class definitions matching description.

        Args:
            class_description: Description of desired class
            language: Filter by programming language
            limit: Maximum results

        Returns:
            List of class definitions
        """
        return await self.search_by_description(
            description=class_description,
            language=language,
            chunk_types=[ChunkType.CLASS],
            limit=limit,
        )
