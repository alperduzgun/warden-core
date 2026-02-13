"""
Code Simplifier Analyzer

Detects opportunities to simplify code and improve elegance:
- Nested logic that could use guard clauses
- Redundant variables (used only once)
- Complex boolean expressions
- Opportunities to use modern language features
- Redundant else blocks after return

Universal multi-language support via tree-sitter AST (uses BaseCleaningAnalyzer helpers).
"""

import re
from typing import Any

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

# Thresholds
MAX_NESTING_FOR_GUARD_CLAUSE = 2  # Suggest guard clauses if nesting > 2
MAX_BOOLEAN_CONDITIONS = 3  # Suggest extraction if > 3 conditions


class CodeSimplifierAnalyzer(BaseCleaningAnalyzer):
    """
    Analyzer for detecting code simplification opportunities.

    Focuses on elegance, clarity, and modernization:
    - Nested logic that could use guard clauses
    - Redundant variables
    - Complex boolean expressions
    - Opportunities for modern language features
    - Redundant else blocks

    Universal multi-language support via tree-sitter AST.
    """

    @property
    def name(self) -> str:
        """Analyzer name."""
        return "Code Simplifier"

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
        Analyze code for simplification opportunities using Universal AST.

        Args:
            code_file: The code file to analyze
            cancellation_token: Optional cancellation token
            ast_tree: Optional pre-parsed Universal AST tree

        Returns:
            CleaningResult with simplification opportunities
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
                # No AST provider available or parsing failed
                return CleaningResult(
                    success=True,
                    file_path=code_file.path,
                    issues_found=0,
                    suggestions=[],
                    cleanup_score=100.0,
                    summary="AST parsing not available for this language",
                    analyzer_name=self.name,
                )

            # Analyze for simplification opportunities
            issues = self._analyze_simplification_universal(ast_root, code_file.content)

            if not issues:
                return CleaningResult(
                    success=True,
                    file_path=code_file.path,
                    issues_found=0,
                    suggestions=[],
                    cleanup_score=100.0,
                    summary="No simplification opportunities found - code is elegant!",
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
                summary=f"Found {len(issues)} simplification opportunities",
                analyzer_name=self.name,
                metrics={
                    "guard_clause_opportunities": sum(
                        1 for i in issues if "guard clause" in i.description.lower()
                    ),
                    "redundant_else": sum(
                        1 for i in issues if "redundant else" in i.description.lower()
                    ),
                    "complex_boolean": sum(
                        1 for i in issues if "boolean" in i.description.lower()
                    ),
                    "modernization": sum(
                        1 for i in issues if "modern" in i.description.lower()
                    ),
                },
            )

        except Exception as e:
            logger.error(
                "code_simplifier_analysis_failed",
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

    def _analyze_simplification_universal(
        self, ast_root: ASTNode, code: str
    ) -> list[CleaningIssue]:
        """
        Analyze code for simplification opportunities using Universal AST.

        Args:
            ast_root: Universal AST root node
            code: Source code to analyze

        Returns:
            List of simplification issues
        """
        issues = []
        lines = code.split("\n")

        # Use base class helper to find all functions/methods
        all_callables = self._get_functions_and_methods(ast_root)

        # Analyze each callable
        for func_node in all_callables:
            issues.extend(self._check_guard_clause_opportunities(func_node))
            issues.extend(self._check_redundant_else_after_return(func_node))
            issues.extend(self._check_complex_boolean_expressions(func_node))

        # Python-specific modernization checks
        if (code and "python" in code.lower()) or any("def " in line for line in lines[:10]):
            issues.extend(self._check_python_modernization(code, lines))

        return issues

    def _check_guard_clause_opportunities(self, node: ASTNode) -> list[CleaningIssue]:
        """
        Check for nested if-statements that could use guard clauses.

        Args:
            node: Universal AST function/method node

        Returns:
            List of guard clause opportunity issues
        """
        issues = []
        func_name = node.name or "<anonymous>"

        # Calculate nesting depth
        max_depth = self._calculate_nesting_depth_universal(node)

        if max_depth > MAX_NESTING_FOR_GUARD_CLAUSE:
            line_number = node.location.start_line if node.location else 0
            issues.append(
                CleaningIssue(
                    issue_type=CleaningIssueType.COMPLEX_METHOD,
                    description=f"Function '{func_name}' has deep nesting (depth {max_depth}) - consider using guard clauses",
                    line_number=line_number,
                    severity=CleaningIssueSeverity.MEDIUM,
                )
            )

        return issues

    def _check_redundant_else_after_return(self, node: ASTNode) -> list[CleaningIssue]:
        """
        Check for redundant else blocks after return/continue/break.

        Args:
            node: Universal AST function/method node

        Returns:
            List of redundant else issues
        """
        issues = []

        def find_redundant_else(node: ASTNode) -> None:
            """Recursively find redundant else blocks."""
            if node.node_type == ASTNodeType.IF_STATEMENT:
                # Check if the if block ends with return/break/continue
                has_early_exit = self._block_has_early_exit(node)

                # Check if there's an else clause
                has_else = any(
                    child for child in node.children
                    if hasattr(child, 'node_type') and 'else' in str(child.node_type).lower()
                )

                if has_early_exit and has_else:
                    line_number = node.location.start_line if node.location else 0
                    issues.append(
                        CleaningIssue(
                            issue_type=CleaningIssueType.DESIGN_SMELL,
                            description="Redundant else block after early return - flatten the code",
                            line_number=line_number,
                            severity=CleaningIssueSeverity.LOW,
                        )
                    )

            # Recursively check children
            for child in node.children:
                find_redundant_else(child)

        find_redundant_else(node)
        return issues

    def _block_has_early_exit(self, node: ASTNode) -> bool:
        """
        Check if a block ends with return/break/continue.

        Args:
            node: AST node to check

        Returns:
            True if block has early exit
        """
        # Check node attributes for return/break/continue indicators
        if hasattr(node, 'node_type'):
            node_type_str = str(node.node_type).lower()
            if any(keyword in node_type_str for keyword in ['return', 'break', 'continue']):
                return True

        # Check children recursively
        return any(self._block_has_early_exit(child) for child in node.children)

    def _check_complex_boolean_expressions(self, node: ASTNode) -> list[CleaningIssue]:
        """
        Check for complex boolean expressions that could be simplified.

        Args:
            node: Universal AST function/method node

        Returns:
            List of complex boolean issues
        """
        issues = []

        def count_boolean_operators(node: ASTNode) -> int:
            """Count boolean operators in an expression."""
            count = 0

            if node.node_type == ASTNodeType.BINARY_EXPRESSION:
                operator = node.attributes.get("operator", "")
                if operator in ("&&", "||", "and", "or"):
                    count += 1

            for child in node.children:
                count += count_boolean_operators(child)

            return count

        def find_complex_booleans(node: ASTNode) -> None:
            """Recursively find complex boolean expressions."""
            if node.node_type == ASTNodeType.IF_STATEMENT:
                # Count boolean operators in condition
                bool_count = count_boolean_operators(node)

                if bool_count > MAX_BOOLEAN_CONDITIONS:
                    line_number = node.location.start_line if node.location else 0
                    issues.append(
                        CleaningIssue(
                            issue_type=CleaningIssueType.COMPLEX_METHOD,
                            description=f"Complex boolean expression with {bool_count} operators - extract to named function",
                            line_number=line_number,
                            severity=CleaningIssueSeverity.MEDIUM,
                        )
                    )

            for child in node.children:
                find_complex_booleans(child)

        find_complex_booleans(node)
        return issues

    def _check_python_modernization(
        self, code: str, lines: list[str]
    ) -> list[CleaningIssue]:
        """
        Check for Python modernization opportunities.

        Args:
            code: Full source code
            lines: Source code lines

        Returns:
            List of modernization issues
        """
        issues = []

        # Check for old-style string formatting
        for i, line in enumerate(lines):
            line_stripped = line.strip()

            # Check for % formatting
            if re.search(r'["\'].*%[sd].*["\'].*%', line_stripped):
                issues.append(
                    CleaningIssue(
                        issue_type=CleaningIssueType.DESIGN_SMELL,
                        description="Old-style % formatting - consider using f-strings",
                        line_number=i + 1,
                        severity=CleaningIssueSeverity.LOW,
                    )
                )

            # Check for .format() that could be f-string
            if ".format(" in line_stripped and not line_stripped.strip().startswith("#"):
                issues.append(
                    CleaningIssue(
                        issue_type=CleaningIssueType.DESIGN_SMELL,
                        description="Consider using f-strings instead of .format()",
                        line_number=i + 1,
                        severity=CleaningIssueSeverity.INFO,
                    )
                )

            # Check for manual list building that could be comprehension
            if re.search(r'for\s+\w+\s+in.*:\s*$', line_stripped):
                # Look ahead for append pattern
                if i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    if ".append(" in next_line and len(next_line.split()) < 10:
                        issues.append(
                            CleaningIssue(
                                issue_type=CleaningIssueType.DESIGN_SMELL,
                                description="Consider using list comprehension for clarity",
                                line_number=i + 1,
                                severity=CleaningIssueSeverity.INFO,
                            )
                        )

        return issues

    def _create_suggestion(self, issue: CleaningIssue, code: str) -> CleaningSuggestion:
        """Create a cleanup suggestion from an issue."""
        # Extract code snippet
        code_snippet = self._get_code_snippet(code, issue.line_number, context=3)
        issue.code_snippet = code_snippet

        if "guard clause" in issue.description.lower():
            suggestion = "Use guard clauses to reduce nesting and improve readability"
            rationale = "Guard clauses (early returns) flatten code structure, making it easier to understand the happy path"
            example_code = """# Instead of:
def process(item):
    if item is not None:
        if item.is_valid():
            return process_item(item)
    return None

# Use guard clauses:
def process(item):
    if item is None:
        return None
    if not item.is_valid():
        return None
    return process_item(item)"""

        elif "redundant else" in issue.description.lower():
            suggestion = "Remove redundant else block after return - the code after the if will execute anyway"
            rationale = "Else blocks after returns add unnecessary nesting and reduce readability"
            example_code = """# Instead of:
if condition:
    return value
else:
    do_something()

# Simply write:
if condition:
    return value
do_something()"""

        elif "boolean" in issue.description.lower():
            suggestion = "Extract complex boolean expression to a named function"
            rationale = "Named boolean functions document intent and make conditions self-explanatory"
            example_code = """# Instead of:
if user.age > 18 and user.verified and not user.banned:
    grant_access()

# Extract to named function:
def can_access(user):
    return user.age > 18 and user.verified and not user.banned

if can_access(user):
    grant_access()"""

        elif "f-string" in issue.description.lower():
            suggestion = "Use f-strings for cleaner and more readable string formatting"
            rationale = "F-strings are faster, more readable, and the modern Python standard"
            example_code = """# Instead of:
message = "Hello %s, you have %d points" % (name, points)

# Use f-strings:
message = f"Hello {name}, you have {points} points" """

        elif "comprehension" in issue.description.lower():
            suggestion = "Use list comprehension for more Pythonic and readable code"
            rationale = "List comprehensions are more concise and often faster than explicit loops"
            example_code = """# Instead of:
result = []
for item in items:
    result.append(item.value)

# Use comprehension:
result = [item.value for item in items]"""

        else:
            suggestion = "Simplify this code to improve elegance and maintainability"
            rationale = "Simpler code is easier to understand, test, and maintain"
            example_code = "# Extract complex logic into well-named functions"

        return CleaningSuggestion(
            issue=issue,
            suggestion=suggestion,
            rationale=rationale,
            example_code=example_code,
        )
