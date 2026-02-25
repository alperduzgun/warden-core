"""
Regression tests for FrameRegistry.

Covers:
- _resolve_frame_id: property-based vs class-attribute frame_id (#property_dedup_bug)
- _deduplicate_frames: all non-attribute frames get unique IDs, none are dropped
- abstract hub-stub classes are skipped silently (no ERROR log)
"""

from __future__ import annotations

import inspect

import pytest

from warden.validation.domain.enums import FrameCategory, FramePriority, FrameScope
from warden.validation.domain.frame import ValidationFrame
from warden.validation.infrastructure.frame_registry import FrameRegistry

# ── Shared frame defaults ────────────────────────────────────────────────────

_DEFAULTS = dict(
    name="Test Frame",
    description="desc",
    priority=FramePriority.MEDIUM,
    scope=FrameScope.FILE_LEVEL,
    category=FrameCategory.GLOBAL,
    is_blocker=False,
    version="1.0.0",
    author="test",
    supports_verification=True,
)


def _make_property_frame(frame_id_value: str) -> type[ValidationFrame]:
    """Concrete frame whose frame_id is a @property (inherits base pattern)."""

    class _Frame(ValidationFrame):
        name = _DEFAULTS["name"]
        description = _DEFAULTS["description"]
        priority = _DEFAULTS["priority"]
        scope = _DEFAULTS["scope"]
        category = _DEFAULTS["category"]
        is_blocker = _DEFAULTS["is_blocker"]
        version = _DEFAULTS["version"]
        author = _DEFAULTS["author"]
        supports_verification = _DEFAULTS["supports_verification"]

        @property
        def frame_id(self) -> str:  # type: ignore[override]
            return frame_id_value

        async def execute_async(self, code_files, context=None):  # type: ignore[override]
            pass

    _Frame.__name__ = f"PropFrame_{frame_id_value}"
    _Frame.__qualname__ = _Frame.__name__
    return _Frame


def _make_attr_frame(frame_id_value: str) -> type[ValidationFrame]:
    """Concrete frame whose frame_id is a plain class-level string."""
    attrs = dict(
        **_DEFAULTS,
    )
    attrs["frame_id"] = frame_id_value  # type: ignore[assignment]

    async def execute_async(self, code_files, context=None):  # type: ignore[override]
        pass

    attrs["execute_async"] = execute_async
    cls = type(f"AttrFrame_{frame_id_value}", (ValidationFrame,), attrs)
    return cls  # type: ignore[return-value]


def _make_abstract_frame() -> type[ValidationFrame]:
    """Abstract hub-stub: inherits ValidationFrame but never implements execute_async."""

    class _AbstractStub(ValidationFrame):
        name = "Stub"
        description = "stub"
        priority = FramePriority.MEDIUM
        scope = FrameScope.FILE_LEVEL
        category = FrameCategory.GLOBAL
        is_blocker = False
        version = "1.0.0"
        author = "stub"
        supports_verification = True
        # execute_async intentionally NOT implemented → remains abstract

    return _AbstractStub


# ── _resolve_frame_id ────────────────────────────────────────────────────────


class TestResolveFrameId:
    def test_string_class_attribute_returned_directly(self):
        cls = _make_attr_frame("security")
        assert FrameRegistry._resolve_frame_id(cls) == "security"

    def test_property_based_frame_id_resolved_correctly(self):
        cls = _make_property_frame("myframe")
        assert FrameRegistry._resolve_frame_id(cls) == "myframe"

    def test_abstract_class_returns_none(self):
        cls = _make_abstract_frame()
        assert FrameRegistry._resolve_frame_id(cls) is None

    def test_distinct_property_frames_return_distinct_ids(self):
        """
        Regression: before the fix, all property-based frames shared the same
        property descriptor object and therefore the same 'ID', causing all but
        the first to be silently dropped as duplicates.
        """
        a = _make_property_frame("alpha")
        b = _make_property_frame("beta")
        assert FrameRegistry._resolve_frame_id(a) == "alpha"
        assert FrameRegistry._resolve_frame_id(b) == "beta"


# ── _deduplicate_frames ───────────────────────────────────────────────────────


class TestDeduplicateFrames:
    def test_all_concrete_frames_retained(self):
        """Mix of string-attr and property frames — none should be dropped."""
        registry = FrameRegistry()
        frames = [
            _make_attr_frame("security"),
            _make_attr_frame("resilience"),
            _make_property_frame("orphan"),
            _make_property_frame("fuzz"),
            _make_property_frame("spec"),
        ]
        result = registry._deduplicate_frames(frames)
        ids = sorted(FrameRegistry._resolve_frame_id(f) for f in result)  # type: ignore[arg-type]
        assert ids == ["fuzz", "orphan", "resilience", "security", "spec"]

    def test_true_duplicate_dropped(self):
        registry = FrameRegistry()
        cls_a = _make_attr_frame("security")
        cls_b = _make_attr_frame("security")
        result = registry._deduplicate_frames([cls_a, cls_b])
        assert len(result) == 1
        assert result[0] is cls_a

    def test_abstract_stub_skipped(self):
        registry = FrameRegistry()
        stub = _make_abstract_frame()
        real = _make_attr_frame("security")
        result = registry._deduplicate_frames([stub, real])
        assert len(result) == 1
        assert FrameRegistry._resolve_frame_id(result[0]) == "security"


# ── register() ───────────────────────────────────────────────────────────────


class TestRegister:
    def test_register_string_attribute_frame(self):
        registry = FrameRegistry()
        cls = _make_attr_frame("myframe")
        registry.register(cls)
        assert "myframe" in registry.registered_frames

    def test_register_property_frame(self):
        registry = FrameRegistry()
        cls = _make_property_frame("propframe")
        registry.register(cls)
        assert "propframe" in registry.registered_frames

    def test_abstract_frame_not_registered(self):
        registry = FrameRegistry()
        stub = _make_abstract_frame()
        registry.register(stub)
        assert len(registry.registered_frames) == 0

    def test_no_property_object_key_in_registry(self):
        """All registered frame keys must be strings, never property descriptors."""
        registry = FrameRegistry()
        for cls in [
            _make_attr_frame("security"),
            _make_property_frame("orphan"),
            _make_property_frame("fuzz"),
        ]:
            registry.register(cls)
        for key in registry.registered_frames:
            assert isinstance(key, str), f"Non-string key in registry: {key!r}"
