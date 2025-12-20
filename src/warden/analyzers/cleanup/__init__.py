"""
Cleanup Opportunities Module

Analyzes code for cleanup opportunities and reports improvement suggestions.

IMPORTANT: This module is a REPORTER, not a code modifier.
- Detects cleanup opportunities (poor naming, duplication, SOLID violations, magic numbers)
- Reports suggestions for improvements
- NEVER modifies source code
- Developer decides which suggestions to apply
"""

from warden.analyzers.cleanup.models import (
    CleanupIssue,
    CleanupIssueType,
    CleanupIssueSeverity,
    CleanupResult,
    CleanupSuggestion,
)
from warden.analyzers.cleanup.base import BaseCleanupAnalyzer, CleanupAnalyzerPriority
from warden.analyzers.cleanup.analyzer import CleanupAnalyzer
from warden.analyzers.cleanup.analyzers import (
    NamingAnalyzer,
    DuplicationAnalyzer,
    MagicNumberAnalyzer,
    ComplexityAnalyzer,
)

__all__ = [
    # Models
    "CleanupIssue",
    "CleanupIssueType",
    "CleanupIssueSeverity",
    "CleanupResult",
    "CleanupSuggestion",
    # Base classes
    "BaseCleanupAnalyzer",
    "CleanupAnalyzerPriority",
    # Main analyzer
    "CleanupAnalyzer",
    # Individual analyzers
    "NamingAnalyzer",
    "DuplicationAnalyzer",
    "MagicNumberAnalyzer",
    "ComplexityAnalyzer",
]
