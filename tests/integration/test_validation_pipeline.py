"""
Integration tests for complete validation pipeline.

Tests end-to-end validation flow with real code samples.
"""

import pytest
from warden.pipeline import (
    PipelineOrchestrator,
    PipelineConfig,
    ExecutionStrategy,
    PipelineStatus,
)
from warden.validation.frames import SecurityFrame, ChaosFrame
from warden.validation.domain.frame import CodeFile


@pytest.mark.asyncio
async def test_complete_validation_pipeline_vulnerable_code():
    """
    Test complete pipeline on vulnerable code.

    This is a realistic example of code with multiple issues
    across security and chaos engineering frames.
    """
    # Vulnerable Python code with multiple issues
    vulnerable_code = '''
import requests
import sqlite3

# SECURITY ISSUES:
# - Hardcoded API key (CRITICAL)
# - SQL injection vulnerability (CRITICAL)
# - Hardcoded password (CRITICAL)

OPENAI_API_KEY = "sk-1234567890abcdefghijklmnopqrstuvwxyz123456789012"
DATABASE_PASSWORD = "admin123"

def get_user(user_id):
    # SQL INJECTION: String concatenation in query
    query = f"SELECT * FROM users WHERE id = {user_id}"
    cursor.execute(query)
    return cursor.fetchone()

def call_external_api(prompt):
    # CHAOS ISSUES:
    # - No timeout (HIGH)
    # - No retry mechanism (MEDIUM)
    # - No circuit breaker (MEDIUM)
    # - No error handling (HIGH)

    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
        json={"model": "gpt-4", "messages": [{"role": "user", "content": prompt}]}
    )
    return response.json()

def main():
    user = get_user(input("Enter user ID: "))  # SQL injection!
    print(user)

    result = call_external_api("Hello")  # No resilience patterns!
    print(result)
'''

    code_file = CodeFile(
        path="vulnerable_app.py",
        content=vulnerable_code,
        language="python",
    )

    # Create pipeline with both security and chaos frames
    frames = [SecurityFrame(), ChaosFrame()]
    config = PipelineConfig(
        strategy=ExecutionStrategy.SEQUENTIAL,
        fail_fast=False,  # Run all frames to see all issues
    )

    orchestrator = PipelineOrchestrator(frames=frames, config=config)

    # Execute pipeline
    result = await orchestrator.execute([code_file])

    # Assertions
    assert result.status == PipelineStatus.FAILED  # SecurityFrame blocks
    assert result.total_frames == 2
    assert result.total_findings > 5  # Multiple issues detected

    # Should have critical security findings
    assert result.critical_findings > 0

    # Should have high severity chaos findings
    assert result.high_findings > 0

    # Should have findings from both frames
    frame_names = [fr.frame_name for fr in result.frame_results]
    assert "Security Analysis" in frame_names
    assert "Chaos Engineering" in frame_names

    # SecurityFrame should block (is_blocker=True)
    security_result = next(
        fr for fr in result.frame_results if fr.frame_name == "Security Analysis"
    )
    assert security_result.is_blocker is True
    assert security_result.passed is False

    # ChaosFrame should warn (is_blocker=False)
    chaos_result = next(
        fr for fr in result.frame_results if fr.frame_name == "Chaos Engineering"
    )
    assert chaos_result.is_blocker is False

    print("\n=== PIPELINE EXECUTION REPORT ===")
    print(f"Status: {result.status.name}")
    print(f"Total Findings: {result.total_findings}")
    print(f"  - Critical: {result.critical_findings}")
    print(f"  - High: {result.high_findings}")
    print(f"  - Medium: {result.medium_findings}")
    print(f"  - Low: {result.low_findings}")
    print(f"\nFrames Executed: {result.total_frames}")
    print(f"  - Passed: {result.frames_passed}")
    print(f"  - Failed: {result.frames_failed}")
    print(f"\nDuration: {result.duration:.2f}s")


