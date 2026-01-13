"""
Cleanup Analyzers

Individual analyzers for detecting code cleanup opportunities.
"""

from warden.cleaning.application.analyzers.naming_analyzer import NamingAnalyzer
from warden.cleaning.application.analyzers.duplication_analyzer import DuplicationAnalyzer
from warden.cleaning.application.analyzers.magic_number_analyzer import MagicNumberAnalyzer
from warden.cleaning.application.analyzers.complexity_analyzer import ComplexityAnalyzer

__all__ = [
    "NamingAnalyzer",
    "DuplicationAnalyzer",
    "MagicNumberAnalyzer",
    "ComplexityAnalyzer",
]
