"""
Regression test for Issue #314 - concurrency_limit() must be synchronous.

If someone adds `async` back to the method signature this test will fail
because the return value will be a coroutine instead of an asyncio.Semaphore.
"""

import asyncio
import inspect

import pytest

from warden.llm.global_rate_limiter import GlobalRateLimiter


@pytest.fixture(autouse=True)
def reset_singleton():
    """Ensure a clean singleton for every test."""
    GlobalRateLimiter.reset_instance()
    yield
    GlobalRateLimiter.reset_instance()


class TestConcurrencyLimitIsSynchronous:
    @pytest.mark.asyncio
    async def test_concurrency_limit_is_not_coroutine(self):
        """concurrency_limit() must NOT return a coroutine (Issue #314)."""
        limiter = await GlobalRateLimiter.get_instance()
        result = limiter.concurrency_limit("ollama")
        assert not inspect.iscoroutine(result), (
            "concurrency_limit() returned a coroutine — the method must be synchronous"
        )

    @pytest.mark.asyncio
    async def test_concurrency_limit_returns_semaphore(self):
        """concurrency_limit() must return an asyncio.Semaphore."""
        limiter = await GlobalRateLimiter.get_instance()
        result = limiter.concurrency_limit("ollama")
        assert isinstance(result, asyncio.Semaphore)

    @pytest.mark.asyncio
    async def test_concurrency_limit_for_non_local_provider(self):
        """Non-local providers also get a synchronous Semaphore."""
        limiter = await GlobalRateLimiter.get_instance()
        result = limiter.concurrency_limit("openai")
        assert isinstance(result, asyncio.Semaphore)
        assert not inspect.iscoroutine(result)

    def test_concurrency_limit_method_is_not_async(self):
        """Inspect the method signature: must not be a coroutine function."""
        assert not inspect.iscoroutinefunction(GlobalRateLimiter.concurrency_limit), (
            "concurrency_limit is defined as async — it must be a plain def"
        )
