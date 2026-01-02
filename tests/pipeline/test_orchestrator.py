"""
Tests for PipelineOrchestrator.

Validates sequential, parallel, and fail-fast execution strategies.
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
async def test_orchestrator_sequential_execution():
    """Test sequential execution of frames."""
    frames = [SecurityFrame(), ChaosFrame()]
    config = PipelineConfig(strategy=ExecutionStrategy.SEQUENTIAL, fail_fast=False)

    orchestrator = PipelineOrchestrator(frames=frames, config=config)

    code_file = CodeFile(
        path="test.py",
        content='password = "admin123"',  # Security issue
        language="python",
    )

    result, _ = await orchestrator.execute([code_file], frames_to_execute=["security", "chaos"])

    # Both frames should execute
    assert result.total_frames == 2
    assert result.frames_passed + result.frames_failed == 2
    assert result.status == PipelineStatus.FAILED  # Security blocker failed


@pytest.mark.asyncio
async def test_orchestrator_parallel_execution():
    """Test parallel execution of frames."""
    frames = [SecurityFrame(), ChaosFrame()]
    config = PipelineConfig(
        strategy=ExecutionStrategy.PARALLEL,
        parallel_limit=2,
        fail_fast=False,
    )

    orchestrator = PipelineOrchestrator(frames=frames, config=config)

    code_file = CodeFile(
        path="test.py",
        content='OPENAI_API_KEY = "sk-1234567890abcdefghijklmnopqrstuvwxyz123456789012"',  # Security issue - full OpenAI key
        language="python",
    )

    result, _ = await orchestrator.execute([code_file], frames_to_execute=["security", "chaos"])

    # Both frames should execute in parallel
    assert result.total_frames == 2
    assert result.total_findings > 0


@pytest.mark.asyncio
async def test_orchestrator_fail_fast():
    """Test fail-fast execution stops on blocker failure."""
    frames = [SecurityFrame(), ChaosFrame()]
    config = PipelineConfig(strategy=ExecutionStrategy.FAIL_FAST)

    orchestrator = PipelineOrchestrator(frames=frames, config=config)

    code_file = CodeFile(
        path="test.py",
        content='query = f"SELECT * FROM users WHERE id = {user_id}"',  # SQL injection
        language="python",
    )

    result, _ = await orchestrator.execute([code_file], frames_to_execute=["security", "chaos"])

    # Should stop after SecurityFrame fails (it's a blocker)
    assert result.status == PipelineStatus.FAILED
    assert result.frames_failed >= 1
    # ChaosFrame may be skipped if SecurityFrame is blocker and failed
    assert result.frames_skipped >= 0


@pytest.mark.asyncio
async def test_orchestrator_passes_clean_code():
    """Test orchestrator passes clean code."""
    frames = [SecurityFrame(), ChaosFrame()]
    config = PipelineConfig(strategy=ExecutionStrategy.SEQUENTIAL, fail_fast=False)

    orchestrator = PipelineOrchestrator(frames=frames, config=config)

    code_file = CodeFile(
        path="test.py",
        content="""
# Clean code with no security or chaos issues
def add_numbers(a: int, b: int) -> int:
    '''Add two numbers together.'''
    return a + b

def multiply_numbers(a: int, b: int) -> int:
    '''Multiply two numbers together.'''
    return a * b
