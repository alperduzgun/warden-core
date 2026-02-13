"""Shared fixtures for orchestrator unit tests."""

from datetime import datetime
from pathlib import Path

from warden.pipeline.domain.enums import PipelineStatus
from warden.pipeline.domain.models import PipelineConfig, ValidationPipeline
from warden.pipeline.domain.pipeline_context import PipelineContext
from warden.validation.domain.frame import CodeFile, Finding, FrameResult


def make_context(**overrides) -> PipelineContext:
    """Create a minimal PipelineContext for testing."""
    defaults = {
        "pipeline_id": "test-pipeline",
        "started_at": datetime.now(),
        "file_path": Path("/tmp/test.py"),
        "source_code": "print('hello')",
        "project_root": Path("/tmp"),
    }
    defaults.update(overrides)
    return PipelineContext(**defaults)


def make_finding(
    id: str = "F-001",
    severity: str = "medium",
    msg: str = "test finding",
    **kwargs,
) -> Finding:
    """Create a Finding with sensible defaults."""
    defaults = {
        "id": id,
        "severity": severity,
        "message": msg,
        "location": "test.py:1",
    }
    defaults.update(kwargs)
    return Finding(**defaults)


def make_frame_result(
    frame_id: str = "test_frame",
    findings: list[Finding] | None = None,
    status: str | None = None,
    is_blocker: bool = False,
) -> FrameResult:
    """Create a FrameResult with sensible defaults."""
    findings = findings or []
    return FrameResult(
        frame_id=frame_id,
        frame_name=frame_id,
        status=status or ("failed" if findings else "passed"),
        duration=0.1,
        issues_found=len(findings),
        is_blocker=is_blocker,
        findings=findings,
    )


def make_pipeline(**overrides) -> ValidationPipeline:
    """Create a ValidationPipeline with tracking fields."""
    defaults = {
        "status": PipelineStatus.COMPLETED,
    }
    defaults.update(overrides)
    return ValidationPipeline(**defaults)


def make_code_file(
    path: str = "/tmp/test.py",
    content: str = "x = 1\n",
    language: str = "python",
) -> CodeFile:
    return CodeFile(path=path, content=content, language=language)
