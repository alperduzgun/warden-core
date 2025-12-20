"""
Cleanup Analyzers

Individual analyzers for detecting code cleanup opportunities.
"""

from warden.analyzers.cleanup.analyzers.naming_analyzer import NamingAnalyzer
from warden.analyzers.cleanup.analyzers.duplication_analyzer import DuplicationAnalyzer
from warden.analyzers.cleanup.analyzers.magic_number_analyzer import MagicNumberAnalyzer
from warden.analyzers.cleanup.analyzers.complexity_analyzer import ComplexityAnalyzer

__all__ = [
    "NamingAnalyzer",
    "DuplicationAnalyzer",
    "MagicNumberAnalyzer",
    "ComplexityAnalyzer",
]
