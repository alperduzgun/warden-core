"""
Magic Number Analyzer

Detects magic numbers that should be constants:
- Numeric literals in code
- String literals used as constants
- Unexplained numeric values
"""

import ast
import structlog
from typing import List, Optional, Set

from warden.analyzers.cleanup.base import BaseCleanupAnalyzer, CleanupAnalyzerPriority
from warden.analyzers.cleanup.models import (
    CleanupResult,
    CleanupSuggestion,
    CleanupIssue,
    CleanupIssueType,
    CleanupIssueSeverity,
)
from warden.validation.domain.frame import CodeFile

logger = structlog.get_logger()

# Numbers that are NOT magic (common, self-documenting)
ACCEPTABLE_NUMBERS = {0, 1, -1, 2, 10, 100, 1000}

# Acceptable string literals (common patterns)
ACCEPTABLE_STRINGS = {'', ' ', '\n', '\t', ',', '.', '/', '-', '_'}


class MagicNumberAnalyzer(BaseCleanupAnalyzer):
    """
    Analyzer for detecting magic numbers and strings.

    Checks:
    - Numeric literals (except 0, 1, -1)
    - String literals used as configuration
    - Unexplained constants in code
    """

    @property
    def name(self) -> str:
        """Analyzer name."""
        return "Magic Number Analyzer"

    @property
    def priority(self) -> int:
        """Execution priority."""
        return CleanupAnalyzerPriority.MEDIUM

    async def analyze_async(
        self,
        code_file: CodeFile,
        cancellation_token: Optional[str] = None,
    ) -> CleanupResult:
        """
        Analyze code for magic numbers.

        Args:
            code_file: The code file to analyze
            cancellation_token: Optional cancellation token

        Returns:
            CleanupResult with magic number issues
        """
        if not code_file or not code_file.content:
            return CleanupResult(
                success=False,
                file_path="",
                issues_found=0,
                error_message="Code file is empty",
                analyzer_name=self.name,
            )

        try:
            issues = self._analyze_magic_numbers(code_file.content)

            if not issues:
                logger.info(
                    "no_magic_number_issues",
                    file_path=code_file.path,
                    analyzer=self.name,
                )
                return CleanupResult(
                    success=True,
                    file_path=code_file.path,
                    issues_found=0,
                    suggestions=[],
                    cleanup_score=100.0,
                    summary="No magic numbers found",
                    analyzer_name=self.name,
                )

            logger.info(
                "magic_number_issues_found",
                count=len(issues),
                file_path=code_file.path,
            )

            # Convert issues to suggestions
            suggestions = [self._create_suggestion(issue, code_file.content) for issue in issues]

            # Calculate score
            total_lines = len(code_file.content.split("\n"))
            cleanup_score = self._calculate_cleanup_score(len(issues), total_lines)

            return CleanupResult(
                success=True,
                file_path=code_file.path,
                issues_found=len(issues),
                suggestions=suggestions,
                cleanup_score=cleanup_score,
                summary=f"Found {len(issues)} magic numbers/strings",
                analyzer_name=self.name,
                metrics={
                    "magic_numbers": sum(1 for i in issues if "number" in i.description.lower()),
                    "magic_strings": sum(1 for i in issues if "string" in i.description.lower()),
                },
            )

        except Exception as e:
            logger.error(
                "magic_number_analysis_failed",
                error=str(e),
                file_path=code_file.path,
            )
            return CleanupResult(
                success=False,
                file_path=code_file.path,
                issues_found=0,
                error_message=f"Analysis failed: {str(e)}",
                analyzer_name=self.name,
            )

    def _analyze_magic_numbers(self, code: str) -> List[CleanupIssue]:
        """
        Analyze code for magic numbers using AST.

        Args:
            code: Source code to analyze

        Returns:
            List of magic number issues
        """
        issues = []

        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            logger.warning("syntax_error_in_code", error=str(e))
            return issues

        # Track constants defined at module level
        defined_constants: Set[str] = set()

        # First pass: collect defined constants
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id.isupper():
                        defined_constants.add(target.id)

        # Second pass: find magic numbers
        for node in ast.walk(tree):
            # Skip constant definitions
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id.isupper():
                        continue

            # Check for numeric constants
            if isinstance(node, ast.Num):
                value = node.n
                if value not in ACCEPTABLE_NUMBERS and not self._is_acceptable_context(node):
                    issues.append(
                        CleanupIssue(
                            issue_type=CleanupIssueType.MAGIC_NUMBER,
                            description=f"Magic number '{value}' should be a named constant",
                            line_number=getattr(node, 'lineno', 0),
                            severity=CleanupIssueSeverity.MEDIUM,
                        )
                    )

            # Check for string constants (Python 3.8+)
            elif isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                value = node.value
                if value not in ACCEPTABLE_NUMBERS and not self._is_acceptable_context(node):
                    issues.append(
                        CleanupIssue(
                            issue_type=CleanupIssueType.MAGIC_NUMBER,
                            description=f"Magic number '{value}' should be a named constant",
                            line_number=node.lineno,
                            severity=CleanupIssueSeverity.MEDIUM,
                        )
                    )

            # Check for magic strings
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                value = node.value
                if (len(value) > 2 and
                    value not in ACCEPTABLE_STRINGS and
                    not self._is_acceptable_string_context(node)):
                    issues.append(
                        CleanupIssue(
                            issue_type=CleanupIssueType.MAGIC_NUMBER,
                            description=f"Magic string '{value[:20]}...' should be a named constant",
                            line_number=node.lineno,
                            severity=CleanupIssueSeverity.LOW,
                        )
                    )

        return issues

    def _is_acceptable_context(self, node: ast.AST) -> bool:
        """
        Check if a number is in an acceptable context.

        Args:
            node: AST node

        Returns:
            True if context is acceptable
        """
        # Numbers in list/dict literals are often acceptable
        parent = getattr(node, 'parent', None)
        if parent and isinstance(parent, (ast.List, ast.Dict, ast.Tuple)):
            return True

        # Numbers in default arguments
        if parent and isinstance(parent, ast.arguments):
            return True

        # Numbers in comparisons with 0 or 1
        if parent and isinstance(parent, ast.Compare):
            return True

        return False

    def _is_acceptable_string_context(self, node: ast.AST) -> bool:
        """
        Check if a string is in an acceptable context.

        Args:
            node: AST node

        Returns:
            True if context is acceptable
        """
        # Strings in logging calls
        parent = getattr(node, 'parent', None)
        if parent and isinstance(parent, ast.Call):
            if isinstance(parent.func, ast.Attribute):
                if parent.func.attr in ['info', 'debug', 'warning', 'error', 'critical']:
                    return True

        # Strings in f-strings
        if parent and isinstance(parent, ast.JoinedStr):
            return True

        # Docstrings
        if isinstance(parent, ast.Expr) and isinstance(node, ast.Constant):
            return True

        return False

    def _create_suggestion(self, issue: CleanupIssue, code: str) -> CleanupSuggestion:
        """Create a cleanup suggestion from an issue."""
        # Extract code snippet
        code_snippet = self._get_code_snippet(code, issue.line_number)
        issue.code_snippet = code_snippet

        if "number" in issue.description.lower():
            suggestion = "Extract this number into a named constant with a descriptive name"
            rationale = "Magic numbers make code harder to understand and maintain. Named constants provide context and make updates easier."
            example_code = "# Example:\nMAX_RETRIES = 3  # At the top of the file\n# Then use MAX_RETRIES in your code"
        else:
            suggestion = "Extract this string into a named constant or configuration"
            rationale = "Magic strings should be constants to improve maintainability and prevent typos"
            example_code = "# Example:\nDEFAULT_ENCODING = 'utf-8'  # At the top of the file"

        return CleanupSuggestion(
            issue=issue,
            suggestion=suggestion,
            rationale=rationale,
            example_code=example_code,
        )
