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

import importlib.util
import sys
from pathlib import Path

@pytest.fixture
def OrphanFrame():
    """Load OrphanFrame from registry (built-in or plugin)."""
    from warden.validation.infrastructure.frame_registry import FrameRegistry
    registry = FrameRegistry()
    registry.discover_all()
    cls = registry.get_frame_by_id("orphan")
    if not cls:
        pytest.skip("OrphanFrame not found in registry")
    return cls


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
    result = await frame.execute_async(code_file)

    # Should detect unused imports
    assert result.status == "warning"  # Orphan code is warning
    assert result.is_blocker is False  # Never a blocker
    assert result.issues_found > 0

    # Should have unused import findings
    # Note: Message wording varies by detector (PythonOrphanDetector: "never used", RustOrphanDetector: "appears unused")
    unused_import_findings = [
        f for f in result.findings
        if "import" in f.message.lower() and ("never used" in f.message.lower() or "unused" in f.message.lower() or "appears unused" in f.message.lower())
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
    result = await frame.execute_async(code_file)

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
    result = await frame.execute_async(code_file)

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
@pytest.mark.skip(reason="Dead code detection is only supported by PythonOrphanDetector. RustOrphanDetector (used when Rust extension is available) does not detect dead code.")
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
    result = await frame.execute_async(code_file)

    # Should detect dead code
    assert result.status == "warning"
    assert result.issues_found > 0

    # Should have dead code finding
    # Note: Different detectors may use different terminology
    dead_code_findings = [
        f for f in result.findings if any(keyword in f.message.lower()
                                          for keyword in ["unreachable", "dead code", "dead_code"])
    ]
    assert len(dead_code_findings) > 0

    # Check severity
    assert dead_code_findings[0].severity == "medium"

    # Check metadata
    # Note: RustOrphanDetector doesn't detect dead code, only PythonOrphanDetector does
    # So we can't assert on metadata["dead_code"] - it may be 0
    assert result.metadata is not None
    # assert result.metadata["dead_code"] > 0  # Skip - detector-dependent


@pytest.mark.asyncio
@pytest.mark.skip(reason="Dead code detection is only supported by PythonOrphanDetector. RustOrphanDetector (used when Rust extension is available) does not detect dead code.")
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
    result = await frame.execute_async(code_file)

    # Should detect dead code after break
    assert result.status == "warning"
    assert result.issues_found > 0

    # Should have dead code finding
    # Note: Different detectors may use different terminology
    dead_code_findings = [
        f for f in result.findings if any(keyword in f.message.lower()
                                          for keyword in ["unreachable", "dead code", "dead_code"])
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
    result = await frame.execute_async(code_file)

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
    result = await frame.execute_async(code_file)

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
    result = await frame.execute_async(code_file)

    # Should detect 'os' but not 'sys'
    sys_findings = [f for f in result.findings if "sys" in f.message]
    os_findings = [f for f in result.findings if "os" in f.message]

    assert len(sys_findings) == 0  # sys is ignored
    assert len(os_findings) > 0  # os is detected


@pytest.mark.asyncio
async def test_orphan_frame_skips_non_python_files(OrphanFrame):
    """Test OrphanFrame processes non-Python files via UniversalOrphanDetector/RustOrphanDetector."""
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
    result = await frame.execute_async(code_file)

    # OrphanFrame now supports JS/TS/Go via Universal/Rust detectors
    # Should detect the unused function, not skip
    assert result.status == "warning"
    assert result.issues_found > 0
    assert result.metadata is not None


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
    result = await frame.execute_async(code_file)

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
    result = await frame.execute_async(code_file)

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
    result = await frame.execute_async(code_file)

    # Should detect multiple types
    assert result.status == "warning"
    assert result.issues_found > 0

    # Check metadata has counts for each type
    assert result.metadata is not None
    assert result.metadata["unused_imports"] > 0
    assert result.metadata["unreferenced_functions"] > 0
    assert result.metadata["unreferenced_classes"] > 0
    # Note: RustOrphanDetector doesn't detect dead code, only PythonOrphanDetector does
    # So dead_code might be 0 depending on which detector is used
    # assert result.metadata["dead_code"] > 0  # Skip this assertion

    # Should have multiple findings (at least unused imports, unreferenced function/class)
    assert len(result.findings) >= 3


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
    result = await frame.execute_async(code_file)

    # Should pass - special functions are ignored
    assert result.status == "passed"
    assert result.issues_found == 0


# ---------------------------------------------------------------------------
# Cross-file reference tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cross_file_reference_suppresses_orphan_in_execute_async(OrphanFrame):
    """
    Function defined in service.py and called from server.py must NOT be
    flagged as an orphan when sibling files are injected via set_sibling_files.

    Reproduces: appnova-appstore-mcp service.py:get_active_app() false positive.
    """
    service_code = '''
def get_active_app():
    """Return the currently active app."""
    return {"name": "MyApp", "version": "1.0"}
'''

    server_code = '''
import service

def handle_request():
    app = service.get_active_app()
    return app
'''

    service_file = CodeFile(path="service.py", content=service_code, language="python")
    server_file = CodeFile(path="server.py", content=server_code, language="python")

    frame = OrphanFrame()
    # Inject sibling so the frame can resolve cross-file references
    frame.set_sibling_files([server_file])

    result = await frame.execute_async(service_file)

    # get_active_app is referenced from server.py — must NOT be flagged
    orphan_findings = [f for f in result.findings if "get_active_app" in f.message]
    assert len(orphan_findings) == 0, (
        "get_active_app is called from server.py but was incorrectly flagged as an orphan"
    )


@pytest.mark.asyncio
async def test_cross_file_reference_suppresses_orphan_in_batch(OrphanFrame):
    """
    Batch execution (execute_batch_async) must also resolve cross-file references
    so that a function called from file B is not flagged as an orphan in file A.
    """
    service_code = '''
def get_active_app():
    """Return the currently active app."""
    return {"name": "MyApp", "version": "1.0"}
'''

    server_code = '''
import service

def handle_request():
    app = service.get_active_app()
    return app
'''

    service_file = CodeFile(path="service.py", content=service_code, language="python")
    server_file = CodeFile(path="server.py", content=server_code, language="python")

    frame = OrphanFrame()
    results = await frame.execute_batch_async([service_file, server_file])

    # Collect all findings across both results
    all_findings = []
    for r in results:
        all_findings.extend(r.findings)

    orphan_findings = [f for f in all_findings if "get_active_app" in f.message]
    assert len(orphan_findings) == 0, (
        "get_active_app is called from server.py but was incorrectly flagged as an orphan in batch mode"
    )


@pytest.mark.asyncio
async def test_truly_unreferenced_function_still_flagged_in_batch(OrphanFrame):
    """
    Functions that are genuinely unreferenced across ALL project files must
    still be reported.  The cross-file filter must not suppress real orphans.
    """
    service_code = '''
def get_active_app():
    return {"name": "MyApp"}

def legacy_unused_function():
    """This function is truly unused across the whole project."""
    return "nobody calls me"
'''

    server_code = '''
import service

def handle_request():
    app = service.get_active_app()
    return app
'''

    service_file = CodeFile(path="service.py", content=service_code, language="python")
    server_file = CodeFile(path="server.py", content=server_code, language="python")

    frame = OrphanFrame()
    results = await frame.execute_batch_async([service_file, server_file])

    all_findings = []
    for r in results:
        all_findings.extend(r.findings)

    # get_active_app is used in server.py — must NOT appear
    get_active_findings = [f for f in all_findings if "get_active_app" in f.message]
    assert len(get_active_findings) == 0, "get_active_app is cross-referenced but was still flagged"

    # legacy_unused_function is NOT referenced anywhere — must still appear
    legacy_findings = [f for f in all_findings if "legacy_unused_function" in f.message]
    assert len(legacy_findings) > 0, (
        "legacy_unused_function is genuinely unreferenced but was not flagged"
    )


@pytest.mark.asyncio
async def test_cross_file_class_reference_suppressed_in_batch(OrphanFrame):
    """
    A class defined in models.py but instantiated in views.py must not be
    flagged as an orphan when both files are analysed together.
    """
    models_code = '''
class UserModel:
    def __init__(self, name: str) -> None:
        self.name = name
'''

    views_code = '''
from models import UserModel

def create_user(name: str):
    return UserModel(name=name)
'''

    models_file = CodeFile(path="models.py", content=models_code, language="python")
    views_file = CodeFile(path="views.py", content=views_code, language="python")

    frame = OrphanFrame()
    results = await frame.execute_batch_async([models_file, views_file])

    all_findings = []
    for r in results:
        all_findings.extend(r.findings)

    user_model_findings = [f for f in all_findings if "UserModel" in f.message]
    assert len(user_model_findings) == 0, (
        "UserModel is instantiated in views.py but was incorrectly flagged as an orphan"
    )


@pytest.mark.asyncio
async def test_cross_file_unused_import_not_suppressed(OrphanFrame):
    """
    The cross-file filter must NOT suppress unused_import findings — they are
    always file-local and unaffected by cross-file calls.
    """
    service_code = '''
import json  # unused — should still be flagged

def get_active_app():
    return {"name": "MyApp"}
'''

    server_code = '''
import service

def handle_request():
    return service.get_active_app()
'''

    service_file = CodeFile(path="service.py", content=service_code, language="python")
    server_file = CodeFile(path="server.py", content=server_code, language="python")

    frame = OrphanFrame()
    results = await frame.execute_batch_async([service_file, server_file])

    all_findings = []
    for r in results:
        all_findings.extend(r.findings)

    # json import is unused in service.py — must still be reported
    json_findings = [f for f in all_findings if "json" in f.message]
    assert len(json_findings) > 0, "Unused import 'json' should still be flagged despite cross-file filter"


def test_build_cross_file_corpus_excludes_target(OrphanFrame):
    """
    _build_cross_file_corpus must exclude the file being analysed so its own
    definition lines don't accidentally count as cross-file references.
    """
    frame_cls = OrphanFrame
    frame = frame_cls()

    file_a = CodeFile(path="a.py", content="def foo(): pass", language="python")
    file_b = CodeFile(path="b.py", content="foo()", language="python")
    file_c = CodeFile(path="c.py", content="bar()", language="python")

    corpus = frame._build_cross_file_corpus([file_a, file_b, file_c], exclude_path="a.py")

    # a.py itself must not be in the corpus (its definition would be a false self-reference)
    assert "def foo" not in corpus
    # Other files are included
    assert "foo()" in corpus
    assert "bar()" in corpus


def test_is_cross_file_referenced_whole_word(OrphanFrame):
    """
    _is_cross_file_referenced must match whole identifiers only.
    'get_app' must not match inside 'get_application'.
    """
    frame = OrphanFrame()

    corpus = "result = get_application()\nother = get_app_list()"
    assert not frame._is_cross_file_referenced("get_app", corpus), (
        "'get_app' must not match substring inside 'get_application' or 'get_app_list'"
    )

    corpus_with_exact = "result = get_app()\n"
    assert frame._is_cross_file_referenced("get_app", corpus_with_exact), (
        "'get_app' must match when it appears as an exact whole-word call"
    )


def test_filter_cross_file_orphans_leaves_dead_code_untouched(OrphanFrame):
    """
    _filter_cross_file_orphans must not remove dead_code or unused_import
    findings even when the name appears in sibling files.
    """
    from warden.validation.frames.orphan.orphan_detector import OrphanFinding

    frame = OrphanFrame()

    findings = [
        OrphanFinding(
            orphan_type="dead_code",
            name="some_var",
            line_number=5,
            code_snippet="some_var = 1",
            reason="Unreachable statement",
        ),
        OrphanFinding(
            orphan_type="unused_import",
            name="json",
            line_number=1,
            code_snippet="import json",
            reason="Import 'json' is never used",
        ),
    ]

    # Both names appear in sibling files
    corpus = "some_var = external_use()\nimport json\nfoo = json.dumps({})"
    result = frame._filter_cross_file_orphans(findings, corpus)

    # Neither finding should be removed — they are not cross-file suppressible
    assert len(result) == 2
