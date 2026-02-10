"""
Tests for ValidationFrame mixins.

Ensures that the mixin pattern works correctly and frames can opt-in
to optional capabilities without polluting the base ValidationFrame class.
"""

import pytest
from warden.validation.domain.frame import ValidationFrame, FrameResult, CodeFile
from warden.validation.domain.mixins import (
    BatchExecutable,
    ProjectContextAware,
    Cleanable,
)
from warden.validation.domain.enums import (
    FrameCategory,
    FramePriority,
    FrameScope,
)


class MinimalFrame(ValidationFrame):
    """Minimal frame without any mixins."""

    name = "Minimal Test Frame"
    description = "Test frame with no optional capabilities"
    category = FrameCategory.GLOBAL
    priority = FramePriority.LOW
    scope = FrameScope.FILE_LEVEL

    async def execute_async(self, code_file: CodeFile) -> FrameResult:
        return FrameResult(
            frame_id=self.frame_id,
            frame_name=self.name,
            status="passed",
            duration=0.0,
            issues_found=0,
            is_blocker=False,
            findings=[],
        )


class BatchFrame(ValidationFrame, BatchExecutable):
    """Frame with batch execution capability."""

    name = "Batch Test Frame"
    description = "Test frame with batch execution"
    category = FrameCategory.GLOBAL
    priority = FramePriority.LOW
    scope = FrameScope.FILE_LEVEL

    async def execute_async(self, code_file: CodeFile) -> FrameResult:
        return FrameResult(
            frame_id=self.frame_id,
            frame_name=self.name,
            status="passed",
            duration=0.0,
            issues_found=0,
            is_blocker=False,
            findings=[],
        )

    async def execute_batch_async(self, code_files, context=None):
        """Custom batch implementation."""
        return [await self.execute_async(cf) for cf in code_files]


class ContextAwareFrame(ValidationFrame, ProjectContextAware):
    """Frame that uses project context."""

    name = "Context Aware Test Frame"
    description = "Test frame with project context"
    category = FrameCategory.GLOBAL
    priority = FramePriority.LOW
    scope = FrameScope.FILE_LEVEL

    def __init__(self, config=None):
        super().__init__(config)
        self.project_context = None

    def set_project_context(self, context):
        """Store project context."""
        self.project_context = context

    async def execute_async(self, code_file: CodeFile) -> FrameResult:
        return FrameResult(
            frame_id=self.frame_id,
            frame_name=self.name,
            status="passed",
            duration=0.0,
            issues_found=0,
            is_blocker=False,
            findings=[],
        )


class CleanableFrame(ValidationFrame, Cleanable):
    """Frame that needs cleanup."""

    name = "Cleanable Test Frame"
    description = "Test frame with cleanup capability"
    category = FrameCategory.GLOBAL
    priority = FramePriority.LOW
    scope = FrameScope.FILE_LEVEL

    def __init__(self, config=None):
        super().__init__(config)
        self.large_data = "some large data"
        self.cleaned_up = False

    async def cleanup(self):
        """Release resources."""
        self.large_data = None
        self.cleaned_up = True

    async def execute_async(self, code_file: CodeFile) -> FrameResult:
        return FrameResult(
            frame_id=self.frame_id,
            frame_name=self.name,
            status="passed",
            duration=0.0,
            issues_found=0,
            is_blocker=False,
            findings=[],
        )


class FullFeaturedFrame(ValidationFrame, BatchExecutable, ProjectContextAware, Cleanable):
    """Frame with all optional capabilities."""

    name = "Full Featured Test Frame"
    description = "Test frame with all mixins"
    category = FrameCategory.GLOBAL
    priority = FramePriority.LOW
    scope = FrameScope.FILE_LEVEL

    def __init__(self, config=None):
        super().__init__(config)
        self.project_context = None
        self.large_data = "data"
        self.cleaned_up = False

    def set_project_context(self, context):
        self.project_context = context

    async def cleanup(self):
        self.large_data = None
        self.cleaned_up = True

    async def execute_batch_async(self, code_files, context=None):
        return [await self.execute_async(cf) for cf in code_files]

    async def execute_async(self, code_file: CodeFile) -> FrameResult:
        return FrameResult(
            frame_id=self.frame_id,
            frame_name=self.name,
            status="passed",
            duration=0.0,
            issues_found=0,
            is_blocker=False,
            findings=[],
        )


