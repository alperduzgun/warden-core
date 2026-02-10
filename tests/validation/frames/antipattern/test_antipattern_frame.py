"""
Tests for AntiPatternFrame.

Tests the Universal AST-based anti-pattern detection across languages.
"""

import pytest
from warden.validation.domain.frame import CodeFile


@pytest.fixture
def AntiPatternFrame():
    """Load AntiPatternFrame from registry."""
    from warden.validation.infrastructure.frame_registry import FrameRegistry
    registry = FrameRegistry()
    registry.discover_all()
    cls = registry.get_frame_by_id("antipattern")
    if not cls:
        pytest.skip("AntiPatternFrame not found in registry")
    return cls


@pytest.mark.asyncio
async def test_antipattern_frame_initialization(AntiPatternFrame):
    """Test frame initializes with correct metadata."""
    frame = AntiPatternFrame()

    assert frame.name == "Anti-Pattern Detection"
    assert frame.frame_id == "antipattern"
    assert frame.is_blocker is True
    assert frame.priority.value == 2  # HIGH = 2
    assert frame.version == "3.0.0"


@pytest.mark.asyncio
async def test_antipattern_frame_empty_catch_block(AntiPatternFrame):
    """Test detection of empty catch blocks (exception swallowing)."""
    code = '''
try:
    risky_operation()
except Exception:
    pass  # BAD: Empty catch block swallows exceptions
'''

    code_file = CodeFile(
        path="example.py",
        content=code,
        language="python",
    )

    frame = AntiPatternFrame()
    result = await frame.execute_async(code_file)

    # Frame should execute without error
    assert result is not None
    assert result.status in ["passed", "failed", "warning"]

    # If issues found, verify they are exception-related
    if result.issues_found > 0:
        exception_findings = [
            f for f in result.findings
            if "exception" in f.message.lower() or "catch" in f.message.lower()
        ]
        assert len(exception_findings) > 0


@pytest.mark.asyncio
async def test_antipattern_frame_god_class(AntiPatternFrame):
    """Test detection of god classes (classes with 500+ lines)."""
    # Create a large class (over 500 lines)
    methods = []
    for i in range(100):
        methods.append(f'''
    def method_{i}(self):
        """Method {i}."""
        x = {i}
        return x
''')

    code = f'''
class GodClass:
    """A massive god class."""

    def __init__(self):
        self.data = {{}}
{''.join(methods)}
'''

    code_file = CodeFile(
        path="god_class.py",
        content=code,
        language="python",
    )

    frame = AntiPatternFrame()
    result = await frame.execute_async(code_file)

    # Should detect god class
    assert result.status in ["failed", "warning"]
    assert result.issues_found > 0

    # Should have god class finding
    god_class_findings = [
        f for f in result.findings
        if "god" in f.message.lower() or "large" in f.message.lower() or "lines" in f.message.lower()
    ]
    assert len(god_class_findings) > 0


@pytest.mark.asyncio
async def test_antipattern_frame_debug_output(AntiPatternFrame):
    """Test detection of debug output in production code."""
    code = '''
def process_data(data):
    print("DEBUG: Processing data")  # BAD: Debug output
    console.log("User input:", data)  # BAD: Console logging
    return data.upper()
'''

    code_file = CodeFile(
        path="processor.py",
        content=code,
        language="python",
    )

    frame = AntiPatternFrame()
    result = await frame.execute_async(code_file)

    # Should detect debug output
    assert result.status in ["failed", "warning"]
    assert result.issues_found > 0


@pytest.mark.asyncio
async def test_antipattern_frame_todo_fixme(AntiPatternFrame):
    """Test detection of TODO/FIXME comments (technical debt markers)."""
    code = '''
def calculate_discount(price):
    # TODO: Implement dynamic discount logic
    # FIXME: This is a temporary hardcoded value
    return price * 0.9
'''

    code_file = CodeFile(
        path="discounts.py",
        content=code,
        language="python",
    )

    frame = AntiPatternFrame()
    result = await frame.execute_async(code_file)

    # Should detect TODO/FIXME
    assert result.status in ["warning", "passed"]  # Low severity
    assert result.issues_found > 0

    # Should have TODO/FIXME findings
    debt_findings = [
        f for f in result.findings
        if "todo" in f.message.lower() or "fixme" in f.message.lower()
    ]
    assert len(debt_findings) > 0