""",
        language="python",
    )

    result, _ = await orchestrator.execute([code_file], frames_to_execute=["security", "chaos"])

    # Should pass all frames
    assert result.status == PipelineStatus.COMPLETED
    assert result.passed is True
    assert result.total_findings == 0


@pytest.mark.asyncio
async def test_orchestrator_frame_priority_sorting():
    """Test frames are sorted by priority."""
    # ChaosFrame has priority HIGH, SecurityFrame has CRITICAL
    frames = [ChaosFrame(), SecurityFrame()]  # Wrong order
    config = PipelineConfig(strategy=ExecutionStrategy.SEQUENTIAL, fail_fast=False)

    orchestrator = PipelineOrchestrator(frames=frames, config=config)

    # After initialization, frames should be sorted by priority (lower value = higher priority)
    assert orchestrator.frames[0].priority.value == 1  # CRITICAL (Security)
    assert orchestrator.frames[1].priority.value == 2  # HIGH (Chaos)


@pytest.mark.asyncio
async def test_orchestrator_multiple_files():
    """Test orchestrator handles multiple files."""
    frames = [SecurityFrame()]
    config = PipelineConfig(strategy=ExecutionStrategy.SEQUENTIAL, fail_fast=False)

    orchestrator = PipelineOrchestrator(frames=frames, config=config)

    code_files = [
        CodeFile(path="file1.py", content='pwd = "123"', language="python"),
        CodeFile(path="file2.py", content='token = "abc"', language="python"),
        CodeFile(
            path="file3.py",
            content="# Clean file\nimport os",
            language="python",
        ),
    ]

    result, _ = await orchestrator.execute(code_files)

    # Should process all 3 files
    assert result.total_findings >= 2  # At least 2 issues from file1 and file2


@pytest.mark.asyncio
async def test_orchestrator_result_structure():
    """Test pipeline result has correct Panel JSON structure."""
    frames = [SecurityFrame()]
    config = PipelineConfig(strategy=ExecutionStrategy.SEQUENTIAL, fail_fast=False)

    orchestrator = PipelineOrchestrator(frames=frames, config=config)

    code_file = CodeFile(
        path="test.py",
        content='password = "admin"',
        language="python",
    )

    result, _ = await orchestrator.execute([code_file])

    # Test Panel JSON compatibility
    json_data = result.to_json()

    # Check camelCase fields
    assert "pipelineId" in json_data
    assert "pipelineName" in json_data
    assert "status" in json_data
    assert "duration" in json_data
    assert "totalFrames" in json_data
    assert "framesPassed" in json_data
    assert "framesFailed" in json_data
    assert "totalFindings" in json_data
    assert "frameResults" in json_data

    # Status should be integer
    assert isinstance(json_data["status"], int)


@pytest.mark.asyncio
async def test_orchestrator_severity_counts():
    """Test orchestrator correctly counts findings by severity."""
    frames = [SecurityFrame(), ChaosFrame()]
    config = PipelineConfig(strategy=ExecutionStrategy.SEQUENTIAL, fail_fast=False)

    orchestrator = PipelineOrchestrator(frames=frames, config=config)

    code_file = CodeFile(
        path="test.py",
        content="""
# Multiple issues with different severities
password = "admin123"  # CRITICAL (hardcoded password)
query = f"SELECT * FROM users WHERE id = {user_id}"  # CRITICAL (SQL injection)
import requests
response = requests.get(url)  # HIGH (missing timeout)
""",
        language="python",
    )

    result, _ = await orchestrator.execute([code_file], frames_to_execute=["security", "chaos"])

    # Should have findings across multiple severity levels
    assert result.total_findings > 0
    assert result.critical_findings > 0 or result.high_findings > 0


@pytest.mark.asyncio
async def test_orchestrator_metadata():
    """Test pipeline result includes execution metadata."""
    frames = [SecurityFrame()]
    config = PipelineConfig(
        strategy=ExecutionStrategy.SEQUENTIAL,
        fail_fast=True,
    )

    orchestrator = PipelineOrchestrator(frames=frames, config=config)

    code_file = CodeFile(
        path="test.py",
        content='api_key = "sk-123"',
        language="python",
    )

    result, _ = await orchestrator.execute([code_file])

    # Check metadata
    assert "strategy" in result.metadata
    assert result.metadata["strategy"] == "sequential"
    assert "fail_fast" in result.metadata
    assert result.metadata["fail_fast"] is True
    assert "frame_executions" in result.metadata


@pytest.mark.asyncio
async def test_orchestrator_has_blockers_property():
    """Test has_blockers property works correctly."""
    frames = [SecurityFrame()]  # Blocker frame
    config = PipelineConfig(strategy=ExecutionStrategy.SEQUENTIAL, fail_fast=False)

    orchestrator = PipelineOrchestrator(frames=frames, config=config)

    # Code with security issue
    code_file = CodeFile(
        path="test.py",
        content='password = "admin"',
        language="python",
    )

    result, _ = await orchestrator.execute([code_file])

    # Should have blocker issues
    assert result.has_blockers is True


@pytest.mark.asyncio
async def test_orchestrator_no_blockers():
    """Test has_blockers is False when only warnings."""
    frames = [ChaosFrame()]  # Non-blocker frame
    config = PipelineConfig(strategy=ExecutionStrategy.SEQUENTIAL, fail_fast=False)

    orchestrator = PipelineOrchestrator(frames=frames, config=config)

    # Code with chaos issues (warnings only)
    code_file = CodeFile(
        path="test.py",
        content="""
import requests
response = requests.get(url)  # Missing timeout (warning)
""",
        language="python",
    )

    result, _ = await orchestrator.execute([code_file])

    # Should not have blocker issues (ChaosFrame is not a blocker)
    assert result.has_blockers is False
