"""
Validation frames - pluggable validation strategies.

Each frame implements a specific validation strategy:
- SecurityFrame: Security vulnerabilities
- ChaosEngineeringFrame: Resilience patterns
- FuzzTestingFrame: Edge cases
- PropertyTestingFrame: Idempotency
- ArchitecturalConsistencyFrame: Design patterns
- StressTestingFrame: Performance
"""
from warden.core.validation.frames.security import SecurityFrame
from warden.core.validation.frames.chaos import ChaosEngineeringFrame
from warden.core.validation.frames.fuzz import FuzzTestingFrame
from warden.core.validation.frames.property import PropertyTestingFrame
from warden.core.validation.frames.architectural import ArchitecturalConsistencyFrame
from warden.core.validation.frames.stress import StressTestingFrame

__all__ = [
    "SecurityFrame",
    "ChaosEngineeringFrame",
    "FuzzTestingFrame",
    "PropertyTestingFrame",
    "ArchitecturalConsistencyFrame",
    "StressTestingFrame",
]
