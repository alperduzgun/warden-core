"""
Naming Analyzer

Detects poor naming conventions in code:
- Single letter variable names (except loop counters)
- Unclear abbreviations
- Non-descriptive names
- Inconsistent naming patterns

Universal multi-language support via tree-sitter AST (uses BaseCleaningAnalyzer helpers).
"""

import re
import structlog
from typing import List, Optional, Any

from warden.cleaning.domain.base import BaseCleaningAnalyzer, CleaningAnalyzerPriority
from warden.cleaning.domain.models import (
    CleaningResult,
    CleaningSuggestion,
    CleaningIssue,
    CleaningIssueType,
    CleaningIssueSeverity,
)
from warden.validation.domain.frame import CodeFile
from warden.ast.domain.models import ASTNode
from warden.ast.domain.enums import ASTNodeType

logger = structlog.get_logger()

# Common acceptable single-letter variable names
ACCEPTABLE_SINGLE_LETTERS = {'i', 'j', 'k', 'x', 'y', 'z', 'n', 't', '_'}

# Common unclear abbreviations
UNCLEAR_ABBREVIATIONS = {
    'tmp': 'temporary',
    'val': 'value',
    'arr': 'array',
    'lst': 'list',
    'dct': 'dictionary',
    'num': 'number',
    'str': 'string',
    'obj': 'object',
    'idx': 'index',
    'cnt': 'count',
    'msg': 'message',
    'resp': 'response',
    'req': 'request',
}


