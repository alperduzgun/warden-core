"""
Validation Frames Package

Organized collection of validation frames for code analysis.

Each frame is in its own directory with:
- Main frame file (e.g., orphan_frame.py)
- Supporting modules
- Internal checks (if applicable)

Available Frames:
- security: Security Analysis (vulnerability detection)
- resilience: Resilience Architecture Analysis (Chaos 2.0)
- architectural: Architectural Consistency (file-level)
- project_architecture: Project Architecture (project-level)
- gitchanges: Git Changes Analysis (diff-based validation)
- orphan: Orphan Code Detection (dead code, unused imports) - LLM-powered!
- fuzz: Fuzz Testing (edge case validation)
- property: Property Testing (logic validation)
- stress: Stress Testing (performance & resource validation)

Usage:
    from warden.validation.frames.orphan import OrphanFrame
    from warden.validation.frames.security import SecurityFrame
    from warden.validation.frames.resilience import ResilienceFrame
    from warden.validation.frames.gitchanges import GitChangesFrame
    from warden.validation.frames.fuzz import FuzzFrame
    from warden.validation.frames.property import PropertyFrame
    from warden.validation.frames.stress import StressFrame

    # Or import all
    from warden.validation.frames import (
        SecurityFrame,
        ResilienceFrame,
        ArchitecturalConsistencyFrame,
        ProjectArchitectureFrame,
        GitChangesFrame,
        OrphanFrame,
        FuzzFrame,
        PropertyFrame,
        StressFrame,
    )
"""

from warden.validation.frames.security import SecurityFrame
from warden.validation.frames.resilience import ResilienceFrame
from warden.validation.frames.architectural import ArchitecturalConsistencyFrame
from warden.validation.frames.project_architecture import ProjectArchitectureFrame
from warden.validation.frames.gitchanges import GitChangesFrame
from warden.validation.frames.orphan import OrphanFrame
from warden.validation.frames.fuzz import FuzzFrame
from warden.validation.frames.property import PropertyFrame
from warden.validation.frames.stress import StressFrame
from warden.validation.frames.config import ConfigValidationFrame

# Alias for backward compatibility (optional, but requested to rename)
ChaosFrame = ResilienceFrame

__all__ = [
    "SecurityFrame",
    "ResilienceFrame",
    "ChaosFrame", # Keeping alias for now
    "ArchitecturalConsistencyFrame",
    "ProjectArchitectureFrame",
    "GitChangesFrame",
    "OrphanFrame",
    "FuzzFrame",
    "PropertyFrame",
    "StressFrame",
    "ConfigValidationFrame",
]
