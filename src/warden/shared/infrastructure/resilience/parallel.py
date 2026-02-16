"""
Parallel Batch Executor - Global Resilience utility.

Standardizes parallel task execution across frames and core components
with built-in Chaos Engineering protection:
1. Micro-Timeouts: Each task in the batch has its own timeout.
2. Concurrency Control: Semaphore-based throughput limiting.
3. Isolation: Failures in one task do not cascade to others.
"""

import asyncio
import time
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")
R = TypeVar("R")


class ParallelBatchExecutor:
    """
    Executes a batch of async tasks with standardized resilience guardrails.
    """

    def __init__(self, concurrency_limit: int = 4, item_timeout: float = 30.0, return_exceptions: bool = False):
        self.semaphore = asyncio.Semaphore(concurrency_limit)
        self.item_timeout = item_timeout
        self.return_exceptions = return_exceptions

    async def execute_batch(
        self, items: list[T], task_fn: Callable[[T], Coroutine[Any, Any, R]], batch_name: str = "batch"
    ) -> list[R | None]:
        """
        Executes a function across a list of items in parallel with guardrails.
        """
        start_time = time.time()
        logger.debug("parallel_batch_started", batch=batch_name, count=len(items))

        async def _safe_execute(item: T) -> R | None:
            async with self.semaphore:
                try:
                    return await asyncio.wait_for(task_fn(item), timeout=self.item_timeout)
                except asyncio.TimeoutError:
                    logger.warning("parallel_task_timeout", batch=batch_name)
                    return None
                except Exception as e:
                    logger.error("parallel_task_failed", batch=batch_name, error=str(e))
                    if self.return_exceptions:
                        return e  # Return as value for gather to collect
                    return None

        # Build tasks
        tasks = [_safe_execute(item) for item in items]

        # Execute all
        results = await asyncio.gather(*tasks, return_exceptions=self.return_exceptions)

        duration = int((time.time() - start_time) * 1000)
        logger.info("parallel_batch_completed", batch=batch_name, count=len(items), duration_ms=duration)

        return results