@pytest.mark.asyncio
async def test_complete_validation_pipeline_secure_code():
    """
    Test complete pipeline on secure, resilient code.

    This demonstrates best practices for security and resilience.
    """
    secure_code = '''
import os
import requests
from tenacity import retry, stop_after_attempt, wait_exponential
from pybreaker import CircuitBreaker
import logging

logger = logging.getLogger(__name__)

# GOOD: API key from environment variable
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# GOOD: Circuit breaker for external service
api_breaker = CircuitBreaker(fail_max=5, timeout_duration=60)

@api_breaker
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def call_external_api(prompt: str) -> dict:
    """
    Call external API with proper resilience patterns.

    - Circuit breaker prevents cascading failures
    - Retry with exponential backoff handles transient errors
    - Timeout prevents hanging
    - Proper error handling with logging
    """
    try:
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            json={
                "model": "gpt-4",
                "messages": [{"role": "user", "content": prompt}]
            },
            timeout=30  # GOOD: Timeout configured
        )
        response.raise_for_status()
        return response.json()

    except requests.Timeout as e:
        logger.error(f"API timeout: {e}")
        return {"error": "API timeout", "fallback": True}

    except requests.HTTPError as e:
        logger.error(f"API HTTP error: {e.response.status_code}")
        raise

    except requests.ConnectionError as e:
        logger.error(f"API connection error: {e}")
        return {"error": "Connection failed", "fallback": True}

def get_user(user_id: str):
    """Get user with parameterized query (no SQL injection)."""
    # GOOD: Parameterized query prevents SQL injection
    query = "SELECT * FROM users WHERE id = ?"
    cursor.execute(query, (user_id,))
    return cursor.fetchone()
'''

    code_file = CodeFile(
        path="secure_app.py",
        content=secure_code,
        language="python",
    )

    # Create pipeline
    frames = [SecurityFrame(), ChaosFrame()]
    config = PipelineConfig(strategy=ExecutionStrategy.SEQUENTIAL)

    orchestrator = PipelineOrchestrator(frames=frames, config=config)

    # Execute pipeline
    result = await orchestrator.execute([code_file])

    # Assertions - should PASS
    assert result.status == PipelineStatus.COMPLETED
    assert result.passed is True
    assert result.total_findings == 0  # No issues
    assert result.frames_failed == 0
    assert result.has_blockers is False

    print("\n=== SECURE CODE VALIDATION ===")
    print(f"Status: {result.status.name} ✅")
    print(f"Total Findings: {result.total_findings}")
    print(f"Frames Passed: {result.frames_passed}/{result.total_frames}")


@pytest.mark.asyncio
async def test_parallel_execution_integration():
    """Test parallel execution with multiple files."""
    frames = [SecurityFrame(), ChaosFrame()]
    config = PipelineConfig(
        strategy=ExecutionStrategy.PARALLEL,
        parallel_limit=2,
    )

    orchestrator = PipelineOrchestrator(frames=frames, config=config)

    code_files = [
        CodeFile(
            path="file1.py",
            content='password = "admin"',
            language="python",
        ),
        CodeFile(
            path="file2.py",
            content='import requests\nrequests.get(url)',
            language="python",
        ),
        CodeFile(
            path="file3.py",
            content='import os\napi_key = os.getenv("KEY")',
            language="python",
        ),
    ]

    result = await orchestrator.execute(code_files)

    # Should process all files
    assert result.total_frames == 2
    assert result.total_findings > 0  # Issues from file1 and file2


@pytest.mark.asyncio
async def test_fail_fast_integration():
    """Test fail-fast stops on blocker failure."""
    frames = [SecurityFrame(), ChaosFrame()]
    config = PipelineConfig(strategy=ExecutionStrategy.FAIL_FAST)

    orchestrator = PipelineOrchestrator(frames=frames, config=config)

    code_file = CodeFile(
        path="critical_issue.py",
        content='query = f"SELECT * FROM users WHERE id = {user_id}"',
        language="python",
    )

    result = await orchestrator.execute([code_file])

    # Should fail fast after SecurityFrame (blocker)
    assert result.status == PipelineStatus.FAILED
    assert result.has_blockers is True

    # ChaosFrame may be skipped
    if result.frames_skipped > 0:
        assert result.frames_skipped == 1  # ChaosFrame skipped


@pytest.mark.asyncio
async def test_panel_json_output_integration():
    """Test complete pipeline produces valid Panel JSON."""
    frames = [SecurityFrame(), ChaosFrame()]
    config = PipelineConfig(strategy=ExecutionStrategy.SEQUENTIAL)

    orchestrator = PipelineOrchestrator(frames=frames, config=config)

    code_file = CodeFile(
        path="test.py",
        content='api_key = "sk-123"',
        language="python",
    )

    result = await orchestrator.execute([code_file])

    # Convert to Panel JSON
    json_data = result.to_json()

    # Validate structure
    assert "pipelineId" in json_data
    assert "status" in json_data
    assert isinstance(json_data["status"], int)  # Enum as integer
    assert "frameResults" in json_data
    assert isinstance(json_data["frameResults"], list)

    # Validate frame results
    for frame_result_json in json_data["frameResults"]:
        assert "frameId" in frame_result_json
        assert "frameName" in frame_result_json
        assert "status" in frame_result_json
        assert "issuesFound" in frame_result_json
        assert "isBlocker" in frame_result_json
        assert "findings" in frame_result_json

    print("\n=== PANEL JSON OUTPUT ===")
    print(f"Pipeline ID: {json_data['pipelineId']}")
    print(f"Status: {json_data['status']}")
    print(f"Total Findings: {json_data['totalFindings']}")
    print(f"Frame Results: {len(json_data['frameResults'])}")
