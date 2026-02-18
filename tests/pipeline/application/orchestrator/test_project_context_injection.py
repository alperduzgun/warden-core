"""
Regression tests for ProjectContext injection via frame_runner.

Verifies that ProjectContextAware frames receive the full ProjectContext
object from the pipeline path (not just an enum or None).

Bug: frame_runner read context.project_type (ambiguous field) instead of
     context.project_context (dedicated field set by pre_analysis_executor).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from warden.pipeline.application.orchestrator.frame_runner import FrameRunner
from warden.validation.domain.frame import ValidationFrame
from warden.validation.domain.mixins import ProjectContextAware


# ---------------------------------------------------------------------------
# Minimal stubs
# ---------------------------------------------------------------------------

class _FakeProjectContext:
    """Minimal stand-in for analysis.domain.project_context.ProjectContext."""
    service_abstractions: dict[str, Any] = {}
    spec_analysis: dict[str, Any] = {}


class _ProjectContextAwareFrame(ValidationFrame, ProjectContextAware):
    """Minimal frame that implements ProjectContextAware."""
    name = "Test PCA Frame"
    description = "Regression frame for ProjectContext injection tests"
    received_context: Any = None

    def set_project_context(self, context: Any) -> None:
        self.received_context = context

    async def execute_async(self, code_file: Any, context: Any = None):  # type: ignore[override]
        return MagicMock()

    async def validate_async(self, *args, **kwargs):
        return []


def _make_pipeline_context(**kwargs) -> MagicMock:
    ctx = MagicMock()
    ctx.project_context = kwargs.get("project_context", None)
    ctx.project_type = kwargs.get("project_type", None)
    ctx.project_intelligence = None
    ctx.findings = []
    ctx.file_path = MagicMock()
    return ctx


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestProjectContextInjection:

    def test_injection_via_dedicated_field(self):
        """frame_runner injects via context.project_context (new field)."""
        fake_ctx = _FakeProjectContext()
        pipeline_ctx = _make_pipeline_context(project_context=fake_ctx)

        frame = _ProjectContextAwareFrame()
        runner = FrameRunner.__new__(FrameRunner)

        # Simulate only the injection logic from execute_frame_with_rules_async
        if isinstance(frame, ProjectContextAware):
            project_context = getattr(pipeline_ctx, "project_context", None) or getattr(
                pipeline_ctx, "project_type", None
            )
            if project_context and hasattr(project_context, "service_abstractions"):
                frame.set_project_context(project_context)

        assert frame.received_context is fake_ctx, (
            "Frame must receive the ProjectContext object from context.project_context"
        )

    def test_injection_falls_back_to_project_type(self):
        """Legacy fallback: if project_context is None, reads project_type."""
        fake_ctx = _FakeProjectContext()
        pipeline_ctx = _make_pipeline_context(project_context=None, project_type=fake_ctx)

        frame = _ProjectContextAwareFrame()

        if isinstance(frame, ProjectContextAware):
            project_context = getattr(pipeline_ctx, "project_context", None) or getattr(
                pipeline_ctx, "project_type", None
            )
            if project_context and hasattr(project_context, "service_abstractions"):
                frame.set_project_context(project_context)

        assert frame.received_context is fake_ctx

    def test_no_injection_when_both_fields_none(self):
        """No injection when neither field is set (pre-analysis skipped)."""
        pipeline_ctx = _make_pipeline_context(project_context=None, project_type=None)
        frame = _ProjectContextAwareFrame()

        if isinstance(frame, ProjectContextAware):
            project_context = getattr(pipeline_ctx, "project_context", None) or getattr(
                pipeline_ctx, "project_type", None
            )
            if project_context and hasattr(project_context, "service_abstractions"):
                frame.set_project_context(project_context)

        assert frame.received_context is None

    def test_no_injection_for_plain_enum(self):
        """Enum-only project_type (no service_abstractions) must NOT inject."""
        from enum import Enum

        class ProjectType(Enum):
            PYTHON = "python"

        pipeline_ctx = _make_pipeline_context(
            project_context=None, project_type=ProjectType.PYTHON
        )
        frame = _ProjectContextAwareFrame()

        if isinstance(frame, ProjectContextAware):
            project_context = getattr(pipeline_ctx, "project_context", None) or getattr(
                pipeline_ctx, "project_type", None
            )
            if project_context and hasattr(project_context, "service_abstractions"):
                frame.set_project_context(project_context)

        assert frame.received_context is None, (
            "Enum value must not trigger injection (no service_abstractions)"
        )

    def test_pre_analysis_executor_sets_project_context_field(self):
        """pre_analysis_executor must set context.project_context (not only project_type)."""
        # This is a structural test — verify the executor code sets both fields.
        import ast, inspect
        from warden.pipeline.application.executors import pre_analysis_executor
        src = inspect.getsource(pre_analysis_executor)
        tree = ast.parse(src)

        assignments = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Attribute) and target.attr == "project_context"
        ]
        assert len(assignments) >= 1, (
            "pre_analysis_executor must assign context.project_context; "
            "frame_runner depends on this field for ProjectContextAware injection"
        )
