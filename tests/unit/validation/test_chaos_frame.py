"""
Tests for ChaosFrame and its built-in checks.

Validates chaos engineering patterns and resilience.
"""

import pytest
from warden.validation.frames.chaos_frame import ChaosFrame
from warden.validation.domain.frame import CodeFile


@pytest.mark.asyncio
async def test_chaos_frame_timeout_detection():
    """Test ChaosFrame detects missing timeouts."""
    code = '''
import requests

def fetch_user_data(user_id):
    # BAD: No timeout parameter
    response = requests.get(f"https://api.example.com/users/{user_id}")
    return response.json()
'''

    code_file = CodeFile(
        path="api_client.py",
        content=code,
        language="python",
    )

    frame = ChaosFrame()
    result = await frame.execute(code_file)

    # Should detect missing timeout
    assert result.status in ["warning", "failed"]
    assert result.issues_found > 0

    # Should have timeout finding
    timeout_findings = [f for f in result.findings if "timeout" in f.message.lower()]
    assert len(timeout_findings) > 0
    assert timeout_findings[0].severity == "high"


@pytest.mark.asyncio
async def test_chaos_frame_retry_detection():
    """Test ChaosFrame detects missing retry logic."""
    code = '''
import httpx

async def call_external_api():
    # BAD: No retry mechanism for transient failures
    response = await httpx.get("https://api.example.com/data", timeout=30.0)
    return response.json()
'''

    code_file = CodeFile(
        path="api.py",
        content=code,
        language="python",
    )

    frame = ChaosFrame()
    result = await frame.execute(code_file)

    # Should detect missing retry
    assert result.status == "warning"
    assert result.issues_found > 0

    # Should have retry finding
    retry_findings = [f for f in result.findings if "retry" in f.message.lower()]
    assert len(retry_findings) > 0


@pytest.mark.asyncio
async def test_chaos_frame_circuit_breaker_detection():
    """Test ChaosFrame detects missing circuit breaker."""
    code = '''
import requests

def get_product_recommendations(user_id):
    # BAD: External service call without circuit breaker
    response = requests.get(
        f"https://recommendations.example.com/api/v1/users/{user_id}",
        timeout=30
    )
    return response.json()
'''

    code_file = CodeFile(
        path="recommendations.py",
        content=code,
        language="python",
    )

    frame = ChaosFrame()
    result = await frame.execute(code_file)

    # Should detect missing circuit breaker
    assert result.status == "warning"
    assert result.issues_found > 0

    # Should have circuit breaker finding
    cb_findings = [f for f in result.findings if "circuit breaker" in f.message.lower()]
    assert len(cb_findings) > 0


@pytest.mark.asyncio
async def test_chaos_frame_error_handling_detection():
    """Test ChaosFrame detects missing error handling."""
    code = '''
import requests

def fetch_data(url):
    # BAD: Network call without try/except
    response = requests.get(url, timeout=30)
    return response.json()
'''

    code_file = CodeFile(
        path="client.py",
        content=code,
        language="python",
    )

    frame = ChaosFrame()
    result = await frame.execute(code_file)

    # Should detect missing error handling
    assert result.status in ["warning", "failed"]
    assert result.issues_found > 0

    # Should have error handling finding
    error_findings = [f for f in result.findings if "error" in f.message.lower() or "try" in f.message.lower()]
    assert len(error_findings) > 0


@pytest.mark.asyncio
async def test_chaos_frame_bare_except_detection():
    """Test ChaosFrame detects dangerous bare except clauses."""
    code = '''
import requests

def fetch_data(url):
    try:
        response = requests.get(url, timeout=30)
        return response.json()
    except:  # BAD: Bare except catches everything!
        pass  # BAD: Silent failure!
'''

    code_file = CodeFile(
        path="dangerous.py",
        content=code,
        language="python",
    )

    frame = ChaosFrame()
    result = await frame.execute(code_file)

    # Should detect bare except
    assert result.status in ["warning", "failed"]
    assert result.issues_found > 0

    # Should have findings about bare except and pass
    findings_messages = [f.message.lower() for f in result.findings]
    assert any("bare except" in msg or "silent" in msg for msg in findings_messages)


@pytest.mark.asyncio
async def test_chaos_frame_infinite_retry_detection():
    """Test ChaosFrame detects dangerous infinite retry loops."""
    code = '''
import requests

def fetch_with_retry(url):
    # BAD: Infinite retry loop!
    while True:
        try:
            response = requests.get(url, timeout=30)
            return response.json()
        except:
            continue  # Keep retrying forever!
'''

    code_file = CodeFile(
        path="bad_retry.py",
        content=code,
        language="python",
    )

    frame = ChaosFrame()
    result = await frame.execute(code_file)

    # Should detect infinite retry
    assert result.status in ["warning", "failed"]
    assert result.issues_found > 0

    # Should have high severity finding about infinite retry
    high_findings = [f for f in result.findings if f.severity == "high"]
    assert len(high_findings) > 0


