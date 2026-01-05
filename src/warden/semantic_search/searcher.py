"""
Semantic code searcher.

Performs vector similarity search on indexed code using ChromaDB.
"""

from __future__ import annotations

import time
from typing import List, Optional, Dict, Any

import structlog
try:
    import chromadb
except ImportError:
    chromadb = None

from warden.semantic_search.embeddings import EmbeddingGenerator
from warden.semantic_search.models import (
    ChunkType,
    CodeChunk,
    SearchQuery,
    SearchResponse,
    SearchResult,
)

logger = structlog.get_logger()


class SemanticSearcher:
    """
    Semantic code search using ChromaDB vector database.

    Provides similarity-based code search.
    """

    def __init__(
        self,
        chroma_path: str,
        collection_name: str,
        embedding_generator: EmbeddingGenerator,
    ):
        """
        Initialize semantic searcher.

        Args:
            chroma_path: Path to ChromaDB persistent storage
            collection_name: ChromaDB collection name
            embedding_generator: Embedding generator instance
        """
        if not chromadb:
            raise ImportError("chromadb is not installed. Please run 'pip install chromadb'")
            
        self.chroma_path = chroma_path
        self.collection_name = collection_name
        self.embedding_generator = embedding_generator

        # Initialize ChromaDB persistent client
        self.client = chromadb.PersistentClient(path=chroma_path)
        self.collection = None

        logger.info(
            "semantic_searcher_initialized",
            chroma_path=chroma_path,
            collection=collection_name,
        )

    def _ensure_collection(self):
        """Ensure collection is shared/loaded."""
        if not self.collection:
            try:
                self.collection = self.client.get_collection(name=self.collection_name)
            except Exception as e:
                logger.error("collection_not_found", collection=self.collection_name, error=str(e))
                raise

    async def search(self, query: SearchQuery) -> SearchResponse:
        """
        Perform semantic search for code.

        Args:
            query: Search query with filters

        Returns:
            Search response with results
        """
        start_time = time.perf_counter()
        self._ensure_collection()

        try:
            # Generate query embedding
            query_embedding, _ = await self.embedding_generator.generate_embedding(
                query.query_text
            )

            # Build ChromaDB filter (where clause)
            where_filter = self._build_where_filter(query)

            # Search ChromaDB
            logger.info(
                "executing_semantic_search",
                query=query.query_text[:100],
                limit=query.limit,
                min_score=query.min_score,
            )

            # ChromaDB query
            search_results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=query.limit,
                where=where_filter,
                include=["documents", "metadatas", "distances"]
            )

            # Convert to SearchResult objects
            results = self._convert_results(search_results, query.min_score)

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
        Build ChromaDB where filter from search query.

        Args:
            query: Search query

        Returns:
            ChromaDB where dict or None
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
        Convert ChromaDB raw query results to SearchResult objects.

        Args:
            raw_results: ChromaDB search results
            min_score: Minimum score threshold

        Returns:
            List of search results
        """
        results = []
        
        # ChromaDB results are lists of lists because of batch support
        if not raw_results["ids"] or not raw_results["ids"][0]:
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
                # So score = 1 - distance
                score = 1.0 - distances[i]
                
                if score < min_score:
                    continue

                # Extract original attributes from attr_ prefix
                attrs = {}
                for k, v in metadata.items():
                    if k.startswith("attr_"):
                        attrs[k[5:]] = v

                # Reconstruct CodeChunk
                chunk = CodeChunk(
                    id=metadata["chunk_id"],
                    file_path=metadata["file_path"],
                    relative_path=metadata["relative_path"],
                    chunk_type=ChunkType(metadata["chunk_type"]),
                    content=documents[i],
                    start_line=metadata["start_line"],
                    end_line=metadata["end_line"],
                    language=metadata["language"],
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
