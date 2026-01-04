"""Validation module - Frames and checks."""

from warden.validation.domain.enums import (
    FramePriority,
    FrameScope,
    FrameCategory,
    FrameApplicability,
)
from warden.validation.domain.frame import (
    ValidationFrame,
    ValidationFrameError,
    FrameResult,
    Finding,
    CodeFile,
)
from warden.validation.domain.check import (
    ValidationCheck,
    CheckResult,
    CheckFinding,
    CheckSeverity,
)
from warden.validation.frames.security import SecurityFrame
from warden.validation.frames.resilience import ResilienceFrame
from warden.validation.frames.gitchanges import GitChangesFrame
from warden.validation.frames.orphan import OrphanFrame

# Alias
ChaosFrame = ResilienceFrame

__all__ = [
    # Enums
    "FramePriority",
    "FrameScope",
    "FrameCategory",
    "FrameApplicability",
    # Frame models
    "ValidationFrame",
    "ValidationFrameError",
    "FrameResult",
    "Finding",
    "CodeFile",
    # Check models
    "ValidationCheck",
    "CheckResult",
    "CheckFinding",
    "CheckSeverity",
    # Built-in frames
    "SecurityFrame",
    "ResilienceFrame",
    "ChaosFrame",
    "GitChangesFrame",
    "OrphanFrame",
]
