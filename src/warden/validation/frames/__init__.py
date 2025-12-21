"""
Validation Frames Package

Organized collection of validation frames for code analysis.

Each frame is in its own directory with:
- Main frame file (e.g., orphan_frame.py)
- Supporting modules
- Internal checks (if applicable)

Available Frames:
- chaos: Chaos Engineering (resilience testing)
- security: Security Analysis (vulnerability detection)
- orphan: Orphan Code Detection (dead code, unused imports) - NEW: LLM-powered!
- gitchanges: Git Changes Analysis (diff-based validation)

Usage:
    from warden.validation.frames.orphan import OrphanFrame
    from warden.validation.frames.security import SecurityFrame
    from warden.validation.frames.chaos import ChaosFrame
    from warden.validation.frames.gitchanges import GitChangesFrame

    # Or import all
    from warden.validation.frames import (
        OrphanFrame,
        SecurityFrame,
        ChaosFrame,
        GitChangesFrame,
    )
"""

from warden.validation.frames.security import SecurityFrame
from warden.validation.frames.chaos import ChaosFrame
from warden.validation.frames.gitchanges import GitChangesFrame
from warden.validation.frames.orphan import OrphanFrame

__all__ = [
    "SecurityFrame",
    "ChaosFrame",
    "GitChangesFrame",
    "OrphanFrame",
]
