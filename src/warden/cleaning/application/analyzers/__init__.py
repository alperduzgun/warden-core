"""
Cleanup Analyzers

Individual analyzers for detecting code cleanup opportunities.
"""

from warden.cleaning.application.analyzers.code_simplifier import CodeSimplifierAnalyzer
from warden.cleaning.application.analyzers.complexity_analyzer import ComplexityAnalyzer
from warden.cleaning.application.analyzers.documentation_analyzer import DocumentationAnalyzer
from warden.cleaning.application.analyzers.duplication_analyzer import DuplicationAnalyzer
from warden.cleaning.application.analyzers.magic_number_analyzer import MagicNumberAnalyzer
from warden.cleaning.application.analyzers.maintainability_analyzer import MaintainabilityAnalyzer
from warden.cleaning.application.analyzers.naming_analyzer import NamingAnalyzer
from warden.cleaning.application.analyzers.testability_analyzer import TestabilityAnalyzer

# LSP analyzer has import issues - import conditionally
try:
    from warden.cleaning.application.analyzers.lsp_diagnostics_analyzer import LSPDiagnosticsAnalyzer
    _LSP_AVAILABLE = True
except ImportError:
    _LSP_AVAILABLE = False
    LSPDiagnosticsAnalyzer = None

__all__ = [
    # Core analyzers
    "NamingAnalyzer",
    "DuplicationAnalyzer",
    "MagicNumberAnalyzer",
    "ComplexityAnalyzer",
    "CodeSimplifierAnalyzer",
    # Extended analyzers
    "DocumentationAnalyzer",
    "MaintainabilityAnalyzer",
    "TestabilityAnalyzer",
]

if _LSP_AVAILABLE:
    __all__.append("LSPDiagnosticsAnalyzer")
