
from __future__ import annotations
import ast
from pathlib import Path
from typing import List, Optional
import structlog
from warden.semantic_search.models import ChunkType, CodeChunk
from warden.semantic_search.embeddings import EmbeddingGenerator

logger = structlog.get_logger()

class CodeChunker:
    """
    Split code files into semantic chunks for indexing.

    Extracts functions, classes, and code blocks.
    """

    def __init__(self, project_root: Optional[Path] = None, max_chunk_size: int = 500):
        """
        Initialize code chunker.

        Args:
            project_root: Root directory of the project for relative paths
            max_chunk_size: Maximum lines per chunk
        """
        self.project_root = project_root
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

        # Calculate proper relative path
        rel_path = file_path
        if self.project_root:
            try:
                rel_path = str(Path(file_path).relative_to(self.project_root))
            except ValueError:
                rel_path = str(Path(file_path).name)
        else:
            rel_path = str(Path(file_path).name)

        chunk_id = EmbeddingGenerator.generate_chunk_id(
            CodeChunk(
                id="",
                file_path=file_path,
                relative_path=rel_path,
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
            relative_path=rel_path,
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

        # Calculate proper relative path
        rel_path = file_path
        if self.project_root:
            try:
                rel_path = str(Path(file_path).relative_to(self.project_root))
            except ValueError:
                rel_path = str(Path(file_path).name)
        else:
            rel_path = str(Path(file_path).name)

        chunk_id = EmbeddingGenerator.generate_chunk_id(
            CodeChunk(
                id="",
                file_path=file_path,
                relative_path=rel_path,
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
            relative_path=rel_path,
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
        # Calculate proper relative path
        rel_path = file_path
        if self.project_root:
            try:
                rel_path = str(Path(file_path).relative_to(self.project_root))
            except ValueError:
                rel_path = str(Path(file_path).name)
        else:
            rel_path = str(Path(file_path).name)

        chunk_id = EmbeddingGenerator.generate_chunk_id(
            CodeChunk(
                id="",
                file_path=file_path,
                relative_path=rel_path,
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
            relative_path=rel_path,
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