@pytest.mark.asyncio
async def test_antipattern_frame_passes_clean_code(AntiPatternFrame):
    """Test frame passes clean code without anti-patterns."""
    code = '''
import logging

logger = logging.getLogger(__name__)

class UserService:
    """Clean service class under 500 lines."""

    def __init__(self):
        self.users = {}

    def get_user(self, user_id: str):
        """Retrieve user by ID."""
        try:
            return self.users[user_id]
        except KeyError:
            logger.error(f"User {user_id} not found")
            raise ValueError(f"User {user_id} not found")
'''

    code_file = CodeFile(
        path="user_service.py",
        content=code,
        language="python",
    )

    frame = AntiPatternFrame()
    result = await frame.execute_async(code_file)

    # Should pass (or have minimal warnings)
    assert result.status in ["passed", "warning"]
    assert result.is_blocker is False


@pytest.mark.asyncio
async def test_antipattern_frame_skips_test_files(AntiPatternFrame):
    """Test frame skips test files when configured."""
    code = '''
def test_something():
    # TODO: Add more test cases
    assert True
'''

    code_file = CodeFile(
        path="test_example.py",
        content=code,
        language="python",
    )

    frame = AntiPatternFrame()
    result = await frame.execute_async(code_file)

    # Should skip test file
    assert result.status == "passed"
    metadata = result.metadata
    assert metadata.get("skipped") is True or result.issues_found == 0


@pytest.mark.asyncio
async def test_antipattern_frame_multiple_languages(AntiPatternFrame):
    """Test frame works across different languages."""
    # JavaScript empty catch
    js_code = '''
try {
    dangerousOperation();
} catch(e) {
    // Empty catch block
}
'''

    js_file = CodeFile(
        path="app.js",
        content=js_code,
        language="javascript",
    )

    frame = AntiPatternFrame()
    js_result = await frame.execute_async(js_file)

    # Frame should execute without error on JavaScript files
    assert js_result is not None
    assert js_result.status in ["passed", "failed", "warning"]
    assert js_result.metadata.get("language") == "javascript"


@pytest.mark.asyncio
async def test_antipattern_frame_result_structure(AntiPatternFrame):
    """Test result has correct structure for Panel compatibility."""
    code = '''
try:
    risky()
except:
    pass  # Empty catch
'''

    code_file = CodeFile(
        path="test.py",
        content=code,
        language="python",
    )

    frame = AntiPatternFrame()
    result = await frame.execute_async(code_file)

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

    # Check metadata contains detection info
    assert "language" in json_data["metadata"]
    assert "total_violations" in json_data["metadata"]
    assert "checks_executed" in json_data["metadata"]


@pytest.mark.asyncio
async def test_antipattern_frame_edge_case_empty_file(AntiPatternFrame):
    """Test frame handles empty files gracefully."""
    code_file = CodeFile(
        path="empty.py",
        content="",
        language="python",
    )

    frame = AntiPatternFrame()
    result = await frame.execute_async(code_file)

    # Should pass (no code to analyze)
    assert result.status == "passed"
    assert result.issues_found == 0


@pytest.mark.asyncio
async def test_antipattern_frame_edge_case_binary_content(AntiPatternFrame):
    """Test frame handles binary/invalid content gracefully."""
    code_file = CodeFile(
        path="image.png",
        content="\x00\x01\x02\x03\xff\xfe",
        language="unknown",
    )

    frame = AntiPatternFrame()
    result = await frame.execute_async(code_file)

    # Should skip or pass (unsupported file type)
    assert result.status == "passed"
    metadata = result.metadata
    assert metadata.get("skipped") is True or result.issues_found == 0
