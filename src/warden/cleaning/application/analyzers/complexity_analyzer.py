"""
Complexity Analyzer

Detects complex and long methods:
- Functions with too many lines
- Functions with high cyclomatic complexity
- Deeply nested code
- Too many parameters

Universal multi-language support via tree-sitter AST (uses BaseCleaningAnalyzer helpers).
"""

from typing import Any, List, Optional

import structlog

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

# Thresholds for complexity analysis
MAX_FUNCTION_LINES = 50
MAX_PARAMETERS = 5
MAX_NESTING_DEPTH = 4
MAX_CYCLOMATIC_COMPLEXITY = 10


class ComplexityAnalyzer(BaseCleaningAnalyzer):
    """
    Analyzer for detecting code complexity issues.

    Checks:
    - Long functions (> 50 lines)
    - Functions with too many parameters (> 5)
    - Deeply nested code (> 4 levels)
    - High cyclomatic complexity

    Universal multi-language support via tree-sitter AST.
    Uses BaseCleaningAnalyzer helper methods for AST operations.
    """

    @property
    def name(self) -> str:
        """Analyzer name."""
        return "Complexity Analyzer"

    @property
    def priority(self) -> int:
        """Execution priority."""
        return CleaningAnalyzerPriority.HIGH

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
        Analyze code for complexity issues using Universal AST.

        Args:
            code_file: The code file to analyze
            cancellation_token: Optional cancellation token
            ast_tree: Optional pre-parsed Universal AST tree

        Returns:
            CleaningResult with complexity issues
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
            # Use base class helper to get AST root (handles all parsing)
            ast_root = await self._get_ast_root(code_file, ast_tree)

            if not ast_root:
                # No AST provider available or parsing failed (already logged by base class)
                return CleaningResult(
                    success=True,
                    file_path=code_file.path,
                    issues_found=0,
                    suggestions=[],
                    cleanup_score=100.0,
                    summary="AST parsing not available for this language",
                    analyzer_name=self.name,
                )

            # Analyze complexity using Universal AST
            issues = self._analyze_complexity_universal(ast_root, code_file.content)

            if not issues:
                return CleaningResult(
                    success=True,
                    file_path=code_file.path,
                    issues_found=0,
                    suggestions=[],
                    cleanup_score=100.0,
                    summary="No complexity issues found",
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
                summary=f"Found {len(issues)} complexity issues",
                analyzer_name=self.name,
                metrics={
                    "long_methods": sum(1 for i in issues if i.issue_type == CleaningIssueType.LONG_METHOD),
                    "complex_methods": sum(1 for i in issues if i.issue_type == CleaningIssueType.COMPLEX_METHOD),
                },
            )

        except Exception as e:
            logger.error(
                "complexity_analysis_failed",
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

    def _analyze_complexity_universal(self, ast_root: ASTNode, code: str) -> list[CleaningIssue]:
        """
        Analyze code for complexity issues using Universal AST.

        Args:
            ast_root: Universal AST root node
            code: Source code to analyze

        Returns:
            List of complexity issues
        """
        issues = []
        lines = code.split("\n")

        # Use base class helper to find all functions/methods
        all_callables = self._get_functions_and_methods(ast_root)

        # Analyze each callable
        for func_node in all_callables:
            issues.extend(self._check_function_complexity_universal(func_node, lines))

        return issues

    def _check_function_complexity_universal(
        self,
        node: ASTNode,
        lines: list[str]
    ) -> list[CleaningIssue]:
        """
        Check a function for complexity issues using Universal AST.

        Uses base class helper methods for calculations.

        Args:
            node: Universal AST function/method node
            lines: Source code lines

        Returns:
            List of complexity issues
        """
        issues = []
        func_name = node.name or "<anonymous>"

        # Get line number from location
        line_number = node.location.start_line if node.location else 0

        # Check function length (use base class helper)
        func_lines = self._count_function_lines_universal(node, lines)
        if func_lines > MAX_FUNCTION_LINES:
            issues.append(
                CleaningIssue(
                    issue_type=CleaningIssueType.LONG_METHOD,
                    description=f"Function '{func_name}' is too long ({func_lines} lines, max {MAX_FUNCTION_LINES})",
                    line_number=line_number,
                    severity=CleaningIssueSeverity.HIGH,
                )
            )

        # Check parameter count (use base class helper)
        param_count = self._count_parameters_universal(node)
        if param_count > MAX_PARAMETERS:
            issues.append(
                CleaningIssue(
                    issue_type=CleaningIssueType.COMPLEX_METHOD,
                    description=f"Function '{func_name}' has too many parameters ({param_count}, max {MAX_PARAMETERS})",
                    line_number=line_number,
                    severity=CleaningIssueSeverity.MEDIUM,
                )
            )

        # Check nesting depth (use base class helper)
        max_depth = self._calculate_nesting_depth_universal(node)
        if max_depth > MAX_NESTING_DEPTH:
            issues.append(
                CleaningIssue(
                    issue_type=CleaningIssueType.COMPLEX_METHOD,
                    description=f"Function '{func_name}' has deep nesting (depth {max_depth}, max {MAX_NESTING_DEPTH})",
                    line_number=line_number,
                    severity=CleaningIssueSeverity.HIGH,
                )
            )

        # Check cyclomatic complexity (use base class helper)
        complexity = self._calculate_cyclomatic_complexity_universal(node)
        if complexity > MAX_CYCLOMATIC_COMPLEXITY:
            issues.append(
                CleaningIssue(
                    issue_type=CleaningIssueType.COMPLEX_METHOD,
                    description=f"Function '{func_name}' has high cyclomatic complexity ({complexity}, max {MAX_CYCLOMATIC_COMPLEXITY})",
                    line_number=line_number,
                    severity=CleaningIssueSeverity.HIGH,
                )
            )

        return issues

    def _create_suggestion(self, issue: CleaningIssue, code: str) -> CleaningSuggestion:
        """Create a cleanup suggestion from an issue."""
        # Extract code snippet
        code_snippet = self._get_code_snippet(code, issue.line_number, context=3)
        issue.code_snippet = code_snippet

        if issue.issue_type == CleaningIssueType.LONG_METHOD:
            suggestion = "Break this long function into smaller, focused functions"
            rationale = "Long functions are harder to understand, test, and maintain. Extract logical blocks into separate functions."
            example_code = "# Break into smaller functions:\ndef main_function():\n    result1 = process_step_1()\n    result2 = process_step_2(result1)\n    return finalize(result2)"
        elif "parameters" in issue.description:
            suggestion = "Reduce the number of parameters by grouping related ones into a data class or dictionary"
            rationale = "Too many parameters make functions hard to use and test. Consider using a configuration object."
            example_code = "# Use dataclass or dict:\n@dataclass\nclass Config:\n    param1: str\n    param2: int\n\ndef function(config: Config):\n    ..."
        elif "nesting" in issue.description:
            suggestion = "Reduce nesting by extracting nested blocks into separate functions or using early returns"
            rationale = "Deep nesting makes code hard to read. Use guard clauses and extract complex logic."
            example_code = "# Use early returns:\nif not valid:\n    return\n# Continue with main logic"
        else:
            suggestion = "Simplify this function by reducing conditional logic and extracting complex conditions"
            rationale = "High cyclomatic complexity makes code hard to test and understand. Simplify conditions and extract logic."
            example_code = "# Extract complex conditions:\ndef is_valid(item):\n    return condition1 and condition2\n\nif is_valid(item):\n    ..."

        return CleaningSuggestion(
            issue=issue,
            suggestion=suggestion,
            rationale=rationale,
            example_code=example_code,
        )
