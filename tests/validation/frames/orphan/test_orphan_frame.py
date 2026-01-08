"""
Tests for OrphanFrame - Dead code and unused code detection.

Tests cover:
- Unused imports detection
- Unreferenced functions detection
- Unreferenced classes detection
- Dead code detection
- Configuration options
"""

import pytest
from warden.validation.domain.frame import CodeFile

import pytest
from warden.validation.domain.frame import CodeFile
import importlib.util
import sys
from pathlib import Path

@pytest.fixture
def OrphanFrame():
    # Load directly from plugin file to bypass registry preference for src version
    file_path = Path(".warden/frames/orphan/frame.py").absolute()
    module_name = "orphan_plugin_test"
    
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if not spec or not spec.loader:
        pytest.skip("Could not load OrphanFrame plugin")
        
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    
    return module.OrphanFrame


@pytest.mark.asyncio
async def test_orphan_frame_unused_imports(OrphanFrame):
    """Test OrphanFrame detects unused imports."""
    code = '''
import sys  # ORPHAN - never used
import os
from typing import List  # ORPHAN - never used

def get_home():
    return os.getenv("HOME")
'''

    code_file = CodeFile(
        path="test.py",
        content=code,
        language="python",
    )

    frame = OrphanFrame()
    result = await frame.execute(code_file)

    # Should detect unused imports
    assert result.status == "warning"  # Orphan code is warning
    assert result.is_blocker is False  # Never a blocker
    assert result.issues_found > 0

    # Should have unused import findings
    unused_import_findings = [
        f for f in result.findings if "never used" in f.message.lower()
    ]
    assert len(unused_import_findings) > 0

    # Check metadata
    assert result.metadata is not None
    assert result.metadata["unused_imports"] > 0


@pytest.mark.asyncio
async def test_orphan_frame_unreferenced_functions(OrphanFrame):
    """Test OrphanFrame detects unreferenced functions."""
    code = '''
def used_function():
    return "I am used"

def orphan_function():  # ORPHAN - never called
    return "I am never called"

def main():
    result = used_function()
    print(result)
'''

    code_file = CodeFile(
        path="test.py",
        content=code,
        language="python",
    )

    frame = OrphanFrame()
    result = await frame.execute(code_file)

    # Should detect unreferenced function
    assert result.status == "warning"
    assert result.issues_found > 0

    # Should have unreferenced function finding
    unreferenced_findings = [
        f for f in result.findings if "orphan_function" in f.message
    ]
    assert len(unreferenced_findings) > 0

    # Check severity
    assert unreferenced_findings[0].severity == "medium"

    # Check metadata
    assert result.metadata is not None
    assert result.metadata["unreferenced_functions"] > 0


@pytest.mark.asyncio
async def test_orphan_frame_unreferenced_classes(OrphanFrame):
    """Test OrphanFrame detects unreferenced classes."""
    code = '''
class UsedClass:
    pass

class OrphanClass:  # ORPHAN - never instantiated
    pass

def main():
    obj = UsedClass()
    return obj
'''

    code_file = CodeFile(
        path="test.py",
        content=code,
        language="python",
    )

    frame = OrphanFrame()
    result = await frame.execute(code_file)

    # Should detect unreferenced class
    assert result.status == "warning"
    assert result.issues_found > 0

    # Should have unreferenced class finding
    unreferenced_findings = [
        f for f in result.findings if "OrphanClass" in f.message
    ]
    assert len(unreferenced_findings) > 0

    # Check metadata
    assert result.metadata is not None
    assert result.metadata["unreferenced_classes"] > 0


