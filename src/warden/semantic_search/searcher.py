
"""
Semantic code searcher.

Performs vector similarity search on indexed code using an adapter.
"""

from __future__ import annotations

import time
from typing import List, Optional, Dict, Any

import structlog

from warden.semantic_search.embeddings import EmbeddingGenerator
from warden.semantic_search.models import (
    ChunkType,
    CodeChunk,
    SearchQuery,
    SearchResponse,
    SearchResult,
)
from warden.semantic_search.adapters import VectorStoreAdapter

logger = structlog.get_logger()


class SemanticSearcher:
    """
    Semantic code search using a VectorStoreAdapter.

    Provides similarity-based code search.
    """

    def __init__(
        self,
        adapter: VectorStoreAdapter,
        embedding_generator: EmbeddingGenerator,
    ):
        """
        Initialize semantic searcher.

        Args:
            adapter: Vector store adapter instance
            embedding_generator: Embedding generator instance
        """
        self.adapter = adapter
        self.embedding_generator = embedding_generator

        logger.info(
            "semantic_searcher_initialized",
            adapter_type=type(adapter).__name__,
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

            # Build filter (where clause)
            where_filter = self._build_where_filter(query)

            # Search Adapter
            logger.info(
                "executing_semantic_search",
                query=query.query_text[:100],
                limit=query.limit,
                min_score=query.min_score,
            )

            # Adapter query
            raw_results = await self.adapter.query(
                query_embeddings=[query_embedding],
                n_results=query.limit,
                where=where_filter
            )

            # Convert to SearchResult objects
            results = self._convert_results(raw_results, query.min_score)

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
            # Return empty response on failure to avoid breaking pipeline
            return SearchResponse(
                query=query,
                results=[],
                total_results=0,
                search_duration_seconds=time.perf_counter() - start_time,
            )

    def _build_where_filter(self, query: SearchQuery) -> Optional[Dict[str, Any]]:
        """
        Build metadata filter from search query.

        Args:
            query: Search query

        Returns:
            Filter dict or None
        """
        filters = []

        # Language filters
        if query.language_filters:
            if len(query.language_filters) == 1:
                filters.append({"language": query.language_filters[0]})
            else:
                filters.append({"language": {"$in": query.language_filters}})

        # Chunk type filters
        if query.chunk_type_filters:
            chunk_types = [ct.value for ct in query.chunk_type_filters]
            if len(chunk_types) == 1:
                filters.append({"chunk_type": chunk_types[0]})
            else:
                filters.append({"chunk_type": {"$in": chunk_types}})

        # File path filters (exact relative path)
        if query.file_filters:
            if len(query.file_filters) == 1:
                filters.append({"relative_path": query.file_filters[0]})
            else:
                filters.append({"relative_path": {"$in": query.file_filters}})

        if not filters:
            return None

        if len(filters) == 1:
            return filters[0]

        return {"$and": filters}

    def _convert_results(self, raw_results: Dict[str, Any], min_score: float = 0.5) -> List[SearchResult]:
        """
        Convert raw query results to SearchResult objects.

        Args:
            raw_results: Adapter search results (Chroma-like dict)
            min_score: Minimum score threshold

        Returns:
            List of search results
        """
        results = []
        
        # Results are lists of lists because of batch support
        if not raw_results or not raw_results.get("ids") or not raw_results["ids"][0]:
            return []

        ids = raw_results["ids"][0]
        metadatas = raw_results["metadatas"][0]
        documents = raw_results["documents"][0]
        distances = raw_results["distances"][0]

        for i in range(len(ids)):
            try:
                metadata = metadatas[i]
                
                # ChromaDB distance is squared L2 or cosine distance.
                # For cosine similarity, it's 1 - similarity.
                # So score = 1 - distance.
                # Ensure distance is float.
                dist = float(distances[i])
                score = 1.0 - dist
                
                if score < min_score:
                    continue

                # Extract original attributes from attr_ prefix
                attrs = {}
                for k, v in metadata.items():
                    if k.startswith("attr_"):
                        attrs[k[5:]] = v

                # Reconstruct CodeChunk
                chunk = CodeChunk(
                    id=metadata.get("chunk_id", ids[i]),
                    file_path=metadata.get("file_path", ""),
                    relative_path=metadata.get("relative_path", ""),
                    chunk_type=ChunkType(metadata.get("chunk_type", ChunkType.MODULE.value)),
                    content=documents[i],
                    start_line=metadata.get("start_line", 0),
                    end_line=metadata.get("end_line", 0),
                    language=metadata.get("language", "unknown"),
                    metadata=attrs,
                )

                # Create SearchResult
                result = SearchResult(
                    chunk=chunk,
                    score=score,
                    rank=i + 1,
                    metadata={
                        "indexed_at": metadata.get("indexed_at"),
                    },
                )

                results.append(result)

            except Exception as e:
                logger.warning(
                    "result_conversion_failed",
                    index=i,
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
        """Find code similar to the given snippet."""
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
        """Find code matching a natural language description."""
        query = SearchQuery(
            query_text=description,
            limit=limit,
            min_score=0.5,
            language_filters=[language] if language else [],
            chunk_type_filters=chunk_types or [],
        )

        response = await self.search(query)
        return response.results
