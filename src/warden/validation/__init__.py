"""Validation module - Frames and checks."""

from warden.validation.domain.check import (
    CheckFinding,
    CheckResult,
    CheckSeverity,
    ValidationCheck,
)
from warden.validation.domain.enums import (
    FrameApplicability,
    FrameCategory,
    FramePriority,
    FrameScope,
)
from warden.validation.domain.frame import (
    CodeFile,
    Finding,
    FrameResult,
    ValidationFrame,
    ValidationFrameError,
)

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
]