@pytest.mark.asyncio
async def test_orphan_frame_dead_code(OrphanFrame):
    """Test OrphanFrame detects dead code after return."""
    code = '''
def function_with_dead_code():
    x = 10
    return x
    print("This is dead code")  # ORPHAN - unreachable
    y = 20  # ORPHAN - unreachable
'''

    code_file = CodeFile(
        path="test.py",
        content=code,
        language="python",
    )

    frame = OrphanFrame()
    result = await frame.execute(code_file)

    # Should detect dead code
    assert result.status == "warning"
    assert result.issues_found > 0

    # Should have dead code finding
    dead_code_findings = [
        f for f in result.findings if "unreachable" in f.message.lower()
    ]
    assert len(dead_code_findings) > 0

    # Check severity
    assert dead_code_findings[0].severity == "medium"

    # Check metadata
    assert result.metadata is not None
    assert result.metadata["dead_code"] > 0


@pytest.mark.asyncio
async def test_orphan_frame_dead_code_after_break(OrphanFrame):
    """Test OrphanFrame detects dead code after break."""
    code = '''
def process_items():
    for i in range(10):
        if i == 5:
            break
            print("Unreachable after break")  # ORPHAN - dead code
'''

    code_file = CodeFile(
        path="test.py",
        content=code,
        language="python",
    )

    frame = OrphanFrame()
    result = await frame.execute(code_file)

    # Should detect dead code after break
    assert result.status == "warning"
    assert result.issues_found > 0

    # Should have dead code finding
    dead_code_findings = [
        f for f in result.findings if "unreachable" in f.message.lower()
    ]
    assert len(dead_code_findings) > 0


@pytest.mark.asyncio
async def test_orphan_frame_passes_clean_code(OrphanFrame):
    """Test OrphanFrame passes clean code with no orphans."""
    code = '''
import os

def get_home():
    return os.getenv("HOME")

def main():
    home = get_home()
    print(home)
'''

    code_file = CodeFile(
        path="test.py",
        content=code,
        language="python",
    )

    frame = OrphanFrame()
    result = await frame.execute(code_file)

    # Should pass - no orphan code
    assert result.status == "passed"
    assert result.is_blocker is False
    assert result.issues_found == 0


@pytest.mark.asyncio
async def test_orphan_frame_ignores_private_functions(OrphanFrame):
    """Test OrphanFrame ignores private functions by default."""
    code = '''
def _private_helper():  # Should be ignored (private)
    return "helper"

def public_orphan():  # Should be detected
    return "orphan"
'''

    code_file = CodeFile(
        path="test.py",
        content=code,
        language="python",
    )

    frame = OrphanFrame()
    result = await frame.execute(code_file)

    # Should detect public orphan but not private
    assert result.issues_found > 0

    # Should only have public_orphan finding
    findings = [f for f in result.findings if "public_orphan" in f.message]
    assert len(findings) > 0

    # Should NOT have _private_helper finding
    private_findings = [f for f in result.findings if "_private_helper" in f.message]
    assert len(private_findings) == 0


@pytest.mark.asyncio
async def test_orphan_frame_config_ignore_imports(OrphanFrame):
    """Test OrphanFrame respects ignore_imports configuration."""
    code = '''
import sys  # Should be ignored via config
import os  # Should be detected

def main():
    pass
'''

    code_file = CodeFile(
        path="test.py",
        content=code,
        language="python",
    )

    # Configure to ignore 'sys' import
    config = {
        "ignore_imports": ["sys"]
    }

    frame = OrphanFrame(config=config)
    result = await frame.execute(code_file)

    # Should detect 'os' but not 'sys'
    sys_findings = [f for f in result.findings if "sys" in f.message]
    os_findings = [f for f in result.findings if "os" in f.message]

    assert len(sys_findings) == 0  # sys is ignored
    assert len(os_findings) > 0  # os is detected


@pytest.mark.asyncio
async def test_orphan_frame_skips_non_python_files(OrphanFrame):
    """Test OrphanFrame skips non-Python files."""
    code = '''
// JavaScript code
function unusedFunction() {
    return "orphan";
}
'''

    code_file = CodeFile(
        path="test.js",
        content=code,
        language="javascript",
    )

    frame = OrphanFrame()
    result = await frame.execute(code_file)

    # Should skip (status="skipped")
    assert result.status == "skipped"
    assert result.issues_found == 0
    assert result.metadata is not None
    assert result.metadata.get("skipped") is True


