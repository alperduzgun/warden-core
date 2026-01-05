"""
Base Cleanup Analyzer Interface

Abstract base class for all cleanup analyzers.
Follows Python ABC pattern (not C# interfaces).
"""

from abc import ABC, abstractmethod
from typing import Optional, Any

from warden.cleaning.domain.models import CleaningResult, CleaningIssueSeverity
from warden.validation.domain.frame import CodeFile


class CleaningAnalyzerPriority:
    """
    Priority levels for cleanup analyzers.

    Lower values execute first.
    """
    CRITICAL = 0  # Critical issues (e.g., severe naming problems)
    HIGH = 1      # High priority (e.g., complexity, duplication)
    MEDIUM = 2    # Medium priority (e.g., magic numbers)
    LOW = 3       # Low priority (e.g., minor style issues)


class BaseCleaningAnalyzer(ABC):
    """
    Abstract base class for code cleanup analyzers.

    Each analyzer implements a specific cleanup check:
    - Naming conventions
    - Code duplication
    - Magic numbers
    - Complexity
    - Documentation
    - Dead code

    IMPORTANT: Warden is a REPORTER, not a code modifier.
    Analyzers ONLY detect and report issues, NEVER modify code.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Analyzer name (e.g., 'Naming Analyzer')."""
        pass

    @property
    @abstractmethod
    def priority(self) -> int:
        """
        Execution priority.

        Returns:
            Priority value (0 = highest, 3 = lowest)
        """
        pass

    @abstractmethod
    async def analyze_async(
        self,
        code_file: CodeFile,
        cancellation_token: Optional[str] = None,
        ast_tree: Optional[Any] = None,
    ) -> CleaningResult:
        """
        Analyze code for cleanup opportunities.

        Args:
            code_file: The code file to analyze
            cancellation_token: Optional cancellation token

        Returns:
            CleaningResult with detected issues and suggestions

        Note:
            This method REPORTS issues only. It NEVER modifies code.
        """
        pass

    def _get_code_snippet(self, code: str, line_number: int, context: int = 2) -> str:
        """
        Extract code snippet around a specific line.

        Args:
            code: Full source code
            line_number: Target line number (1-indexed)
            context: Number of lines before/after to include

        Returns:
            Code snippet as string
        """
        lines = code.split("\n")
        start = max(0, line_number - context - 1)
        end = min(len(lines), line_number + context)

        snippet_lines = lines[start:end]
        return "\n".join(snippet_lines)

    def _calculate_cleanup_score(self, issues_count: int, total_lines: int) -> float:
        """
        Calculate cleanup score (0-100).

        Args:
            issues_count: Number of issues found
            total_lines: Total lines of code

        Returns:
            Score from 0-100 (100 = perfect, no issues)
        """
        if total_lines == 0:
            return 100.0

        # Score decreases based on issue density
        issue_density = issues_count / total_lines
        score = max(0.0, 100.0 - (issue_density * 100.0))
        return round(score, 2)
