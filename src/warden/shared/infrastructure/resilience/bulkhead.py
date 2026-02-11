"""Bulkhead Resilience Pattern."""

import asyncio
from dataclasses import dataclass
from typing import Optional

from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)

@dataclass
class BulkheadConfig:
    """Configuration for bulkhead pattern."""
    max_concurrent: int = 10
    max_waiting: int = 100
    timeout: float = 30.0

class BulkheadFull(Exception):
    """Raised when bulkhead is at capacity."""
    def __init__(self, name: str, max_concurrent: int):
        self.name = name
        self.max_concurrent = max_concurrent
        super().__init__(
            f"Bulkhead '{name}' at capacity ({max_concurrent} concurrent)"
        )

class Bulkhead:
    """Bulkhead pattern for resource isolation."""
    def __init__(self, name: str, config: BulkheadConfig | None = None):
        self.name = name
        self.config = config or BulkheadConfig()
        self._semaphore = asyncio.Semaphore(self.config.max_concurrent)
        self._waiting = 0

    @property
    def available(self) -> int:
        return self._semaphore._value

    async def __aenter__(self):
        if self._waiting >= self.config.max_waiting:
            raise BulkheadFull(self.name, self.config.max_concurrent)
        self._waiting += 1
        try:
            await asyncio.wait_for(
                self._semaphore.acquire(),
                timeout=self.config.timeout,
            )
        except asyncio.TimeoutError:
            self._waiting -= 1
            raise BulkheadFull(self.name, self.config.max_concurrent)
        self._waiting -= 1
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self._semaphore.release()
        return False
