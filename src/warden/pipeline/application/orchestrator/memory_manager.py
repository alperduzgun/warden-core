"""
Memory Manager - Prevent OOM by streaming and chunking (ID 27).
Process files in chunks instead of loading all into RAM.
"""

import asyncio
from pathlib import Path
from typing import List, AsyncIterator, Optional
import structlog

from warden.validation.domain.frame import CodeFile

logger = structlog.get_logger()

CHUNK_SIZE = 10  # Process 10 files at a time
MAX_FILE_SIZE_MB = 50  # Skip files larger than 50MB


class MemoryManager:
    """Manages memory-efficient file processing."""

    @staticmethod
    async def stream_files_chunked(
        code_files: List[CodeFile],
        chunk_size: int = CHUNK_SIZE
    ) -> AsyncIterator[List[CodeFile]]:
        """
        Stream files in chunks to prevent OOM.

        Args:
            code_files: List of files to process
            chunk_size: Number of files per chunk

        Returns:
            Async iterator yielding file chunks
        """
        for i in range(0, len(code_files), chunk_size):
            chunk = code_files[i:i + chunk_size]
            logger.info("processing_chunk", chunk_index=i // chunk_size, size=len(chunk))
            yield chunk
            # Allow garbage collection between chunks
            await asyncio.sleep(0)

    @staticmethod
    def validate_file_size(file_path: str, max_size_mb: int = MAX_FILE_SIZE_MB) -> bool:
        """Check if file is within size limits."""
        try:
            size_mb = Path(file_path).stat().st_size / (1024 * 1024)
            if size_mb > max_size_mb:
                logger.warning("file_too_large", file=file_path, size_mb=size_mb)
                return False
            return True
        except OSError:
            return False

    @staticmethod
    async def process_with_memory_limit(
        items: List,
        processor_func,
        batch_size: int = 10
    ) -> List:
        """Process items with memory constraints."""
        results = []
        for i in range(0, len(items), batch_size):
            batch = items[i:i + batch_size]
            batch_results = await processor_func(batch)
            results.extend(batch_results)
            await asyncio.sleep(0)  # Yield control
        return results

    @staticmethod
    def estimate_memory_usage(code_files: List[CodeFile]) -> int:
        """Estimate total memory needed for all files in MB."""
        total_bytes = sum(len(f.content.encode()) for f in code_files if f.content)
        return total_bytes // (1024 * 1024)
