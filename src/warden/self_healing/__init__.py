"""Self-healing module — modular error diagnosis and auto-fix.

Public API:
    SelfHealingOrchestrator  — main entry point
    DiagnosticResult         — result dataclass
    ErrorCategory            — error classification enum
    HealingRecord            — persistent cache record
    HealerRegistry           — strategy registry
    ErrorClassifier          — error classifier
"""

from warden.self_healing.classifier import ErrorClassifier
from warden.self_healing.models import DiagnosticResult, ErrorCategory, HealingRecord
from warden.self_healing.orchestrator import SelfHealingOrchestrator, reset_heal_attempts
from warden.self_healing.registry import HealerRegistry

__all__ = [
    "DiagnosticResult",
    "ErrorCategory",
    "ErrorClassifier",
    "HealerRegistry",
    "HealingRecord",
    "SelfHealingOrchestrator",
    "reset_heal_attempts",
]
