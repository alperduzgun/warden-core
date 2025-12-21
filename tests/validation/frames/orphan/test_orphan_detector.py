"""Tests for OrphanDetector - dead code detection."""

import pytest
from warden.validation.frames.orphan.orphan_detector import (
    OrphanDetector,
    OrphanFinding,
)


class TestOrphanDetector:
    """Tests for OrphanDetector."""

    def test_detect_unused_import(self):
        """Test detection of unused imports."""
        code = """
import os
import sys

def main():
    print("Hello")
    sys.exit(0)
"""
        detector = OrphanDetector(code, "test.py")
        findings = detector.detect_unused_imports()

        # 'os' is imported but never used
        assert len(findings) == 1
        assert findings[0].orphan_type == "unused_import"
        assert findings[0].name == "os"

    def test_detect_unused_from_import(self):
        """Test detection of unused from imports."""
        code = """
from pathlib import Path
from typing import List, Dict

def process(items: List[str]) -> None:
    pass
"""
        detector = OrphanDetector(code, "test.py")
        findings = detector.detect_unused_imports()

        # Path and Dict are unused
        assert len(findings) == 2
        names = {f.name for f in findings}
        assert "Path" in names
        assert "Dict" in names

    def test_no_unused_imports(self):
        """Test when all imports are used."""
        code = """
import os

def check_path():
    return os.path.exists("/tmp")
"""
        detector = OrphanDetector(code, "test.py")
        findings = detector.detect_unused_imports()

        assert len(findings) == 0

    def test_detect_unreferenced_function(self):
        """Test detection of unreferenced functions."""
        code = """
def used_function():
    return "used"

def unused_function():
    return "unused"

def main():
    result = used_function()
"""
        detector = OrphanDetector(code, "test.py")
        findings = detector.detect_unreferenced_definitions()

        # unused_function is never called
        assert len(findings) == 1
        assert findings[0].orphan_type == "unreferenced_function"
        assert findings[0].name == "unused_function"

    def test_detect_unreferenced_class(self):
        """Test detection of unreferenced classes."""
        code = """
class UsedClass:
    pass

class UnusedClass:
    pass

def create():
    return UsedClass()
"""
        detector = OrphanDetector(code, "test.py")
        findings = detector.detect_unreferenced_definitions()

        # UnusedClass is never instantiated
        assert len(findings) == 1
        assert findings[0].orphan_type == "unreferenced_class"
        assert findings[0].name == "UnusedClass"

    def test_skip_private_functions(self):
        """Test that private functions are skipped."""
        code = """
def _private_unused():
    pass

def main():
    pass
"""
        detector = OrphanDetector(code, "test.py")
        findings = detector.detect_unreferenced_definitions()

        # Private functions are skipped
        assert all(f.name != "_private_unused" for f in findings)

    def test_skip_special_methods(self):
        """Test that special methods are skipped."""
        code = """
class MyClass:
    def __init__(self):
        pass

    def __str__(self):
        return "test"

    def unused_method(self):
        pass
"""
        detector = OrphanDetector(code, "test.py")
        findings = detector.detect_unreferenced_definitions()

        # __init__ and __str__ should be skipped
        assert all(f.name not in ["__init__", "__str__"] for f in findings)

    def test_detect_dead_code_after_return(self):
        """Test detection of dead code after return."""
        code = """
def function_with_dead_code():
    x = 1
    return x
    print("This is dead code")
    y = 2
"""
        detector = OrphanDetector(code, "test.py")
        findings = detector.detect_dead_code()

        # Code after return is dead
        assert len(findings) >= 1
        assert any(f.orphan_type == "dead_code" for f in findings)

    def test_detect_dead_code_after_break(self):
        """Test detection of dead code after break."""
        code = """
def loop_function():
    for i in range(10):
        break
        print("Dead code after break")
"""
        detector = OrphanDetector(code, "test.py")
        findings = detector.detect_dead_code()

        # Code after break is dead
        assert len(findings) >= 1

    def test_detect_dead_code_after_continue(self):
        """Test detection of dead code after continue."""
        code = """
def loop_function():
    for i in range(10):
        continue
        print("Dead code after continue")
"""
        detector = OrphanDetector(code, "test.py")
        findings = detector.detect_dead_code()

        # Code after continue is dead
        assert len(findings) >= 1

    def test_no_dead_code(self):
        """Test when there is no dead code."""
        code = """
def clean_function():
    x = 1
    y = 2
    return x + y
"""
        detector = OrphanDetector(code, "test.py")
        findings = detector.detect_dead_code()

        assert len(findings) == 0

    def test_detect_all(self):
        """Test detect_all finds all types of issues."""
        code = """
import os  # unused
from typing import List  # unused

def unused_function():
    pass

def used_function():
    return 42

def function_with_dead_code():
    return 1
    print("dead code")

def main():
    result = used_function()
"""
        detector = OrphanDetector(code, "test.py")
        all_findings = detector.detect_all()

        # Should find: os, List, unused_function, dead_code
        assert len(all_findings) >= 4

        types = {f.orphan_type for f in all_findings}
        assert "unused_import" in types
        assert "unreferenced_function" in types
        assert "dead_code" in types

    def test_invalid_syntax(self):
        """Test handling of invalid syntax."""
        code = """
def broken function():  # Invalid syntax
    pass
"""
        detector = OrphanDetector(code, "test.py")
        findings = detector.detect_all()

        # Should return empty list for invalid syntax
        assert findings == []

    def test_empty_code(self):
        """Test handling of empty code."""
        detector = OrphanDetector("", "test.py")
        findings = detector.detect_all()

        assert findings == []


class TestOrphanFinding:
    """Tests for OrphanFinding dataclass."""

    def test_orphan_finding_creation(self):
        """Test OrphanFinding creation."""
        finding = OrphanFinding(
            orphan_type="unused_import",
            name="os",
            line_number=1,
            code_snippet="import os",
            reason="Import 'os' is never used in the code",
        )

        assert finding.orphan_type == "unused_import"
        assert finding.name == "os"
        assert finding.line_number == 1
        assert "import os" in finding.code_snippet
        assert "never used" in finding.reason