@pytest.mark.asyncio
async def test_orphan_frame_ignores_test_files(OrphanFrame):
    """Test OrphanFrame ignores test files by default."""
    code = '''
import pytest

def test_something():
    assert True
'''

    code_file = CodeFile(
        path="test_module.py",
        content=code,
        language="python",
    )

    frame = OrphanFrame()
    result = await frame.execute(code_file)

    # Should skip test files
    assert result.status == "passed"
    assert result.metadata is not None
    assert result.metadata.get("skipped") is True


@pytest.mark.asyncio
async def test_orphan_frame_handles_syntax_errors(OrphanFrame):
    """Test OrphanFrame handles files with syntax errors."""
    code = '''
def broken_function(
    # Missing closing parenthesis - syntax error
    return "broken"
'''

    code_file = CodeFile(
        path="broken.py",
        content=code,
        language="python",
    )

    frame = OrphanFrame()
    result = await frame.execute(code_file)

    # Should handle gracefully and pass (can't analyze invalid syntax)
    assert result.status == "passed"
    assert result.issues_found == 0


@pytest.mark.asyncio
async def test_orphan_frame_metadata(OrphanFrame):
    """Test OrphanFrame has correct metadata."""
    frame = OrphanFrame()

    assert frame.name == "Orphan Code Analysis"
    assert frame.frame_id == "orphan"
    assert frame.is_blocker is False
    assert frame.priority.value == 3  # MEDIUM = 3
    assert frame.category.value == "language-specific"
    assert frame.scope.value == "file_level"


@pytest.mark.asyncio
async def test_orphan_frame_result_structure(OrphanFrame):
    """Test OrphanFrame result has correct structure (Panel compatibility)."""
    code = '''
import sys  # unused

def orphan():
    return "never called"
'''

    code_file = CodeFile(
        path="test.py",
        content=code,
        language="python",
    )

    frame = OrphanFrame()
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

    # Check metadata contains orphan counts
    assert "unused_imports" in json_data["metadata"]
    assert "unreferenced_functions" in json_data["metadata"]
    assert "unreferenced_classes" in json_data["metadata"]
    assert "dead_code" in json_data["metadata"]


@pytest.mark.asyncio
async def test_orphan_frame_multiple_orphan_types(OrphanFrame):
    """Test OrphanFrame detects multiple orphan types in same file."""
    code = '''
import sys  # ORPHAN - unused import
from typing import List  # ORPHAN - unused import

class OrphanClass:  # ORPHAN - unreferenced class
    pass

def orphan_function():  # ORPHAN - unreferenced function
    return "never called"

def function_with_dead_code():
    x = 10
    return x
    print("Dead code")  # ORPHAN - dead code

def main():
    pass
'''

    code_file = CodeFile(
        path="test.py",
        content=code,
        language="python",
    )

    frame = OrphanFrame()
    result = await frame.execute(code_file)

    # Should detect multiple types
    assert result.status == "warning"
    assert result.issues_found > 0

    # Check metadata has counts for each type
    assert result.metadata is not None
    assert result.metadata["unused_imports"] > 0
    assert result.metadata["unreferenced_functions"] > 0
    assert result.metadata["unreferenced_classes"] > 0
    assert result.metadata["dead_code"] > 0

    # Should have multiple findings
    assert len(result.findings) >= 4


@pytest.mark.asyncio
async def test_orphan_frame_special_functions_ignored(OrphanFrame):
    """Test OrphanFrame ignores special functions like main, __init__."""
    code = '''
def main():  # Should be ignored (special)
    pass

class MyClass:
    def __init__(self):  # Should be ignored (special)
        pass

    def __str__(self):  # Should be ignored (special)
        return "string"

# Use MyClass to ensure it's not flagged as orphan
_ = MyClass()
'''

    code_file = CodeFile(
        path="test.py",
        content=code,
        language="python",
    )

    frame = OrphanFrame()
    result = await frame.execute(code_file)

    # Should pass - special functions are ignored
    assert result.status == "passed"
    assert result.issues_found == 0
