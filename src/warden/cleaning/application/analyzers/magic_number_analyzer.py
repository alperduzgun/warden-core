"""
Magic Number Analyzer

Detects magic numbers that should be constants:
- Numeric literals in code
- String literals used as constants
- Unexplained numeric values

Universal multi-language support via tree-sitter AST (uses BaseCleaningAnalyzer helpers).
"""

from typing import Any, List, Optional, Set

import structlog

from warden.ast.domain.enums import ASTNodeType
from warden.ast.domain.models import ASTNode
from warden.cleaning.domain.base import BaseCleaningAnalyzer, CleaningAnalyzerPriority
from warden.cleaning.domain.models import (
    CleaningIssue,
    CleaningIssueSeverity,
    CleaningIssueType,
    CleaningResult,
    CleaningSuggestion,
)
from warden.validation.domain.frame import CodeFile

logger = structlog.get_logger()

# Numbers that are NOT magic (common, self-documenting)
ACCEPTABLE_NUMBERS = {
    0, 1, -1, 2, 3, 4, 5, 8, 10, 12, 16, 24, 32, 60, 64, 100, 128, 180,
    255, 256, 360, 365, 500, 512, 1000, 1024, 2048, 4096, 8080, 8192,
    # Common fractions/percentages
    0.1, 0.25, 0.5, 0.75, 2.0,
}

# Acceptable string literals (common patterns)
ACCEPTABLE_STRINGS = {
    '', ' ', '\n', '\t', '\r', ',', '.', '/', '-', '_', ':', ';',
    'utf-8', 'utf8', 'ascii', 'latin-1',
    'True', 'False', 'None', 'null', 'true', 'false', 'nil',
    'GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS',
    'id', 'name', 'type', 'value', 'key', 'error', 'message', 'status',
}


class MagicNumberAnalyzer(BaseCleaningAnalyzer):
    """
    Analyzer for detecting magic numbers and strings.

    Checks:
    - Numeric literals (except 0, 1, -1)
    - String literals used as configuration
    - Unexplained constants in code

    Universal multi-language support via tree-sitter AST.
    """

    @property
    def name(self) -> str:
        """Analyzer name."""
        return "Magic Number Analyzer"

    @property
    def priority(self) -> int:
        """Execution priority."""
        return CleaningAnalyzerPriority.MEDIUM

    @property
    def supported_languages(self) -> set:
        """Languages supported by this analyzer (universal - all languages)."""
        return set()  # Empty set = universal support (all languages)

    async def analyze_async(
        self,
        code_file: CodeFile,
        cancellation_token: str | None = None,
        ast_tree: Any | None = None,
    ) -> CleaningResult:
        """
        Analyze code for magic numbers using Universal AST.

        Args:
            code_file: The code file to analyze
            cancellation_token: Optional cancellation token
            ast_tree: Optional pre-parsed Universal AST tree

        Returns:
            CleaningResult with magic number issues
        """
        if not code_file or not code_file.content:
            return CleaningResult(
                success=False,
                file_path="",
                issues_found=0,
                error_message="Code file is empty",
                analyzer_name=self.name,
            )

        try:
            # Use base class helper to get AST root
            ast_root = await self._get_ast_root(code_file, ast_tree)

            if not ast_root:
                return CleaningResult(
                    success=True,
                    file_path=code_file.path,
                    issues_found=0,
                    suggestions=[],
                    cleanup_score=100.0,
                    summary="AST parsing not available for this language",
                    analyzer_name=self.name,
                )

            # Analyze magic numbers
            issues = self._analyze_magic_numbers_universal(ast_root)

            if not issues:
                return CleaningResult(
                    success=True,
                    file_path=code_file.path,
                    issues_found=0,
                    suggestions=[],
                    cleanup_score=100.0,
                    summary="No magic numbers found",
                    analyzer_name=self.name,
                )

            # Convert issues to suggestions
            suggestions = [self._create_suggestion(issue, code_file.content) for issue in issues]

            # Calculate score
            total_lines = len(code_file.content.split("\n"))
            cleanup_score = self._calculate_cleanup_score(len(issues), total_lines)

            return CleaningResult(
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
            return CleaningResult(
                success=False,
                file_path=code_file.path,
                issues_found=0,
                error_message=f"Analysis failed: {e!s}",
                analyzer_name=self.name,
            )

    def _analyze_magic_numbers_universal(self, ast_root: ASTNode) -> list[CleaningIssue]:
        """
        Analyze code for magic numbers using Universal AST.

        Works for all languages (Python, Swift, Dart, Go, JS, etc.)

        Args:
            ast_root: Universal AST root node

        Returns:
            List of magic number issues
        """
        issues = []

        # Find all literal nodes (numbers, strings, booleans)
        literals = ast_root.find_nodes(ASTNodeType.LITERAL)

        for literal in literals:
            value = literal.value
            line_number = literal.location.start_line if literal.location else 0

            # Check numeric literals
            if isinstance(value, (int, float)):
                if value not in ACCEPTABLE_NUMBERS:
                    issues.append(
                        CleaningIssue(
                            issue_type=CleaningIssueType.MAGIC_NUMBER,
                            description=f"Magic number '{value}' should be a named constant",
                            line_number=line_number,
                            severity=CleaningIssueSeverity.MEDIUM,
                        )
                    )

            # Check string literals (only flag long config-like strings)
            elif isinstance(value, str) and (len(value) > 10 and
                value not in ACCEPTABLE_STRINGS and
                self._looks_like_config_value(value)):
                issues.append(
                    CleaningIssue(
                        issue_type=CleaningIssueType.MAGIC_NUMBER,
                        description=f"Magic string '{value[:30]}...' should be a named constant",
                        line_number=line_number,
                        severity=CleaningIssueSeverity.INFO,
                    )
                )

        return issues

    def _looks_like_config_value(self, value: str) -> bool:
        """
        Check if a string looks like it should be a config constant.

        Args:
            value: String value to check

        Returns:
            True if it looks like a hardcoded config value
        """
        # File paths
        if '/' in value and len(value) > 15:
            return True
        # URLs
        if value.startswith(('http://', 'https://', 'ftp://')):
            return True
        # Connection strings
        if any(x in value.lower() for x in ['host=', 'port=', 'user=', 'password=']):
            return True
        # Email patterns
        return bool('@' in value and '.' in value)

    def _create_suggestion(self, issue: CleaningIssue, code: str) -> CleaningSuggestion:
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

        return CleaningSuggestion(
            issue=issue,
            suggestion=suggestion,
            rationale=rationale,
            example_code=example_code,
        )
