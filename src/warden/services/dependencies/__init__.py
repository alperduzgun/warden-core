from .auto_resolver import ensure_dependencies, require_package, resolve_with_llm
from .dependency_manager import DependencyManager
from .self_healing import DiagnosticResult, SelfHealingDiagnostic

__all__ = [
    "DependencyManager",
    "DiagnosticResult",
    "SelfHealingDiagnostic",
    "ensure_dependencies",
    "require_package",
    "resolve_with_llm",
]
