"""
Complexity Analyzer

Detects complex and long methods:
- Functions with too many lines
- Functions with high cyclomatic complexity
- Deeply nested code
- Too many parameters
"""

import ast
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
    """

    @property
    def name(self) -> str:
        """Analyzer name."""
        return "Complexity Analyzer"

    @property
    def priority(self) -> int:
        """Execution priority."""
        return CleaningAnalyzerPriority.HIGH

    async def analyze_async(
        self,
        code_file: CodeFile,
        cancellation_token: Optional[str] = None,
        ast_tree: Optional[Any] = None,
    ) -> CleaningResult:
        """
        Analyze code for complexity issues.

        Args:
            code_file: The code file to analyze
            cancellation_token: Optional cancellation token

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
            issues = self._analyze_complexity(code_file.content, ast_tree)

            if not issues:
                logger.info(
                    "no_complexity_issues",
                    file_path=code_file.path,
                    analyzer=self.name,
                )
                return CleaningResult(
                    success=True,
                    file_path=code_file.path,
                    issues_found=0,
                    suggestions=[],
                    cleanup_score=100.0,
                    summary="No complexity issues found",
                    analyzer_name=self.name,
                )

            logger.info(
                "complexity_issues_found",
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

    def _analyze_complexity(self, code: str, ast_tree: Optional[Any] = None) -> List[CleaningIssue]:
        """
        Analyze code for complexity issues using AST.

        Args:
            code: Source code to analyze
            ast_tree: Optional pre-parsed AST

        Returns:
            List of complexity issues
        """
        issues = []

        try:
            tree = ast_tree if ast_tree else ast.parse(code)
        except SyntaxError as e:
            logger.warning("syntax_error_in_code", error=str(e))
            return issues

        # Analyze all function definitions
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                issues.extend(self._check_function_complexity(node, code))

        return issues

    def _check_function_complexity(
        self,
        node: ast.FunctionDef,
        code: str
    ) -> List[CleaningIssue]:
        """
        Check a function for complexity issues.

        Args:
            node: Function definition AST node
            code: Source code

        Returns:
            List of complexity issues
        """
        issues = []
        func_name = node.name

        # Check function length
        func_lines = self._count_function_lines(node, code)
        if func_lines > MAX_FUNCTION_LINES:
            issues.append(
                CleaningIssue(
                    issue_type=CleaningIssueType.LONG_METHOD,
                    description=f"Function '{func_name}' is too long ({func_lines} lines, max {MAX_FUNCTION_LINES})",
                    line_number=node.lineno,
                    severity=CleaningIssueSeverity.HIGH,
                )
            )

        # Check parameter count
        param_count = len(node.args.args)
        if param_count > MAX_PARAMETERS:
            issues.append(
                CleaningIssue(
                    issue_type=CleaningIssueType.COMPLEX_METHOD,
                    description=f"Function '{func_name}' has too many parameters ({param_count}, max {MAX_PARAMETERS})",
                    line_number=node.lineno,
                    severity=CleaningIssueSeverity.MEDIUM,
                )
            )

        # Check nesting depth
        max_depth = self._calculate_nesting_depth(node)
        if max_depth > MAX_NESTING_DEPTH:
            issues.append(
                CleaningIssue(
                    issue_type=CleaningIssueType.COMPLEX_METHOD,
                    description=f"Function '{func_name}' has deep nesting (depth {max_depth}, max {MAX_NESTING_DEPTH})",
                    line_number=node.lineno,
                    severity=CleaningIssueSeverity.HIGH,
                )
            )

        # Check cyclomatic complexity
        complexity = self._calculate_cyclomatic_complexity(node)
        if complexity > MAX_CYCLOMATIC_COMPLEXITY:
            issues.append(
                CleaningIssue(
                    issue_type=CleaningIssueType.COMPLEX_METHOD,
                    description=f"Function '{func_name}' has high cyclomatic complexity ({complexity}, max {MAX_CYCLOMATIC_COMPLEXITY})",
                    line_number=node.lineno,
                    severity=CleaningIssueSeverity.HIGH,
                )
            )

        return issues

    def _count_function_lines(self, node: ast.FunctionDef, code: str) -> int:
        """
        Count non-empty lines in a function.

        Args:
            node: Function definition AST node
            code: Source code

        Returns:
            Number of non-empty lines
        """
        lines = code.split("\n")
        start_line = node.lineno - 1

        # Find end line by looking at the body
        if node.body:
            end_line = max(
                getattr(child, 'end_lineno', node.lineno)
                for child in ast.walk(node)
                if hasattr(child, 'lineno')
            )
        else:
            end_line = node.lineno

        # Count non-empty, non-comment lines
        count = 0
        for i in range(start_line, min(end_line, len(lines))):
            line = lines[i].strip()
            if line and not line.startswith("#"):
                count += 1

        return count

    def _calculate_nesting_depth(self, node: ast.FunctionDef) -> int:
        """
        Calculate maximum nesting depth in a function.

        Args:
            node: Function definition AST node

        Returns:
            Maximum nesting depth
        """
        def get_depth(node: ast.AST, current_depth: int = 0) -> int:
            """Recursively calculate depth."""
            max_depth = current_depth

            for child in ast.iter_child_nodes(node):
                # Increase depth for control structures
                if isinstance(child, (ast.If, ast.For, ast.While, ast.With, ast.Try)):
                    child_depth = get_depth(child, current_depth + 1)
                    max_depth = max(max_depth, child_depth)
                else:
                    child_depth = get_depth(child, current_depth)
                    max_depth = max(max_depth, child_depth)

            return max_depth

        return get_depth(node, 0)

    def _calculate_cyclomatic_complexity(self, node: ast.FunctionDef) -> int:
        """
        Calculate cyclomatic complexity of a function.

        Cyclomatic complexity = number of decision points + 1

        Args:
            node: Function definition AST node

        Returns:
            Cyclomatic complexity
        """
        complexity = 1  # Base complexity

        for child in ast.walk(node):
            # Count decision points
            if isinstance(child, (ast.If, ast.While, ast.For)):
                complexity += 1
            elif isinstance(child, ast.BoolOp):
                # Each 'and' or 'or' adds complexity
                complexity += len(child.values) - 1
            elif isinstance(child, ast.ExceptHandler):
                complexity += 1
            elif isinstance(child, ast.comprehension):
                # List/dict comprehensions with conditions
                complexity += len(child.ifs)

        return complexity

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
