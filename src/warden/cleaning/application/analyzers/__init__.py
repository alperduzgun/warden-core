"""
Cleanup Analyzers

Individual analyzers for detecting code cleanup opportunities.
"""

from warden.cleaning.analyzers.naming_analyzer import NamingAnalyzer
from warden.cleaning.analyzers.duplication_analyzer import DuplicationAnalyzer
from warden.cleaning.analyzers.magic_number_analyzer import MagicNumberAnalyzer
from warden.cleaning.analyzers.complexity_analyzer import ComplexityAnalyzer

__all__ = [
    "NamingAnalyzer",
    "DuplicationAnalyzer",
    "MagicNumberAnalyzer",
    "ComplexityAnalyzer",
]
