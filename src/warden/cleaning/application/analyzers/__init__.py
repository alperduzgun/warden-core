"""
Cleanup Analyzers

Individual analyzers for detecting code cleanup opportunities.
"""

from warden.cleaning.application.analyzers.naming_analyzer import NamingAnalyzer
from warden.cleaning.application.analyzers.duplication_analyzer import DuplicationAnalyzer
from warden.cleaning.application.analyzers.magic_number_analyzer import MagicNumberAnalyzer
from warden.cleaning.application.analyzers.complexity_analyzer import ComplexityAnalyzer
from warden.cleaning.application.analyzers.documentation_analyzer import DocumentationAnalyzer
from warden.cleaning.application.analyzers.lsp_diagnostics_analyzer import LSPDiagnosticsAnalyzer
from warden.cleaning.application.analyzers.maintainability_analyzer import MaintainabilityAnalyzer
from warden.cleaning.application.analyzers.testability_analyzer import TestabilityAnalyzer

__all__ = [
    # Core analyzers
    "NamingAnalyzer",
    "DuplicationAnalyzer",
    "MagicNumberAnalyzer",
    "ComplexityAnalyzer",
    # Extended analyzers
    "DocumentationAnalyzer",
    "LSPDiagnosticsAnalyzer",
    "MaintainabilityAnalyzer",
    "TestabilityAnalyzer",
]
