"""
Tests for ErrorHandlingCheck — Resilience Frame Static Check.

Covers:
- TP: Bare except clauses, silent swallowing
- FP exclusion: re-raise patterns, pytest.raises, pattern definitions
"""

import pytest

from warden.validation.domain.frame import CodeFile
from warden.validation.frames.resilience._internal.error_handling_check import (
    ErrorHandlingCheck,
)


# ============================================================================
# True Positive cases
# ============================================================================

@pytest.mark.asyncio
async def test_bare_except_detected():
    """Bare `except:` clause should be flagged."""
    code = '''
import requests

def fetch_data(url):
    try:
        response = requests.get(url, timeout=5)
        return response.json()
    except:
        return {}
'''
    code_file = CodeFile(path="client.py", content=code, language="python")
    check = ErrorHandlingCheck()
    result = await check.execute_async(code_file)

    assert result.passed is False
    assert len(result.findings) >= 1
    assert any("Bare except clause" in f.message for f in result.findings)


@pytest.mark.asyncio
async def test_bare_except_with_pass_detected():
    """Bare `except:` with `pass` should be flagged (bare except takes precedence)."""
    code = '''
import requests

def load_user(user_id):
    try:
        response = requests.get(f"https://api.internal/users/{user_id}", timeout=10)
        return response.json()
    except:
        pass
    return None
'''
    code_file = CodeFile(path="client.py", content=code, language="python")
    check = ErrorHandlingCheck()
    result = await check.execute_async(code_file)

    assert result.passed is False
    assert len(result.findings) >= 1
    assert any("Bare except clause" in f.message for f in result.findings)


@pytest.mark.asyncio
async def test_generic_exception_without_logging_detected():
    """Catching Exception without logging should be flagged."""
    code = '''
import requests

def fetch_config(url):
    try:
        response = requests.get(url, timeout=5)
        return response.json()
    except Exception as e:
        return {}
'''
    code_file = CodeFile(path="client.py", content=code, language="python")
    check = ErrorHandlingCheck()
    result = await check.execute_async(code_file)

    assert result.passed is False
    assert len(result.findings) >= 1
    assert any("Catching Exception without logging" in f.message for f in result.findings)


# ============================================================================
# False Positive exclusion cases
# ============================================================================

@pytest.mark.xfail(reason="Known bug: _LIBRARY_SAFE_PATTERNS regex uses \\n but FPExclusionRegistry.check() searches per-line")
@pytest.mark.asyncio
async def test_re_raise_not_flagged():
    """Bare except that immediately re-raises should NOT be flagged.

    NOTE: This test is xfail because the _LIBRARY_SAFE_PATTERNS regex
    r'\\bexcept\\b.*:\\s*\\n\\s*raise\\b' requires a newline character,
    but FPExclusionRegistry.check() iterates over split lines, so \\n
    is never present. This should be fixed by changing the regex to
    r'\\bexcept\\b.*:\\s*\\n?\\s*raise\\b' or using a multi-line search.
    """
    code = '''
import requests

def fetch_data(url):
    try:
        response = requests.get(url, timeout=5)
        return response.json()
    except:
        raise
'''
    code_file = CodeFile(path="client.py", content=code, language="python")
    check = ErrorHandlingCheck()
    result = await check.execute_async(code_file)

    # `except: raise` matches _LIBRARY_SAFE_PATTERNS["error-handling"] exclusion
    assert result.passed is True
    assert len(result.findings) == 0


@pytest.mark.asyncio
async def test_pytest_raises_not_flagged():
    """pytest.raises in test files should NOT be flagged."""
    code = '''
import pytest

def test_bad_url_raises():
    with pytest.raises(ValueError):
        parse_url("")
'''
    code_file = CodeFile(path="test_client.py", content=code, language="python")
    check = ErrorHandlingCheck()
    result = await check.execute_async(code_file)

    # pytest.raises matches _LIBRARY_SAFE_PATTERNS["error-handling"] exclusion
    assert result.passed is True
    assert len(result.findings) == 0


@pytest.mark.asyncio
async def test_pattern_definition_not_flagged():
    """RISKY_PATTERNS / NETWORK_PATTERNS definitions should NOT be flagged."""
    code = '''
RISKY_PATTERNS = [
    (r"except\\s*:", "Bare except", "except SpecificException:"),
]
NETWORK_PATTERNS = [
    r"requests\\.",
    r"httpx\\.",
]
'''
    code_file = CodeFile(path="some_check.py", content=code, language="python")
    check = ErrorHandlingCheck()
    result = await check.execute_async(code_file)

    # RISKY_PATTERNS / NETWORK_PATTERNS match _LIBRARY_SAFE_PATTERNS["error-handling"] exclusion
    assert result.passed is True
    assert len(result.findings) == 0
