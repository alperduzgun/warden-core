"""Built-in validation frames for Warden."""

from warden.validation.frames.antipattern import AntiPatternFrame
from warden.validation.frames.architecture import ArchitectureFrame
from warden.validation.frames.fuzz import FuzzFrame
from warden.validation.frames.gitchanges import GitChangesFrame
from warden.validation.frames.orphan import OrphanFrame
from warden.validation.frames.property import PropertyFrame
from warden.validation.frames.resilience import ResilienceFrame
from warden.validation.frames.security import SecurityFrame
from warden.validation.frames.spec import SpecFrame

__all__ = [
    "ArchitectureFrame",
    "OrphanFrame",
    "SpecFrame",
    "SecurityFrame",
    "GitChangesFrame",
    "ResilienceFrame",
    "FuzzFrame",
    "PropertyFrame",
    "AntiPatternFrame",
]
