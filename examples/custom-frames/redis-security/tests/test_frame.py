"""
Tests for redis-security validation frame.
"""

import pytest
from warden.validation.domain.frame import CodeFile
from frame import RedisSecurityFrame


@pytest.mark.asyncio
async def test_frame_initialization():
    """Test frame can be initialized."""
    frame = RedisSecurityFrame()
    assert frame.name == "redis-security"
    assert frame.version == "1.0.0"


@pytest.mark.asyncio
async def test_frame_executes_without_error():
    """Test frame executes successfully."""
    frame = RedisSecurityFrame()

    # Create test code file
    code_file = CodeFile(
        path="test.py",
        content="def hello(): pass",
        language="python",
    )

    # Execute frame
    result = await frame.execute(code_file)

    # Verify result
    assert result.frame_id == frame.frame_id
    assert result.frame_name == frame.name
    assert result.status in ["passed", "failed", "warning"]
    assert result.duration >= 0
    assert isinstance(result.findings, list)


@pytest.mark.asyncio
async def test_frame_detects_issues():
    """Test frame detects validation issues."""
    frame = RedisSecurityFrame()

    # TODO: Create code file with known issues
    code_file = CodeFile(
        path="test.py",
        content="# TODO: Add your test code here",
        language="python",
    )

    result = await frame.execute(code_file)

    # TODO: Add assertions for expected findings
    # assert len(result.findings) > 0
    # assert result.findings[0].severity == "critical"


@pytest.mark.asyncio
async def test_frame_passes_valid_code():
    """Test frame passes on valid code."""
    frame = RedisSecurityFrame()

    # TODO: Create code file with valid code
    code_file = CodeFile(
        path="test.py",
        content="def valid_function(): return True",
        language="python",
    )

    result = await frame.execute(code_file)

    # TODO: Add assertions
    # assert result.status == "passed"
    # assert len(result.findings) == 0