@pytest.mark.asyncio
async def test_chaos_frame_passes_resilient_code():
    """Test ChaosFrame passes well-designed resilient code."""
    code = '''
import requests
from tenacity import retry, stop_after_attempt, wait_exponential
from pybreaker import CircuitBreaker
import logging

logger = logging.getLogger(__name__)

# GOOD: Circuit breaker configured
breaker = CircuitBreaker(fail_max=5, timeout_duration=60)

@breaker
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def fetch_user_data(user_id: str):
    """Fetch user data with proper resilience patterns."""
    try:
        # GOOD: Timeout configured
        response = requests.get(
            f"https://api.example.com/users/{user_id}",
            timeout=30
        )
        response.raise_for_status()
        return response.json()

    # GOOD: Specific exception handling with logging
    except requests.Timeout as e:
        logger.error(f"Timeout fetching user {user_id}: {e}")
        return {"id": user_id, "name": "Unknown"}  # Fallback

    except requests.ConnectionError as e:
        logger.error(f"Connection error for user {user_id}: {e}")
        raise  # Let retry/circuit breaker handle it

    except requests.HTTPError as e:
        logger.error(f"HTTP error {e.response.status_code} for user {user_id}")
        raise
'''

    code_file = CodeFile(
        path="resilient_client.py",
        content=code,
        language="python",
    )

    frame = ChaosFrame()
    result = await frame.execute(code_file)

    # Should pass all checks
    assert result.status == "passed"
    assert result.is_blocker is False
    assert result.issues_found == 0


@pytest.mark.asyncio
async def test_chaos_frame_check_registry():
    """Test ChaosFrame has all built-in checks registered."""
    frame = ChaosFrame()

    # Should have 4 built-in checks
    all_checks = frame.checks.get_all()
    assert len(all_checks) >= 4

    # Check IDs should be present
    check_ids = [check.id for check in all_checks]
    assert "timeout" in check_ids
    assert "retry" in check_ids
    assert "circuit-breaker" in check_ids
    assert "error-handling" in check_ids


@pytest.mark.asyncio
async def test_chaos_frame_metadata():
    """Test ChaosFrame has correct metadata."""
    frame = ChaosFrame()

    assert frame.name == "Chaos Engineering"
    assert frame.frame_id == "chaos"
    assert frame.is_blocker is False  # Warning only, not blocking
    assert frame.priority.value == "high"


@pytest.mark.asyncio
async def test_chaos_frame_result_structure():
    """Test ChaosFrame result has correct structure (Panel compatibility)."""
    code = '''
import requests

# Missing timeout
response = requests.get("https://api.example.com/data")
'''

    code_file = CodeFile(
        path="test.py",
        content=code,
        language="python",
    )

    frame = ChaosFrame()
    result = await frame.execute(code_file)

    # Test Panel JSON compatibility
    json_data = result.to_json()

    # Check required Panel fields (camelCase)
    assert "frameId" in json_data
    assert "frameName" in json_data
    assert "status" in json_data
    assert "duration" in json_data
    assert "issuesFound" in json_data
    assert "isBlocker" in json_data
    assert "findings" in json_data
    assert "metadata" in json_data

    # Check metadata contains check results
    assert "check_results" in json_data["metadata"]
    assert isinstance(json_data["metadata"]["check_results"], list)


@pytest.mark.asyncio
async def test_chaos_frame_multiple_issues():
    """Test ChaosFrame detects multiple resilience issues in one file."""
    code = '''
import requests

def bad_function(url):
    # BAD: No timeout, no retry, no circuit breaker, no error handling
    response = requests.get(url)
    return response.json()
'''

    code_file = CodeFile(
        path="very_bad.py",
        content=code,
        language="python",
    )

    frame = ChaosFrame()
    result = await frame.execute(code_file)

    # Should detect multiple issues
    assert result.issues_found >= 3  # At least timeout, retry, error-handling
    assert result.status in ["warning", "failed"]

    # Check we have findings from different checks
    finding_sources = set()
    for finding in result.findings:
        # Extract check name from message
        if "timeout" in finding.message.lower():
            finding_sources.add("timeout")
        if "retry" in finding.message.lower():
            finding_sources.add("retry")
        if "error" in finding.message.lower():
            finding_sources.add("error-handling")
        if "circuit" in finding.message.lower():
            finding_sources.add("circuit-breaker")

    # Should have findings from multiple checks
    assert len(finding_sources) >= 2


@pytest.mark.asyncio
async def test_chaos_frame_javascript_timeout():
    """Test ChaosFrame detects missing timeout in JavaScript fetch."""
    code = '''
async function fetchUserData(userId) {
    // BAD: No AbortSignal timeout
    const response = await fetch(`https://api.example.com/users/${userId}`);
    return await response.json();
}
'''

    code_file = CodeFile(
        path="client.js",
        content=code,
        language="javascript",
    )

    frame = ChaosFrame()
    result = await frame.execute(code_file)

    # Should detect missing timeout
    assert result.issues_found > 0
    timeout_findings = [f for f in result.findings if "timeout" in f.message.lower() or "abort" in f.message.lower()]
    assert len(timeout_findings) > 0
