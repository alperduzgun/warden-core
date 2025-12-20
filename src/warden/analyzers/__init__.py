"""
Warden Code Analyzers

Collection of code analysis modules that detect issues and suggest improvements.

IMPORTANT: All analyzers are REPORTERS, not code modifiers.
- Detect issues in code
- Report suggestions for improvements
- NEVER modify source code
- Developer makes final decisions

Available Analyzers:
- Fortification: Detects missing safety measures (error handling, logging, etc.)
- Cleanup: Detects code quality issues (poor naming, duplication, etc.)
- Security: (Future) Security vulnerability detection
- Performance: (Future) Performance issue detection
"""

from warden.analyzers.fortification import (
    BaseFortifier,
    CodeFortifier,
    FortificationResult,
    FortificationSuggestion,
)
from warden.analyzers.cleanup import (
    BaseCleanupAnalyzer,
    CleanupAnalyzer,
    CleanupResult,
    CleanupSuggestion,
)

__all__ = [
    # Fortification
    "BaseFortifier",
    "CodeFortifier",
    "FortificationResult",
    "FortificationSuggestion",
    # Cleanup
    "BaseCleanupAnalyzer",
    "CleanupAnalyzer",
    "CleanupResult",
    "CleanupSuggestion",
]