def test_minimal_frame_has_no_optional_capabilities():
    """Minimal frame should not implement any mixins."""
    frame = MinimalFrame()
    assert not isinstance(frame, BatchExecutable)
    assert not isinstance(frame, ProjectContextAware)
    assert not isinstance(frame, Cleanable)


def test_batch_frame_implements_batch_executable():
    """BatchFrame should implement BatchExecutable mixin."""
    frame = BatchFrame()
    assert isinstance(frame, BatchExecutable)
    assert not isinstance(frame, ProjectContextAware)
    assert not isinstance(frame, Cleanable)


def test_context_aware_frame_implements_project_context_aware():
    """ContextAwareFrame should implement ProjectContextAware mixin."""
    frame = ContextAwareFrame()
    assert isinstance(frame, ProjectContextAware)
    assert not isinstance(frame, BatchExecutable)
    assert not isinstance(frame, Cleanable)


def test_cleanable_frame_implements_cleanable():
    """CleanableFrame should implement Cleanable mixin."""
    frame = CleanableFrame()
    assert isinstance(frame, Cleanable)
    assert not isinstance(frame, BatchExecutable)
    assert not isinstance(frame, ProjectContextAware)


def test_full_featured_frame_implements_all_mixins():
    """FullFeaturedFrame should implement all mixins."""
    frame = FullFeaturedFrame()
    assert isinstance(frame, BatchExecutable)
    assert isinstance(frame, ProjectContextAware)
    assert isinstance(frame, Cleanable)


@pytest.mark.asyncio
async def test_batch_executable_works():
    """BatchExecutable mixin should work correctly."""
    frame = BatchFrame()
    code_files = [
        CodeFile(path="test1.py", content="", language="python"),
        CodeFile(path="test2.py", content="", language="python"),
    ]
    results = await frame.execute_batch_async(code_files)
    assert len(results) == 2
    assert all(r.status == "passed" for r in results)


def test_project_context_aware_works():
    """ProjectContextAware mixin should work correctly."""
    frame = ContextAwareFrame()
    context = {"project_type": "monorepo"}
    frame.set_project_context(context)
    assert frame.project_context == context


@pytest.mark.asyncio
async def test_cleanable_works():
    """Cleanable mixin should work correctly."""
    frame = CleanableFrame()
    assert frame.large_data is not None
    assert not frame.cleaned_up

    await frame.cleanup()
    assert frame.large_data is None
    assert frame.cleaned_up


@pytest.mark.asyncio
async def test_full_featured_frame_all_capabilities_work():
    """All mixins should work together correctly."""
    frame = FullFeaturedFrame()

    # Test project context
    context = {"project_type": "monorepo"}
    frame.set_project_context(context)
    assert frame.project_context == context

    # Test batch execution
    code_files = [CodeFile(path="test.py", content="", language="python")]
    results = await frame.execute_batch_async(code_files)
    assert len(results) == 1

    # Test cleanup
    assert frame.large_data is not None
    await frame.cleanup()
    assert frame.large_data is None
    assert frame.cleaned_up


def test_base_validation_frame_is_minimal():
    """ValidationFrame base class should not force mixins on subclasses."""
    # This test verifies that the base class doesn't require subclasses
    # to implement optional methods
    frame = MinimalFrame()

    # Should have core attributes
    assert hasattr(frame, "name")
    assert hasattr(frame, "description")
    assert hasattr(frame, "frame_id")

    # Should NOT force optional capabilities
    assert not hasattr(frame, "cleanup") or not callable(
        getattr(frame, "cleanup", None)
    )
    # Note: execute_batch_async is removed from base class
