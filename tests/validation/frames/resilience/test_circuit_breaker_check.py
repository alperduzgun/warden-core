"""
Tests for CircuitBreakerCheck — Resilience Frame Static Check.

Covers:
- TP: External HTTP calls without circuit breaker pattern
- FP exclusion: circuit breaker implementation files, pattern definitions
"""

import pytest

from warden.validation.domain.frame import CodeFile
from warden.validation.frames.resilience._internal.circuit_breaker_check import (
    CircuitBreakerCheck,
)


# ============================================================================
# True Positive cases
# ============================================================================

@pytest.mark.asyncio
async def test_raw_http_without_circuit_breaker_detected():
    """requests.post() without circuit breaker should be flagged."""
    code = '''
import requests

def call_payment_service(amount, currency):
    response = requests.post(
        "https://payments.example.com/charge",
        json={"amount": amount, "currency": currency},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()
'''
    code_file = CodeFile(path="payments.py", content=code, language="python")
    check = CircuitBreakerCheck()
    result = await check.execute_async(code_file)

    assert result.passed is False
    assert len(result.findings) == 1
    assert "External service calls without circuit breaker pattern" in result.findings[0].message


@pytest.mark.asyncio
async def test_multiple_http_calls_no_breaker_detected():
    """Multiple external calls without circuit breaker should flag once (file-level)."""
    code = '''
import requests

def send_notification(user_id, message):
    response = requests.post(
        "https://notify.internal/send",
        json={"user_id": user_id, "message": message},
        timeout=10,
    )
    return response.status_code == 200

def fetch_user(user_id):
    response = requests.get(f"https://api.internal/users/{user_id}", timeout=5)
    return response.json()
'''
    code_file = CodeFile(path="services.py", content=code, language="python")
    check = CircuitBreakerCheck()
    result = await check.execute_async(code_file)

    assert result.passed is False
    assert len(result.findings) == 1


# ============================================================================
# False Positive exclusion cases
# ============================================================================

@pytest.mark.asyncio
async def test_pybreaker_decorator_not_flagged():
    """Function decorated with pybreaker should NOT be flagged."""
    code = '''
import pybreaker
import requests

payment_breaker = pybreaker.CircuitBreaker(fail_max=5, timeout_duration=60)

@payment_breaker
def call_payment_service(amount, currency):
    response = requests.post(
        "https://payments.example.com/charge",
        json={"amount": amount, "currency": currency},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()
'''
    code_file = CodeFile(path="payments.py", content=code, language="python")
    check = CircuitBreakerCheck()
    result = await check.execute_async(code_file)

    # pybreaker matches GOOD_PATTERNS → has_circuit_breaker = True
    assert result.passed is True
    assert len(result.findings) == 0


@pytest.mark.asyncio
async def test_circuit_breaker_class_not_flagged():
    """File defining a CircuitBreaker class should NOT be flagged (scanner impl exclusion)."""
    code = '''
class CustomCircuitBreaker:
    def __init__(self, fail_max=5, timeout=60):
        self.fail_max = fail_max
        self.timeout = timeout
        self.state = "closed"

    def call(self, func, *args, **kwargs):
        if self.state == "open":
            raise Exception("Circuit is open")
        try:
            return func(*args, **kwargs)
        except Exception:
            self.state = "open"
            raise
'''
    code_file = CodeFile(path="circuit_breaker.py", content=code, language="python")
    check = CircuitBreakerCheck()
    result = await check.execute_async(code_file)

    # class.*CircuitBreaker matches _LIBRARY_SAFE_PATTERNS["circuit-breaker"] exclusion
    assert result.passed is True
    assert len(result.findings) == 0


@pytest.mark.asyncio
async def test_pattern_definition_not_flagged():
    """GOOD_PATTERNS / RISKY_PATTERNS definitions should NOT be flagged."""
    code = '''
GOOD_PATTERNS = [
    r"CircuitBreaker",
    r"@circuit_breaker",
]
RISKY_PATTERNS = [
    r"requests\\.",
    r"httpx\\.",
]
'''
    code_file = CodeFile(path="some_check.py", content=code, language="python")
    check = CircuitBreakerCheck()
    result = await check.execute_async(code_file)

    # GOOD_PATTERNS / RISKY_PATTERNS match _LIBRARY_SAFE_PATTERNS["circuit-breaker"] exclusion
    assert result.passed is True
    assert len(result.findings) == 0
