"""Backward compatibility wrapper — delegates to warden.self_healing module.

All logic has been moved to ``warden.self_healing``. This file re-exports
the original public API so existing imports continue to work.
"""

from warden.self_healing import (  # noqa: F401
    DiagnosticResult,
    ErrorCategory,
    SelfHealingOrchestrator,
    reset_heal_attempts,
)
from warden.self_healing.strategies.import_healer import IMPORT_TO_PIP as _IMPORT_TO_PIP  # noqa: F401

# Backward-compatible alias
SelfHealingDiagnostic = SelfHealingOrchestrator
