"""
Async Rule Validator - Offload regex to thread pool (ID 28).
Prevents event loop starvation from expensive regex operations.
"""

import asyncio
import re
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional

import structlog

logger = structlog.get_logger()


class AsyncRuleValidator:
    """Validates rules asynchronously without blocking event loop."""

    def __init__(self, max_workers: int = 4):
        """Initialize thread pool for regex operations."""
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        logger.info("async_validator_initialized", workers=max_workers)

    async def validate_patterns_async(self, content: str, patterns: list[str]) -> list:
        """
        Validate content against patterns asynchronously.

        Args:
            content: Code content to validate
            patterns: Regex patterns to check

        Returns:
            List of matches
        """
        loop = asyncio.get_event_loop()
        matches = await loop.run_in_executor(self.executor, self._validate_patterns, content, patterns)
        return matches

    @staticmethod
    def _validate_patterns(content: str, patterns: list[str]) -> list:
        """Execute regex validation in thread pool."""
        matches = []
        for pattern in patterns:
            try:
                compiled = re.compile(pattern)
                found = compiled.finditer(content)
                matches.extend(list(found))
            except re.error as e:
                logger.warning("invalid_pattern", pattern=pattern, error=str(e))
        return matches

    def close(self):
        """Shutdown thread pool."""
        self.executor.shutdown(wait=True)
