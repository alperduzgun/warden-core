
import pytest
import asyncio
from unittest.mock import AsyncMock, patch
from warden.shared.utils.retry_utils import async_retry

@pytest.mark.asyncio
async def test_async_retry_success():
    """Test that the function returns result on success."""
    mock_func = AsyncMock(return_value="success")

    @async_retry(retries=3, initial_delay=0.01, jitter=False)
    async def decorated_func():
        return await mock_func()

    result = await decorated_func()
    assert result == "success"
    assert mock_func.call_count == 1

@pytest.mark.asyncio
async def test_async_retry_failure_then_success():
    """Test that the function retries validation error."""
    mock_func = AsyncMock(side_effect=[ValueError("fail"), "success"])

    @async_retry(retries=3, initial_delay=0.01, jitter=False, exceptions=(ValueError,))
    async def decorated_func():
        return await mock_func()

    result = await decorated_func()
    assert result == "success"
    assert mock_func.call_count == 2

@pytest.mark.asyncio
async def test_async_retry_all_failures():
    """Test that the function raises exception after max retries."""
    mock_func = AsyncMock(side_effect=ValueError("fail"))

    @async_retry(retries=2, initial_delay=0.01, jitter=False)
    async def decorated_func():
        return await mock_func()

    with pytest.raises(ValueError):
        await decorated_func()
    
    # 1 initial + 2 retries = 3 calls
    assert mock_func.call_count == 3
