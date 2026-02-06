"""
Semantic Search Service - Real chromadb integration (ID 5).
Replaces fake/mocked implementation with actual vector search.
"""

import asyncio
from typing import List, Optional, Dict, Any

import chromadb
from chromadb.config import Settings
import structlog

from .models import CodeChunk, SearchQuery, SearchResponse

logger = structlog.get_logger()


class SemanticSearchService:
    """Real semantic search using chromadb for vector similarity."""

    def __init__(self, config: Dict[str, Any]):
        """Initialize chromadb client."""
        self.config = config
        self.project_root = config.get("project_root", ".")
        self.client = chromadb.Client(Settings(
            chroma_db_impl="duckdb",
            persist_directory=f"{self.project_root}/.warden/chroma",
            allow_reset=True,
        ))
        self.collection = None
        logger.info("semantic_search_initialized", project_root=self.project_root)

    async def initialize(self) -> None:
        """Initialize collection and embeddings."""
        loop = asyncio.get_event_loop()
        self.collection = await loop.run_in_executor(
            None,
            self.client.get_or_create_collection,
            "code_chunks"
        )
        logger.info("chromadb_collection_ready")

    async def index_code(self, chunks: List[CodeChunk]) -> None:
        """Index code chunks into chromadb."""
        if not self.collection:
            await self.initialize()

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            self._batch_add_chunks,
            chunks
        )
        logger.info("code_indexed", chunk_count=len(chunks))

    def _batch_add_chunks(self, chunks: List[CodeChunk]) -> None:
        """Add chunks to chromadb collection."""
        documents = [c.content for c in chunks]
        metadatas = [
            {
                "file_path": c.relative_path,
                "language": c.language,
                "start_line": str(c.start_line),
                "end_line": str(c.end_line),
            }
            for c in chunks
        ]
        ids = [c.id for c in chunks]

        self.collection.add(
            documents=documents,
            metadatas=metadatas,
            ids=ids
        )

    async def search(self, query: SearchQuery) -> SearchResponse:
        """Execute semantic search query."""
        if not self.collection:
            await self.initialize()

        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(
            None,
            self._chromadb_search,
            query
        )
        return results

    def _chromadb_search(self, query: SearchQuery) -> SearchResponse:
        """Execute search in chromadb."""
        try:
            results = self.collection.query(
                query_texts=[query.query_text],
                n_results=query.limit,
                where_document={"$contains": query.query_text} if query.query_text else None
            )

            chunks = []
            for i, doc_id in enumerate(results.get("ids", [[]])[0]):
                chunks.append({
                    "chunk_id": doc_id,
                    "content": results["documents"][0][i] if results["documents"] else "",
                    "score": results["distances"][0][i] if results["distances"] else 0.0,
                    "metadata": results["metadatas"][0][i] if results["metadatas"] else {}
                })

            return SearchResponse(
                query=query.query_text,
                results=chunks,
                total=len(chunks)
            )
        except Exception as e:
            logger.error("search_failed", error=str(e))
            return SearchResponse(query=query.query_text, results=[], total=0)

    async def close(self) -> None:
        """Close chromadb connection."""
        if self.collection:
            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self.client.delete_collection, "code_chunks")
            except Exception as e:
                logger.warning("close_failed", error=str(e))
