"""
Code indexer for semantic search.

Indexes code chunks into ChromaDB vector database.
"""

from __future__ import annotations

import ast
import hashlib
from datetime import datetime
from pathlib import Path
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
    Index code chunks into ChromaDB vector database.

    Manages ChromaDB collection and index operations.
    """

    def __init__(
        self,
        chroma_path: str,
        collection_name: str,
        embedding_generator: EmbeddingGenerator,
        chunk_size: int = 500,
    ):
        """
        Initialize code indexer.

        Args:
            chroma_path: Path to ChromaDB persistent storage
            collection_name: ChromaDB collection name
            embedding_generator: Embedding generator instance
            chunk_size: Maximum chunk size in lines
        """
        if not chromadb:
            raise ImportError("chromadb is not installed. Please run 'pip install chromadb'")

        self.chroma_path = chroma_path
        self.collection_name = collection_name
        self.embedding_generator = embedding_generator
        self.chunker = CodeChunker(max_chunk_size=chunk_size)

        self.client = chromadb.PersistentClient(path=chroma_path)
        self.collection = None

        logger.info(
            "code_indexer_initialized",
            chroma_path=chroma_path,
            collection=collection_name,
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

    def _get_existing_file_hash(self, file_path: str) -> Optional[str]:
        """Get existing file hash from ChromaDB metadata."""
        if not self.collection:
            self.ensure_collection()
            
        try:
            # Query by file_path in metadata
            results = self.collection.get(
                where={"file_path": file_path},
                include=["metadatas"],
                limit=1
            )
            
            if results and results["metadatas"]:
                return results["metadatas"][0].get("file_hash")
        except Exception as e:
            logger.debug("existing_hash_lookup_failed", file_path=file_path, error=str(e))
            
        return None

    def ensure_collection(self) -> None:
        """
        Ensure ChromaDB collection exists.

        Creates collection if it doesn't exist.
        """
        try:
            self.collection = self.client.get_or_create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": "cosine"}
            )
            logger.debug(
                "chromadb_collection_ready",
                collection=self.collection_name,
            )
        except Exception as e:
            logger.error(
                "collection_creation_failed",
                collection=self.collection_name,
                error=str(e),
            )
            raise

    async def index_file(self, file_path: str, language: str, force: bool = False) -> int:
        """
        Index a single file with change detection.

        Args:
            file_path: Path to file
            language: Programming language
            force: Force re-indexing even if hash matches

        Returns:
            Number of chunks indexed
        """
        self.ensure_collection()
        
        # 1. Calculate current hash
        current_hash = self._calculate_file_hash(file_path)
        
        # 2. Check for changes
        if not force and current_hash:
            existing_hash = self._get_existing_file_hash(file_path)
            if existing_hash == current_hash:
                logger.debug(
                    "file_unchanged_skipping_index",
                    file_path=file_path,
                    hash=current_hash
                )
                return 0

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
        ids = []
        embeddings = []
        metadatas = []
        documents = []

        for chunk in chunks:
            try:
                # Generate embedding
                embedding, _ = await self.embedding_generator.generate_chunk_embedding(
                    chunk
                )

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

            except Exception as e:
                logger.error(
                    "chunk_embedding_failed",
                    chunk_id=chunk.id,
                    error=str(e),
                )

        if ids:
            try:
                self.collection.upsert(
                    ids=ids,
                    embeddings=embeddings,
                    metadatas=metadatas,
                    documents=documents
                )
            except Exception as e:
                logger.error("collection_upsert_failed", error=str(e))
                return 0

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
        self.ensure_collection()

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

    def delete_collection(self) -> None:
        """Delete the ChromaDB collection."""
        try:
            self.client.delete_collection(name=self.collection_name)
            logger.info("collection_deleted", collection=self.collection_name)
        except Exception as e:
            logger.error(
                "collection_deletion_failed",
                collection=self.collection_name,
                error=str(e),
            )
            raise

    def get_stats(self) -> IndexStats:
        """
        Get current index statistics.

        Returns:
            Index statistics
        """
        try:
            if not self.collection:
                self.ensure_collection()
            
            count = self.collection.count()

            return IndexStats(
                total_chunks=count,
                last_indexed_at=datetime.now(),
            )

        except Exception as e:
            logger.error(
                "stats_retrieval_failed",
                collection=self.collection_name,
                error=str(e),
            )
            return IndexStats()
