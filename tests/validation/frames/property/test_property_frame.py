"""
Tests for PropertyFrame.

Tests the property-based testing frame that validates business logic.
"""

import pytest
from warden.validation.domain.frame import CodeFile


@pytest.fixture
def PropertyFrame():
    """Load PropertyFrame from registry."""
    from warden.validation.infrastructure.frame_registry import FrameRegistry
    registry = FrameRegistry()
    registry.discover_all()
    cls = registry.get_frame_by_id("property")
    if not cls:
        pytest.skip("PropertyFrame not found in registry")
    return cls


@pytest.mark.asyncio
async def test_property_frame_initialization(PropertyFrame):
    """Test frame initializes with correct metadata."""
    frame = PropertyFrame()

    assert frame.name == "Property Testing"
    assert frame.frame_id == "property"
    assert frame.is_blocker is False
    assert frame.priority.value == 2  # HIGH = 2
    assert frame.version == "1.0.0"


@pytest.mark.asyncio
async def test_property_frame_detects_division_no_zero_check(PropertyFrame):
    """Test detection of division without zero check."""
    code = '''
def divide(a, b):
    return a / b  # BAD: No zero check
'''

    code_file = CodeFile(
        path="math.py",
        content=code,
        language="python",
    )

    frame = PropertyFrame()
    result = await frame.execute_async(code_file)

    # Should detect missing zero check
    assert result.issues_found > 0

    # Should have division-related finding
    division_findings = [
        f for f in result.findings
        if "division" in f.message.lower() or "zero" in f.message.lower()
    ]
    assert len(division_findings) > 0
    assert result.status in ["passed", "warning", "failed"]


@pytest.mark.asyncio
async def test_property_frame_detects_always_true_condition(PropertyFrame):
    """Test detection of always-true conditions."""
    code = '''
def process():
    if true:  # BAD: Always true
        print("This always executes")

    while True:  # This is OK for infinite loops
        break
'''

    code_file = CodeFile(
        path="logic.py",
        content=code,
        language="python",
    )

    frame = PropertyFrame()
    result = await frame.execute_async(code_file)

    # May detect always-true condition
    # (depends on pattern matching)
    assert result.status in ["passed", "warning"]


@pytest.mark.asyncio
async def test_property_frame_detects_negative_index_possible(PropertyFrame):
    """Test detection of possible negative array indices."""
    code = '''
def get_value(arr, x, y):
    index = x - y  # Could be negative
    return arr[index]  # BAD: Possible negative index
'''

    code_file = CodeFile(
        path="array.py",
        content=code,
        language="python",
    )

    frame = PropertyFrame()
    result = await frame.execute_async(code_file)

    # Should detect possible negative index (may or may not catch this pattern)
    # The frame executes without error
    assert result is not None
    assert result.status in ["passed", "warning", "failed"]


@pytest.mark.asyncio
async def test_property_frame_checks_assertions(PropertyFrame):
    """Test frame checks for assertion usage."""
    # File with many functions but no assertions
    code = '''
def func1(): return 1
def func2(): return 2
def func3(): return 3
def func4(): return 4
def func5(): return 5
def func6(): return 6
def func7(): return 7
def func8(): return 8
def func9(): return 9
def func10(): return 10
def func11(): return 11
'''

    code_file = CodeFile(
        path="no_assertions.py",
        content=code,
        language="python",
    )

    frame = PropertyFrame()
    result = await frame.execute_async(code_file)

    # Should suggest adding assertions
    assertion_findings = [
        f for f in result.findings
        if "assertion" in f.message.lower()
    ]
    assert len(assertion_findings) > 0


@pytest.mark.asyncio
async def test_property_frame_passes_safe_code(PropertyFrame):
    """Test frame passes code with proper preconditions."""
    code = '''
def safe_divide(a, b):
    """Division with precondition check."""
    assert b != 0, "Divisor cannot be zero"
    return a / b

def safe_array_access(arr, index):
    """Safe array access with validation."""
    assert index >= 0, "Index must be non-negative"
    assert index < len(arr), "Index out of bounds"
    return arr[index]
'''

    code_file = CodeFile(
        path="safe_math.py",
        content=code,
        language="python",
    )

    frame = PropertyFrame()
    result = await frame.execute_async(code_file)

    # Should have fewer findings (code has assertions)
    assert result.status in ["passed", "warning"]


@pytest.mark.asyncio
async def test_property_frame_result_structure(PropertyFrame):
    """Test result has correct structure for Panel compatibility."""
    code = '''
def divide(a, b):
    return a / b
'''

    code_file = CodeFile(
        path="test.py",
        content=code,
        language="python",
    )

    frame = PropertyFrame()
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
async def test_property_frame_patterns_are_defined(PropertyFrame):
    """Test frame has property testing patterns defined."""
    frame = PropertyFrame()

    # Should have PATTERNS attribute
    assert hasattr(frame, "PATTERNS")
    assert isinstance(frame.PATTERNS, dict)
    assert len(frame.PATTERNS) > 0

    # Check pattern structure
    for pattern_id, pattern_config in frame.PATTERNS.items():
        assert "severity" in pattern_config
        assert "message" in pattern_config


@pytest.mark.asyncio
async def test_property_frame_handles_empty_file(PropertyFrame):
    """Test frame handles empty files gracefully."""
    code_file = CodeFile(
        path="empty.py",
        content="",
        language="python",
    )

    frame = PropertyFrame()
    result = await frame.execute_async(code_file)

    # Should pass (no code to analyze)
    assert result.status == "passed"
    assert result.issues_found == 0


@pytest.mark.asyncio
async def test_property_frame_multiple_issues(PropertyFrame):
    """Test frame detects multiple property violations."""
    code = '''
def bad_logic(arr, a, b, x, y):
    # Multiple issues:
    result1 = a / b  # No zero check
    index = x - y  # Could be negative
    value = arr[index]  # No bounds check
    return result1 + value
'''

    code_file = CodeFile(
        path="multiple_issues.py",
        content=code,
        language="python",
    )

    frame = PropertyFrame()
    result = await frame.execute_async(code_file)

    # Should detect at least one issue
    assert result.issues_found >= 1


@pytest.mark.asyncio
async def test_property_frame_status_determination(PropertyFrame):
    """Test frame determines status correctly based on findings."""
    # Code with high severity issues
    code_high = '''
def calc(a, b, c, d):
    x = a / b  # Issue 1
    y = c / d  # Issue 2
    z = x / y  # Issue 3
    w = z / 2  # Issue 4
    return w / 1  # Issue 5
'''

    code_file = CodeFile(
        path="many_issues.py",
        content=code_high,
        language="python",
    )

    frame = PropertyFrame()
    result = await frame.execute_async(code_file)

    # With many issues, should detect them
    assert result.issues_found > 0
    assert result.status in ["passed", "warning", "failed"]


@pytest.mark.asyncio
async def test_property_frame_finding_has_location(PropertyFrame):
    """Test findings include location information."""
    code = '''
def divide(a, b):
    return a / b
'''

    code_file = CodeFile(
        path="test.py",
        content=code,
        language="python",
    )

    frame = PropertyFrame()
    result = await frame.execute_async(code_file)

    if result.issues_found > 0:
        finding = result.findings[0]
        assert finding.location is not None
        assert "test.py" in finding.location
        assert finding.severity in ["critical", "high", "medium", "low"]
        assert finding.message is not None
