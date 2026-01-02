"""
Code indexer for semantic search.

Indexes code chunks into Qdrant vector database.
"""

from __future__ import annotations

import ast
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import structlog
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from warden.analysis.application.semantic_search.embeddings import EmbeddingGenerator
from warden.analysis.application.semantic_search.models import (
    ChunkType,
    CodeChunk,
    IndexStats,
)

logger = structlog.get_logger()


class CodeChunker:
    """
    Split code files into semantic chunks for indexing.

    Extracts functions, classes, and code blocks.
    """

    def __init__(self, max_chunk_size: int = 500):
        """
        Initialize code chunker.

        Args:
            max_chunk_size: Maximum lines per chunk
        """
        self.max_chunk_size = max_chunk_size

    def chunk_python_file(self, file_path: str, content: str) -> List[CodeChunk]:
        """
        Chunk Python file into semantic units.

        Extracts functions and classes as separate chunks.

        Args:
            file_path: Path to Python file
            content: File content

        Returns:
            List of code chunks
        """
        chunks = []

        try:
            tree = ast.parse(content)

            for node in ast.walk(tree):
                # Extract functions
                if isinstance(node, ast.FunctionDef):
                    chunk = self._extract_function_chunk(node, file_path, content)
                    if chunk:
                        chunks.append(chunk)

                # Extract classes
                elif isinstance(node, ast.ClassDef):
                    chunk = self._extract_class_chunk(node, file_path, content)
                    if chunk:
                        chunks.append(chunk)

        except SyntaxError as e:
            logger.warning(
                "python_ast_parse_failed",
                file_path=file_path,
                error=str(e),
            )
            # Fallback to module-level chunk
            chunks.append(
                self._create_module_chunk(file_path, content, language="python")
            )

        # If no chunks extracted, add whole file
        if not chunks:
            chunks.append(
                self._create_module_chunk(file_path, content, language="python")
            )

        return chunks

    def _extract_function_chunk(
        self, node: ast.FunctionDef, file_path: str, content: str
    ) -> Optional[CodeChunk]:
        """Extract function as code chunk."""
        start_line = node.lineno
        end_line = node.end_lineno or start_line

        # Skip if too large
        if end_line - start_line > self.max_chunk_size:
            logger.debug(
                "function_chunk_too_large",
                function=node.name,
                lines=end_line - start_line,
            )
            return None

        # Extract function code
        lines = content.split("\n")
        function_code = "\n".join(lines[start_line - 1 : end_line])

        chunk_id = EmbeddingGenerator.generate_chunk_id(
            CodeChunk(
                id="",
                file_path=file_path,
                relative_path=str(Path(file_path).name),
                chunk_type=ChunkType.FUNCTION,
                content=function_code,
                start_line=start_line,
                end_line=end_line,
                language="python",
            )
        )

        return CodeChunk(
            id=chunk_id,
            file_path=file_path,
            relative_path=str(Path(file_path).name),
            chunk_type=ChunkType.FUNCTION,
            content=function_code,
            start_line=start_line,
            end_line=end_line,
            language="python",
            metadata={"function_name": node.name},
        )

    def _extract_class_chunk(
        self, node: ast.ClassDef, file_path: str, content: str
    ) -> Optional[CodeChunk]:
        """Extract class as code chunk."""
        start_line = node.lineno
        end_line = node.end_lineno or start_line

        # Skip if too large
        if end_line - start_line > self.max_chunk_size:
            logger.debug(
                "class_chunk_too_large",
                class_name=node.name,
                lines=end_line - start_line,
            )
            return None

        # Extract class code
        lines = content.split("\n")
        class_code = "\n".join(lines[start_line - 1 : end_line])

        chunk_id = EmbeddingGenerator.generate_chunk_id(
            CodeChunk(
                id="",
                file_path=file_path,
                relative_path=str(Path(file_path).name),
                chunk_type=ChunkType.CLASS,
                content=class_code,
                start_line=start_line,
                end_line=end_line,
                language="python",
            )
        )

        return CodeChunk(
            id=chunk_id,
            file_path=file_path,
            relative_path=str(Path(file_path).name),
            chunk_type=ChunkType.CLASS,
            content=class_code,
            start_line=start_line,
            end_line=end_line,
            language="python",
            metadata={"class_name": node.name},
        )

    def _create_module_chunk(
        self, file_path: str, content: str, language: str
    ) -> CodeChunk:
        """Create module-level chunk (entire file)."""
        lines = content.split("\n")
        chunk_id = EmbeddingGenerator.generate_chunk_id(
            CodeChunk(
                id="",
                file_path=file_path,
                relative_path=str(Path(file_path).name),
                chunk_type=ChunkType.MODULE,
                content=content,
                start_line=1,
                end_line=len(lines),
                language=language,
            )
        )

        return CodeChunk(
            id=chunk_id,
            file_path=file_path,
            relative_path=str(Path(file_path).name),
            chunk_type=ChunkType.MODULE,
            content=content,
            start_line=1,
            end_line=len(lines),
            language=language,
        )

    def chunk_file(self, file_path: str, language: str) -> List[CodeChunk]:
        """
        Chunk any file based on language.

        Args:
            file_path: Path to file
            language: Programming language

        Returns:
            List of code chunks
        """
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            logger.error("file_read_failed", file_path=file_path, error=str(e))
            return []

        # Language-specific chunking
        if language == "python":
            return self.chunk_python_file(file_path, content)
        else:
            # Fallback: module-level chunk
            return [self._create_module_chunk(file_path, content, language)]