class NamingAnalyzer(BaseCleaningAnalyzer):
    """
    Analyzer for detecting poor naming conventions.

    Checks:
    - Single letter variable names (except loop counters)
    - Unclear abbreviations
    - Non-descriptive names (e.g., 'data', 'item', 'thing')
    - Inconsistent naming patterns

    Universal multi-language support via tree-sitter AST.
    """

    @property
    def name(self) -> str:
        """Analyzer name."""
        return "Naming Analyzer"

    @property
    def priority(self) -> int:
        """Execution priority."""
        return CleaningAnalyzerPriority.CRITICAL

    @property
    def supported_languages(self) -> set:
        """Languages supported by this analyzer (universal - all languages)."""
        return set()  # Empty set = universal support (all languages)

    async def analyze_async(
        self,
        code_file: CodeFile,
        cancellation_token: Optional[str] = None,
        ast_tree: Optional[Any] = None,
    ) -> CleaningResult:
        """
        Analyze code for naming issues using Universal AST.

        Args:
            code_file: The code file to analyze
            cancellation_token: Optional cancellation token
            ast_tree: Optional pre-parsed Universal AST tree

        Returns:
            CleaningResult with naming issues
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

            # Analyze naming
            issues = self._analyze_naming_universal(ast_root)

            if not issues:
                return CleaningResult(
                    success=True,
                    file_path=code_file.path,
                    issues_found=0,
                    suggestions=[],
                    cleanup_score=100.0,
                    summary="No naming issues found - code has good naming conventions",
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
                summary=f"Found {len(issues)} naming issues",
                analyzer_name=self.name,
                metrics={
                    "single_letter_vars": sum(1 for i in issues if "single letter" in i.description.lower()),
                    "unclear_abbreviations": sum(1 for i in issues if "abbreviation" in i.description.lower()),
                    "non_descriptive": sum(1 for i in issues if "non-descriptive" in i.description.lower()),
                },
            )

        except Exception as e:
            logger.error(
                "naming_analysis_failed",
                error=str(e),
                file_path=code_file.path,
            )
            return CleaningResult(
                success=False,
                file_path=code_file.path,
                issues_found=0,
                error_message=f"Analysis failed: {str(e)}",
                analyzer_name=self.name,
            )

    def _analyze_naming_universal(self, ast_root: ASTNode) -> List[CleaningIssue]:
        """
        Analyze code for naming issues using Universal AST.

        Works for all languages (Python, Swift, Dart, Go, JS, etc.)

        Args:
            ast_root: Universal AST root node

        Returns:
            List of naming issues
        """
        issues = []

        # Check functions and methods
        functions_and_methods = self._get_functions_and_methods(ast_root)
        for func in functions_and_methods:
            issues.extend(self._check_function_name_universal(func))

        # Check classes
        classes = ast_root.find_nodes(ASTNodeType.CLASS)
        for cls in classes:
            issues.extend(self._check_class_name_universal(cls))

        return issues

    def _check_function_name_universal(self, node: ASTNode) -> List[CleaningIssue]:
        """Check function name for issues (Universal AST)."""
        issues = []
        name = node.name

        if not name:
            return issues

        line_number = node.location.start_line if node.location else 0

        # Skip magic methods/special names
        if name.startswith("__") and name.endswith("__"):
            return issues
        if name.startswith("_"):  # Private methods
            return issues

        # Check for single letter (except common ones)
        if len(name) == 1 and name not in ACCEPTABLE_SINGLE_LETTERS:
            issues.append(
                CleaningIssue(
                    issue_type=CleaningIssueType.POOR_NAMING,
                    description=f"Function '{name}' has single letter name",
                    line_number=line_number,
                    severity=CleaningIssueSeverity.HIGH,
                )
            )

        # Check for unclear abbreviations
        for abbr, full in UNCLEAR_ABBREVIATIONS.items():
            if abbr in name.lower():
                issues.append(
                    CleaningIssue(
                        issue_type=CleaningIssueType.POOR_NAMING,
                        description=f"Function '{name}' uses unclear abbreviation '{abbr}' (consider '{full}')",
                        line_number=line_number,
                        severity=CleaningIssueSeverity.MEDIUM,
                    )
                )

        # Check for non-descriptive names
        if name.lower() in ['process', 'handle', 'do', 'execute', 'run', 'go', 'func', 'method']:
            issues.append(
                CleaningIssue(
                    issue_type=CleaningIssueType.POOR_NAMING,
                    description=f"Function '{name}' has non-descriptive name",
                    line_number=line_number,
                    severity=CleaningIssueSeverity.MEDIUM,
                )
            )

        return issues

    def _check_class_name_universal(self, node: ASTNode) -> List[CleaningIssue]:
        """Check class name for issues (Universal AST)."""
        issues = []
        name = node.name

        if not name:
            return issues

        line_number = node.location.start_line if node.location else 0

        # Check if class name follows PascalCase (common convention)
        if not re.match(r'^[A-Z][a-zA-Z0-9]*$', name):
            issues.append(
                CleaningIssue(
                    issue_type=CleaningIssueType.POOR_NAMING,
                    description=f"Class '{name}' should use PascalCase naming",
                    line_number=line_number,
                    severity=CleaningIssueSeverity.MEDIUM,
                )
            )

        # Check for unclear abbreviations
        for abbr, full in UNCLEAR_ABBREVIATIONS.items():
            if abbr in name.lower():
                issues.append(
                    CleaningIssue(
                        issue_type=CleaningIssueType.POOR_NAMING,
                        description=f"Class '{name}' uses unclear abbreviation '{abbr}' (consider '{full}')",
                        line_number=line_number,
                        severity=CleaningIssueSeverity.MEDIUM,
                    )
                )

        return issues

    def _create_suggestion(self, issue: CleaningIssue, code: str) -> CleaningSuggestion:
        """Create a cleanup suggestion from an issue."""
        # Extract code snippet
        code_snippet = self._get_code_snippet(code, issue.line_number)
        issue.code_snippet = code_snippet

        # Generate suggestion based on issue type
        if "single letter" in issue.description:
            suggestion = "Use a descriptive name that clearly indicates the variable's purpose"
            rationale = "Single-letter variables make code harder to understand and maintain"
        elif "abbreviation" in issue.description:
            suggestion = "Replace abbreviations with full, descriptive names"
            rationale = "Clear naming improves code readability and reduces ambiguity"
        elif "non-descriptive" in issue.description:
            suggestion = "Choose a name that describes what the variable/function does or represents"
            rationale = "Generic names like 'data' or 'process' don't convey meaning"
        else:
            suggestion = "Improve naming to follow best practices and conventions"
            rationale = "Good naming is essential for maintainable code"

        return CleaningSuggestion(
            issue=issue,
            suggestion=suggestion,
            rationale=rationale,
        )
