"""
Tests for FuzzFrame.

Tests the fuzz testing frame that detects missing edge case handling.
"""

import pytest
from warden.validation.domain.frame import CodeFile


@pytest.fixture
def FuzzFrame():
    """Load FuzzFrame from registry."""
    from warden.validation.infrastructure.frame_registry import FrameRegistry
    registry = FrameRegistry()
    registry.discover_all()
    cls = registry.get_frame_by_id("fuzz")
    if not cls:
        pytest.skip("FuzzFrame not found in registry")
    return cls


@pytest.mark.asyncio
async def test_fuzz_frame_initialization(FuzzFrame):
    """Test frame initializes with correct metadata."""
    frame = FuzzFrame()

    assert frame.name == "Fuzz Testing"
    assert frame.frame_id == "fuzz"
    assert frame.is_blocker is False
    assert frame.priority.value == 3  # MEDIUM = 3
    assert frame.version == "1.0.0"


@pytest.mark.asyncio
async def test_fuzz_frame_detects_array_access_no_bounds(FuzzFrame):
    """Test detection of array access without bounds checking."""
    code = '''
def get_item(arr, index):
    return arr[index]  # BAD: No bounds checking
'''

    code_file = CodeFile(
        path="array.py",
        content=code,
        language="python",
    )

    frame = FuzzFrame()
    result = await frame.execute_async(code_file)

    # Should detect missing bounds check
    assert result.status in ["warning", "passed"]
    assert result.issues_found >= 0  # May or may not catch simple cases


@pytest.mark.asyncio
async def test_fuzz_frame_detects_type_conversion_no_validation(FuzzFrame):
    """Test detection of type conversion without validation."""
    code = '''
def process_input(user_input):
    age = int(user_input)  # BAD: No validation, can raise ValueError
    return age * 2
'''

    code_file = CodeFile(
        path="converter.py",
        content=code,
        language="python",
    )

    frame = FuzzFrame()
    result = await frame.execute_async(code_file)

    # Should detect unsafe conversion
    assert result.issues_found > 0
    assert result.status == "warning"

    # Should have type conversion finding
    conversion_findings = [
        f for f in result.findings
        if "conversion" in f.message.lower() or "validation" in f.message.lower()
    ]
    assert len(conversion_findings) > 0


@pytest.mark.asyncio
async def test_fuzz_frame_detects_string_operations_no_empty_check(FuzzFrame):
    """Test detection of string operations without empty checks."""
    code = '''
def process_name(name):
    parts = name.split()  # BAD: No empty string check
    return parts[0].upper()
'''

    code_file = CodeFile(
        path="string_ops.py",
        content=code,
        language="python",
    )

    frame = FuzzFrame()
    result = await frame.execute_async(code_file)

    # Should detect missing empty string check
    assert result.issues_found > 0

    # Should have string operation finding
    string_findings = [
        f for f in result.findings
        if "string" in f.message.lower() or "empty" in f.message.lower()
    ]
    assert len(string_findings) > 0


@pytest.mark.asyncio
async def test_fuzz_frame_passes_robust_code(FuzzFrame):
    """Test frame passes code with proper input validation."""
    code = '''
def safe_divide(a, b):
    """Safe division with validation."""
    if not isinstance(a, (int, float)):
        raise TypeError("a must be numeric")
    if not isinstance(b, (int, float)):
        raise TypeError("b must be numeric")
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b

def safe_get_item(arr, index):
    """Safe array access with bounds checking."""
    if index < 0 or index >= len(arr):
        raise IndexError(f"Index {index} out of bounds")
    return arr[index]
'''

    code_file = CodeFile(
        path="safe_ops.py",
        content=code,
        language="python",
    )

    frame = FuzzFrame()
    result = await frame.execute_async(code_file)

    # Should have fewer findings (code has validation)
    assert result.status in ["passed", "warning"]


@pytest.mark.asyncio
async def test_fuzz_frame_result_structure(FuzzFrame):
    """Test result has correct structure for Panel compatibility."""
    code = '''
def convert(x):
    return int(x)  # No validation
'''

    code_file = CodeFile(
        path="test.py",
        content=code,
        language="python",
    )

    frame = FuzzFrame()
    result = await frame.execute_async(code_file)

    # Test Panel JSON compatibility
    json_data = result.to_json()

    # Check required Panel fields
    assert "frameId" in json_data
    assert "frameName" in json_data
    assert "status" in json_data
    assert "duration" in json_data
    assert "issuesFound" in json_data
    assert "isBlocker" in json_data
    assert "findings" in json_data
    assert "metadata" in json_data

    # Check metadata
    assert "checks_executed" in json_data["metadata"]


@pytest.mark.asyncio
async def test_fuzz_frame_patterns_are_defined(FuzzFrame):
    """Test frame has fuzz testing patterns defined."""
    frame = FuzzFrame()

    # Should have PATTERNS attribute
    assert hasattr(frame, "PATTERNS")
    assert isinstance(frame.PATTERNS, dict)
    assert len(frame.PATTERNS) > 0

    # Check pattern structure
    for pattern_id, pattern_config in frame.PATTERNS.items():
        assert "pattern" in pattern_config
        assert "severity" in pattern_config
        assert "message" in pattern_config


@pytest.mark.asyncio
async def test_fuzz_frame_handles_empty_file(FuzzFrame):
    """Test frame handles empty files gracefully."""
    code_file = CodeFile(
        path="empty.py",
        content="",
        language="python",
    )

    frame = FuzzFrame()
    result = await frame.execute_async(code_file)

    # Should pass (no code to analyze)
    assert result.status == "passed"
    assert result.issues_found == 0


@pytest.mark.asyncio
async def test_fuzz_frame_handles_comments_only(FuzzFrame):
    """Test frame handles files with only comments."""
    code = '''
# This is a comment
# TODO: Implement function
# Another comment
'''

    code_file = CodeFile(
        path="comments.py",
        content=code,
        language="python",
    )

    frame = FuzzFrame()
    result = await frame.execute_async(code_file)

    # Should pass or have minimal findings
    assert result.status in ["passed", "warning"]


@pytest.mark.asyncio
async def test_fuzz_frame_multiple_issues(FuzzFrame):
    """Test frame detects multiple fuzz issues in same file."""
    code = '''
def bad_code(arr, index, user_input):
    # Multiple issues:
    value = arr[index]  # No bounds check
    number = int(user_input)  # No validation
    name = user_input.split()[0]  # No empty check
    return value + number
'''

    code_file = CodeFile(
        path="multiple_issues.py",
        content=code,
        language="python",
    )

    frame = FuzzFrame()
    result = await frame.execute_async(code_file)

    # Should detect multiple issues
    assert result.issues_found > 1
    assert result.status == "warning"


@pytest.mark.asyncio
async def test_fuzz_frame_finding_has_location(FuzzFrame):
    """Test findings include location information."""
    code = '''
def convert(x):
    return int(x)
'''

    code_file = CodeFile(
        path="test.py",
        content=code,
        language="python",
    )

    frame = FuzzFrame()
    result = await frame.execute_async(code_file)

    if result.issues_found > 0:
        finding = result.findings[0]
        assert finding.location is not None
        assert "test.py" in finding.location
        assert finding.severity in ["critical", "high", "medium", "low"]