class CodeIndexer:
    """
    Index code chunks into Qdrant vector database.

    Manages Qdrant collection and index operations.
    """

    def __init__(
        self,
        qdrant_url: str,
        qdrant_api_key: Optional[str],
        collection_name: str,
        embedding_generator: EmbeddingGenerator,
        chunk_size: int = 500,
    ):
        """
        Initialize code indexer.

        Args:
            qdrant_url: Qdrant server URL
            qdrant_api_key: Qdrant API key (optional for local)
            collection_name: Qdrant collection name
            embedding_generator: Embedding generator instance
            chunk_size: Maximum chunk size in lines
        """
        self.qdrant_url = qdrant_url
        self.collection_name = collection_name
        self.embedding_generator = embedding_generator
        self.chunker = CodeChunker(max_chunk_size=chunk_size)

        # Initialize Qdrant client
        self.client = AsyncQdrantClient(
            url=qdrant_url,
            api_key=qdrant_api_key,
        )

        logger.info(
            "code_indexer_initialized",
            qdrant_url=qdrant_url,
            collection=collection_name,
            chunk_size=chunk_size,
        )

    async def ensure_collection(self) -> None:
        """
        Ensure Qdrant collection exists.

        Creates collection if it doesn't exist.
        """
        try:
            collections = await self.client.get_collections()
            collection_names = [c.name for c in collections.collections]

            if self.collection_name not in collection_names:
                logger.info(
                    "creating_qdrant_collection",
                    collection=self.collection_name,
                    dimensions=self.embedding_generator.dimensions,
                )

                await self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(
                        size=self.embedding_generator.dimensions,
                        distance=Distance.COSINE,
                    ),
                )

                logger.info(
                    "qdrant_collection_created",
                    collection=self.collection_name,
                )
            else:
                logger.debug(
                    "qdrant_collection_exists",
                    collection=self.collection_name,
                )

        except Exception as e:
            logger.error(
                "collection_creation_failed",
                collection=self.collection_name,
                error=str(e),
            )
            raise

    async def index_file(self, file_path: str, language: str) -> int:
        """
        Index a single file.

        Args:
            file_path: Path to file
            language: Programming language

        Returns:
            Number of chunks indexed
        """
        # Chunk file
        chunks = self.chunker.chunk_file(file_path, language)

        if not chunks:
            logger.warning("no_chunks_extracted", file_path=file_path)
            return 0

        logger.info(
            "indexing_file",
            file_path=file_path,
            chunks=len(chunks),
            language=language,
        )

        # Generate embeddings and index
        indexed_count = 0
        for chunk in chunks:
            try:
                # Generate embedding
                embedding, metadata = await self.embedding_generator.generate_chunk_embedding(
                    chunk
                )

                # Prepare payload
                payload = {
                    "chunk_id": chunk.id,
                    "file_path": chunk.file_path,
                    "relative_path": chunk.relative_path,
                    "chunk_type": chunk.chunk_type.value,
                    "content": chunk.content,
                    "start_line": chunk.start_line,
                    "end_line": chunk.end_line,
                    "language": chunk.language,
                    "metadata": chunk.metadata,
                    "indexed_at": datetime.now().isoformat(),
                }

                # Upsert to Qdrant
                point = PointStruct(
                    id=hash(chunk.id) % (2**63),  # Convert to integer ID
                    vector=embedding,
                    payload=payload,
                )

                await self.client.upsert(
                    collection_name=self.collection_name,
                    points=[point],
                )

                indexed_count += 1

            except Exception as e:
                logger.error(
                    "chunk_indexing_failed",
                    chunk_id=chunk.id,
                    error=str(e),
                )

        logger.info(
            "file_indexed",
            file_path=file_path,
            chunks_indexed=indexed_count,
            chunks_total=len(chunks),
        )

        return indexed_count

    async def index_files(
        self, file_paths: List[str], languages: dict[str, str]
    ) -> IndexStats:
        """
        Index multiple files.

        Args:
            file_paths: List of file paths
            languages: Mapping of file_path -> language

        Returns:
            Index statistics
        """
        await self.ensure_collection()

        total_chunks = 0
        chunks_by_language: dict[str, int] = {}
        chunks_by_type: dict[str, int] = {}
        files_indexed = 0

        for file_path in file_paths:
            language = languages.get(file_path, "unknown")

            try:
                chunk_count = await self.index_file(file_path, language)

                if chunk_count > 0:
                    total_chunks += chunk_count
                    files_indexed += 1

                    # Update stats
                    chunks_by_language[language] = (
                        chunks_by_language.get(language, 0) + chunk_count
                    )

            except Exception as e:
                logger.error(
                    "file_indexing_failed",
                    file_path=file_path,
                    error=str(e),
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

    async def delete_collection(self) -> None:
        """Delete the Qdrant collection."""
        try:
            await self.client.delete_collection(collection_name=self.collection_name)
            logger.info("collection_deleted", collection=self.collection_name)
        except Exception as e:
            logger.error(
                "collection_deletion_failed",
                collection=self.collection_name,
                error=str(e),
            )
            raise

    async def get_stats(self) -> IndexStats:
        """
        Get current index statistics.

        Returns:
            Index statistics
        """
        try:
            collection_info = await self.client.get_collection(self.collection_name)

            return IndexStats(
                total_chunks=collection_info.points_count or 0,
                last_indexed_at=datetime.now(),
            )

        except Exception as e:
            logger.error(
                "stats_retrieval_failed",
                collection=self.collection_name,
                error=str(e),
            )
            return IndexStats()
