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
