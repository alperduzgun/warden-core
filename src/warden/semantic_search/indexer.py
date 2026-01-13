
"""
Code indexer for semantic search.

Indexes code chunks into vector database using an adapter.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import List, Optional

from pathlib import Path
import structlog

from warden.semantic_search.embeddings import EmbeddingGenerator
from warden.semantic_search.models import (
    IndexStats,
)
from warden.semantic_search.chunker import CodeChunker
from warden.semantic_search.adapters import VectorStoreAdapter

logger = structlog.get_logger()


class CodeIndexer:
    """
    Index code chunks into a vector database.

    Uses a VectorStoreAdapter for storage operations.
    """

    adapter: VectorStoreAdapter
    embedding_generator: EmbeddingGenerator
    project_root: Optional[Path]
    chunker: CodeChunker

    def __init__(
        self,
        adapter: VectorStoreAdapter,
        embedding_generator: EmbeddingGenerator,
        project_root: Optional[Path] = None,
        chunk_size: int = 500,
    ):
        """
        Initialize code indexer.

        Args:
            adapter: Vector store adapter instance
            embedding_generator: Embedding generator instance
            project_root: Root directory of the project
            chunk_size: Maximum chunk size in lines
        """
        self.adapter = adapter
        self.embedding_generator = embedding_generator
        self.project_root = project_root
        self.chunker = CodeChunker(project_root=project_root, max_chunk_size=chunk_size)

        logger.info(
            "code_indexer_initialized",
            adapter_type=type(adapter).__name__,
            chunk_size=chunk_size,
        )

    def _calculate_file_hash(self, file_path: str) -> str:
        """Calculate SHA256 hash of a file."""
        sha256_hash = hashlib.sha256()
        try:
            with open(file_path, "rb") as f:
                for byte_block in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(byte_block)
            return sha256_hash.hexdigest()
        except Exception as e:
            logger.error("hash_calculation_failed", file_path=file_path, error=str(e))
            return ""

    async def index_file(self, file_path: str, language: str, force: bool = False) -> int:
        """
        Index a single file with change detection.
        """
        
        # 1. Calculate current hash
        current_hash = self._calculate_file_hash(file_path)
        
        # 2. Check for changes based on relative path if possible for portability
        rel_path = file_path
        if self.project_root:
            try:
                rel_path = str(Path(file_path).relative_to(self.project_root))
            except ValueError:
                pass

        if not force and current_hash:
            # Try relative path first (Portable across CI/Local)
            existing_hash = self.adapter.get_existing_file_hash(rel_path)
            # Fallback to absolute if not found (Legacy)
            if not existing_hash and rel_path != file_path:
                existing_hash = self.adapter.get_existing_file_hash(file_path)
                
            if existing_hash == current_hash:
                logger.debug(
                    "file_unchanged_skipping_index",
                    file_path=rel_path,
                    hash=current_hash
                )
                return 0

        # Chunk file
        chunks = self.chunker.chunk_file(file_path, language)

        if not chunks:
            logger.warning("no_chunks_extracted", file_path=file_path)
            return 0

        # Prepare for batch embedding
        logger.info(
            "indexing_file",
            file_path=file_path,
            chunks=len(chunks),
            language=language,
        )

        # Generate embeddings in parallel
        batch_results = await self.embedding_generator.generate_batch_embeddings(chunks)

        # Prepare for upsert
        ids = []
        embeddings = []
        metadatas = []
        documents = []
        indexed_count = 0

        for chunk, embedding, emb_metadata in batch_results:
            # Prepare metadata (ChromaDB only supports simple types in metadata)
            metadata = {
                "chunk_id": chunk.id,
                "file_path": str(chunk.file_path),
                "relative_path": str(chunk.relative_path),
                "chunk_type": chunk.chunk_type.value,
                "start_line": chunk.start_line,
                "end_line": chunk.end_line,
                "language": chunk.language,
                "file_hash": current_hash,
                "indexed_at": datetime.now().isoformat(),
            }
            
            # Flatten extra metadata if any
            if chunk.metadata:
                for k, v in chunk.metadata.items():
                    if isinstance(v, (str, int, float, bool)):
                        metadata[f"attr_{k}"] = v

            ids.append(chunk.id)
            embeddings.append(embedding)
            metadatas.append(metadata)
            documents.append(chunk.content)
            indexed_count += 1

        if ids:
            success = await self.adapter.upsert(
                ids=ids,
                embeddings=embeddings,
                metadatas=metadatas,
                documents=documents
            )
            if not success:
                logger.error("adapter_upsert_failed")
                return 0

        logger.info(
            "file_indexed",
            file_path=file_path,
            chunks_indexed=indexed_count,
            chunks_total=len(chunks),
        )

        return indexed_count

    async def index_files(
        self, file_paths: str | List[str], languages: dict[str, str], max_concurrency: int = 5
    ) -> IndexStats:
        """
        Index multiple files in parallel.
        
        Args:
            file_paths: List of absolute file paths or single path
            languages: Mapping of file path to language
            max_concurrency: Maximum number of concurrent files being processed
        """
        import asyncio
        if isinstance(file_paths, str):
            file_paths = [file_paths]

        total_chunks = 0
        chunks_by_language: dict[str, int] = {}
        chunks_by_type: dict[str, int] = {}
        files_indexed = 0
        
        semaphore = asyncio.Semaphore(max_concurrency)

        async def _index_with_semaphore(file_path: str):
            async with semaphore:
                language = languages.get(file_path, "unknown")
                try:
                    return await self.index_file(file_path, language), language
                except Exception as e:
                    logger.error(
                        "file_indexing_failed",
                        file_path=file_path,
                        error=str(e),
                    )
                    return 0, language

        # Run in parallel
        results = await asyncio.gather(*[_index_with_semaphore(fp) for fp in file_paths])

        # Aggregate results
        for chunk_count, language in results:
            if chunk_count > 0:
                total_chunks += chunk_count
                files_indexed += 1
                chunks_by_language[language] = (
                    chunks_by_language.get(language, 0) + chunk_count
                )

        logger.info(
            "batch_indexing_completed",
            total_files=len(file_paths),
            files_indexed=files_indexed,
            total_chunks=total_chunks,
        )

        return IndexStats(
            total_chunks=total_chunks,
            chunks_by_language=chunks_by_language,
            chunks_by_type=chunks_by_type,
            total_files_indexed=files_indexed,
            last_indexed_at=datetime.now(),
        )

    def delete_collection(self) -> None:
        """Delete the collection via adapter."""
        self.adapter.delete_collection()

    def get_stats(self) -> IndexStats:
        """Get current index statistics."""
        try:
            count = self.adapter.count()
            return IndexStats(
                total_chunks=count,
                last_indexed_at=datetime.now(),
            )
        except Exception as e:
            logger.error("stats_retrieval_failed", error=str(e))
            return IndexStats()
