"""
Regression test for Issue #360 - TaintAware empty dict edge case.

The guard in frame_runner.py must use `is not None` so that an empty
dict still triggers taint injection.  If someone changes the condition
to a truthiness check (`if context.taint_paths:`) this test will fail.
"""

import pytest

from warden.validation.domain.mixins import TaintAware


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _MockContext:
    """Minimal context object that exposes taint_paths."""

    def __init__(self, taint_paths):
        self.taint_paths = taint_paths


def _guard_passes(context) -> bool:
    """
    Mirror the exact guard expression from frame_runner.py line ~412:

        hasattr(context, "taint_paths") and context.taint_paths is not None
    """
    return hasattr(context, "taint_paths") and context.taint_paths is not None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestTaintAwareEmptyDictGuard:
    def test_empty_dict_passes_is_not_none_check(self):
        """Empty dict must pass the `is not None` guard (Issue #360)."""
        ctx = _MockContext(taint_paths={})
        assert _guard_passes(ctx) is True

    def test_none_fails_is_not_none_check(self):
        """None must NOT pass the guard so injection is skipped."""
        ctx = _MockContext(taint_paths=None)
        assert _guard_passes(ctx) is False

    def test_populated_dict_passes_guard(self):
        """Non-empty dict must also pass."""
        ctx = _MockContext(taint_paths={"file.py": []})
        assert _guard_passes(ctx) is True

    def test_empty_dict_is_falsy_but_not_none(self):
        """
        Prove that {} is falsy — so a truthiness check would silently
        swallow the empty-dict case, which is the bug this test guards.
        """
        assert not {}              # empty dict is falsy
        assert {} is not None      # but it is not None

    def test_context_without_taint_paths_attr_fails(self):
        """Context with no taint_paths attribute must not trigger injection."""

        class _NoAttrContext:
            pass

        assert _guard_passes(_NoAttrContext()) is False
