"""
Regression test for Issue #352 - Finding severity values must be valid.

Valid severities (from frame.py docstring and Panel TypeScript interface):
    critical | high | medium | low

Invalid values "info" and "warning" must never appear as hardcoded severity
strings in gitchanges_frame.py or spec_frame.py.
"""

import ast
import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths under test
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent.parent
_GITCHANGES = _REPO_ROOT / "src/warden/validation/frames/gitchanges/gitchanges_frame.py"
_SPEC = _REPO_ROOT / "src/warden/validation/frames/spec/spec_frame.py"

VALID_SEVERITIES = {"critical", "high", "medium", "low"}
INVALID_SEVERITIES = {"info", "warning"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_severity_literals(source_path: Path) -> list[str]:
    """
    Parse the AST of *source_path* and return every string literal that
    appears as the value of a keyword argument named ``severity``.
    """
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    found: list[str] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg == "severity" and isinstance(kw.value, ast.Constant):
                found.append(kw.value.value)

    return found


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGitChangesSeverityValues:
    def test_no_invalid_severity_in_gitchanges(self):
        """gitchanges_frame.py must not assign 'info' or 'warning' as severity."""
        severities = _extract_severity_literals(_GITCHANGES)
        bad = [s for s in severities if s in INVALID_SEVERITIES]
        assert not bad, (
            f"gitchanges_frame.py contains invalid severity values: {bad}. "
            f"Allowed: {sorted(VALID_SEVERITIES)}"
        )

    def test_all_gitchanges_severities_are_valid(self):
        """Every severity= keyword in gitchanges_frame.py must be a known value."""
        severities = _extract_severity_literals(_GITCHANGES)
        invalid = [s for s in severities if s not in VALID_SEVERITIES]
        assert not invalid, (
            f"gitchanges_frame.py has unrecognised severity values: {invalid}. "
            f"Allowed: {sorted(VALID_SEVERITIES)}"
        )


class TestSpecSeverityValues:
    def test_no_invalid_severity_in_spec_frame(self):
        """spec_frame.py must not assign 'info' or 'warning' as severity."""
        severities = _extract_severity_literals(_SPEC)
        bad = [s for s in severities if s in INVALID_SEVERITIES]
        assert not bad, (
            f"spec_frame.py contains invalid severity values: {bad}. "
            f"Allowed: {sorted(VALID_SEVERITIES)}"
        )

    def test_all_spec_severities_are_valid(self):
        """Every severity= keyword in spec_frame.py must be a known value."""
        severities = _extract_severity_literals(_SPEC)
        invalid = [s for s in severities if s not in VALID_SEVERITIES]
        assert not invalid, (
            f"spec_frame.py has unrecognised severity values: {invalid}. "
            f"Allowed: {sorted(VALID_SEVERITIES)}"
        )
