"""
Tests for TimeoutCheck — Resilience Frame Static Check.

Covers:
- TP: HTTP requests without timeout parameter
- FP exclusion: mock sessions, pattern definitions, test fixtures
"""

import pytest

from warden.validation.domain.frame import CodeFile
from warden.validation.frames.resilience._internal.timeout_check import (
    TimeoutCheck,
)


# ============================================================================
# True Positive cases
# ============================================================================

@pytest.mark.asyncio
async def test_requests_get_without_timeout_detected():
    """requests.get() without timeout should be flagged."""
    code = '''
import requests

def fetch_data(url):
    response = requests.get(url)
    return response.json()
'''
    code_file = CodeFile(path="client.py", content=code, language="python")
    check = TimeoutCheck()
    result = await check.execute_async(code_file)

    assert result.passed is False
    assert len(result.findings) >= 1
    assert any("requests HTTP call without timeout" in f.message for f in result.findings)


@pytest.mark.asyncio
async def test_httpx_get_without_timeout_detected():
    """httpx.get() without timeout should be flagged."""
    code = '''
import httpx

def fetch_data(url):
    response = httpx.get(url)
    return response.json()
'''
    code_file = CodeFile(path="client.py", content=code, language="python")
    check = TimeoutCheck()
    result = await check.execute_async(code_file)

    assert result.passed is False
    assert len(result.findings) >= 1
    assert any("httpx HTTP call without timeout" in f.message for f in result.findings)


@pytest.mark.asyncio
async def test_aiohttp_session_without_timeout_detected():
    """aiohttp.ClientSession() without timeout should be flagged."""
    code = '''
import aiohttp

async def fetch_data(url):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            return await resp.json()
'''
    code_file = CodeFile(path="client.py", content=code, language="python")
    check = TimeoutCheck()
    result = await check.execute_async(code_file)

    assert result.passed is False
    assert len(result.findings) >= 1
    assert any("aiohttp session without timeout" in f.message for f in result.findings)


# ============================================================================
# False Positive exclusion cases
# ============================================================================

@pytest.mark.asyncio
async def test_session_with_timeout_not_flagged():
    """self._session pattern (pre-configured timeout) should NOT be flagged."""
    code = '''
import requests

class ApiClient:
    def __init__(self):
        self._session = requests.Session()

    def get(self, url):
        return self._session.get(url).json()
'''
    code_file = CodeFile(path="client.py", content=code, language="python")
    check = TimeoutCheck()
    result = await check.execute_async(code_file)

    # self._session matches _LIBRARY_SAFE_PATTERNS["timeout"] exclusion
    assert result.passed is True
    assert len(result.findings) == 0


@pytest.mark.asyncio
async def test_mock_http_calls_not_flagged():
    """MagicMock / patch patterns in test files should NOT be flagged."""
    code = '''
from unittest.mock import MagicMock, patch

def test_api_call():
    with patch("requests.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200)
        result = mock_get("http://example.com")
        assert result.status_code == 200
'''
    code_file = CodeFile(path="test_client.py", content=code, language="python")
    check = TimeoutCheck()
    result = await check.execute_async(code_file)

    # MagicMock matches _LIBRARY_SAFE_PATTERNS["timeout"] exclusion
    assert result.passed is True
    assert len(result.findings) == 0


@pytest.mark.asyncio
async def test_pattern_definition_not_flagged():
    """RISKY_PATTERNS definition inside check files should NOT be flagged."""
    code = '''
RISKY_PATTERNS = [
    (r"requests\\.(?:get|post)\\((?:(?!timeout).)*?\\)", "desc", "fix"),
]
'''
    code_file = CodeFile(path="some_check.py", content=code, language="python")
    check = TimeoutCheck()
    result = await check.execute_async(code_file)

    # RISKY_PATTERNS matches _LIBRARY_SAFE_PATTERNS["timeout"] exclusion
    assert result.passed is True
    assert len(result.findings) == 0
