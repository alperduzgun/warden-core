"""
Naming Analyzer

Detects poor naming conventions in code:
- Single letter variable names (except loop counters)
- Unclear abbreviations
- Non-descriptive names
- Inconsistent naming patterns
"""

import ast
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
    """

    @property
    def name(self) -> str:
        """Analyzer name."""
        return "Naming Analyzer"

    @property
    def priority(self) -> int:
        """Execution priority."""
        return CleaningAnalyzerPriority.CRITICAL

    async def analyze_async(
        self,
        code_file: CodeFile,
        cancellation_token: Optional[str] = None,
        ast_tree: Optional[Any] = None,
    ) -> CleaningResult:
        """
        Analyze code for naming issues.

        Args:
            code_file: The code file to analyze
            cancellation_token: Optional cancellation token

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
            issues = self._analyze_naming(code_file.content, ast_tree)

            if not issues:
                logger.info(
                    "no_naming_issues",
                    file_path=code_file.path,
                    analyzer=self.name,
                )
                return CleaningResult(
                    success=True,
                    file_path=code_file.path,
                    issues_found=0,
                    suggestions=[],
                    cleanup_score=100.0,
                    summary="No naming issues found - code has good naming conventions",
                    analyzer_name=self.name,
                )

            logger.info(
                "naming_issues_found",
                count=len(issues),
                file_path=code_file.path,
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

    def _analyze_naming(self, code: str, ast_tree: Optional[Any] = None) -> List[CleaningIssue]:
        """
        Analyze code for naming issues using AST.

        Args:
            code: Source code to analyze
            ast_tree: Optional pre-parsed AST

        Returns:
            List of naming issues
        """
        issues = []

        try:
            tree = ast_tree if ast_tree else ast.parse(code)
        except SyntaxError as e:
            logger.warning("syntax_error_in_code", error=str(e))
            return issues

        # Analyze all names in the AST
        for node in ast.walk(tree):
            # Check function names
            if isinstance(node, ast.FunctionDef):
                issues.extend(self._check_function_name(node))

            # Check class names
            elif isinstance(node, ast.ClassDef):
                issues.extend(self._check_class_name(node))

            # Check variable assignments
            elif isinstance(node, ast.Assign):
                issues.extend(self._check_variable_assignment(node))

            # Check function arguments
            elif isinstance(node, ast.arg):
                issues.extend(self._check_argument_name(node))

        return issues

    def _check_function_name(self, node: ast.FunctionDef) -> List[CleaningIssue]:
        """Check function name for issues."""
        issues = []
        name = node.name

        # Skip magic methods
        if name.startswith("__") and name.endswith("__"):
            return issues

        # Check for single letter (except common ones)
        if len(name) == 1 and name not in ACCEPTABLE_SINGLE_LETTERS:
            issues.append(
                CleaningIssue(
                    issue_type=CleaningIssueType.POOR_NAMING,
                    description=f"Function '{name}' has single letter name",
                    line_number=node.lineno,
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
                        line_number=node.lineno,
                        severity=CleaningIssueSeverity.MEDIUM,
                    )
                )

        # Check for non-descriptive names
        if name.lower() in ['process', 'handle', 'do', 'execute', 'run', 'go']:
            issues.append(
                CleaningIssue(
                    issue_type=CleaningIssueType.POOR_NAMING,
                    description=f"Function '{name}' has non-descriptive name",
                    line_number=node.lineno,
                    severity=CleaningIssueSeverity.MEDIUM,
                )
            )

        return issues

    def _check_class_name(self, node: ast.ClassDef) -> List[CleaningIssue]:
        """Check class name for issues."""
        issues = []
        name = node.name

        # Check if class name follows PascalCase
        if not re.match(r'^[A-Z][a-zA-Z0-9]*$', name):
            issues.append(
                CleaningIssue(
                    issue_type=CleaningIssueType.POOR_NAMING,
                    description=f"Class '{name}' should use PascalCase naming",
                    line_number=node.lineno,
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
                        line_number=node.lineno,
                        severity=CleaningIssueSeverity.MEDIUM,
                    )
                )

        return issues

    def _check_variable_assignment(self, node: ast.Assign) -> List[CleaningIssue]:
        """Check variable names in assignments."""
        issues = []

        for target in node.targets:
            if isinstance(target, ast.Name):
                name = target.id

                # Skip private variables
                if name.startswith("_"):
                    continue

                # Check for single letter (except common ones)
                if len(name) == 1 and name not in ACCEPTABLE_SINGLE_LETTERS:
                    issues.append(
                        CleaningIssue(
                            issue_type=CleaningIssueType.POOR_NAMING,
                            description=f"Variable '{name}' has single letter name",
                            line_number=node.lineno,
                            severity=CleaningIssueSeverity.MEDIUM,
                        )
                    )

                # Check for non-descriptive names
                if name.lower() in ['data', 'item', 'thing', 'stuff', 'value', 'result']:
                    issues.append(
                        CleaningIssue(
                            issue_type=CleaningIssueType.POOR_NAMING,
                            description=f"Variable '{name}' has non-descriptive name",
                            line_number=node.lineno,
                            severity=CleaningIssueSeverity.LOW,
                        )
                    )

        return issues

    def _check_argument_name(self, node: ast.arg) -> List[CleaningIssue]:
        """Check function argument names."""
        issues = []
        name = node.arg

        # Skip self and cls
        if name in ['self', 'cls']:
            return issues

        # Check for single letter (except common ones)
        if len(name) == 1 and name not in ACCEPTABLE_SINGLE_LETTERS:
            issues.append(
                CleaningIssue(
                    issue_type=CleaningIssueType.POOR_NAMING,
                    description=f"Argument '{name}' has single letter name",
                    line_number=node.lineno,
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
