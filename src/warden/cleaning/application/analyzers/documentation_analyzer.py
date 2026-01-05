"""
Documentation Analyzer

Analyzes documentation quality and coverage:
- Docstring coverage for functions/classes
- Comment quality and density
- README completeness
- API documentation
- Self-documenting code patterns
"""

import ast
import re
import structlog
from typing import List, Optional, Dict, Any
from pathlib import Path

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


class DocumentationAnalyzer(BaseCleaningAnalyzer):
    """
    Analyzer for documentation quality and coverage.

    Checks:
    - Function/class docstring coverage
    - Docstring quality (Google/Sphinx/NumPy style)
    - Comment density and quality
    - Public API documentation
    - Self-documenting patterns
    """

    @property
    def name(self) -> str:
        """Analyzer name."""
        return "Documentation Analyzer"

    @property
    def priority(self) -> int:
        """Execution priority."""
        return CleaningAnalyzerPriority.MEDIUM

    async def analyze_async(
        self,
        code_file: CodeFile,
        cancellation_token: Optional[str] = None,
        ast_tree: Optional[Any] = None,
    ) -> CleaningResult:
        """
        Analyze documentation quality and coverage.

        Args:
            code_file: The code file to analyze
            cancellation_token: Optional cancellation token

        Returns:
            CleaningResult with documentation metrics
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
            # Analyze documentation
            coverage_stats = self._calculate_documentation_coverage(code_file.content, ast_tree)
            issues = self._analyze_documentation_quality(code_file.content, ast_tree)

            # Calculate quality score (0-10)
            coverage_percent = coverage_stats.get("overall_coverage", 0)
            quality_score = (coverage_percent / 100) * 10

            logger.info(
                "documentation_analysis_complete",
                file_path=code_file.path,
                coverage=coverage_percent,
                quality_score=quality_score,
                issues_found=len(issues),
            )

            # Convert issues to suggestions
            suggestions = [self._create_suggestion(issue, code_file.content) for issue in issues]

            # Calculate cleanup score
            total_lines = len(code_file.content.split("\n"))
            cleanup_score = self._calculate_cleanup_score(len(issues), total_lines)

            return CleaningResult(
                success=True,
                file_path=code_file.path,
                issues_found=len(issues),
                suggestions=suggestions,
                cleanup_score=cleanup_score,
                summary=f"Documentation coverage: {coverage_percent:.1f}%",
                analyzer_name=self.name,
                metrics={
                    "documentation_coverage": coverage_percent,
                    "quality_score": quality_score,
                    "functions_documented": coverage_stats.get("functions_documented", 0),
                    "classes_documented": coverage_stats.get("classes_documented", 0),
                    "comment_density": coverage_stats.get("comment_density", 0),
                },
            )

        except Exception as e:
            logger.error(
                "documentation_analysis_failed",
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

    def _calculate_documentation_coverage(self, code: str, ast_tree: Optional[Any] = None) -> Dict[str, Any]:
        """
        Calculate documentation coverage metrics.

        Args:
            code: Source code
            ast_tree: Optional pre-parsed AST

        Returns:
            Dictionary with coverage statistics
        """
        try:
            tree = ast_tree if ast_tree else ast.parse(code)
        except SyntaxError:
            return {"overall_coverage": 0}

        # Count entities
        total_functions = 0
        documented_functions = 0
        total_classes = 0
        documented_classes = 0
        total_public_methods = 0
        documented_public_methods = 0

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                # Skip private functions (start with _)
                if not node.name.startswith('_') or node.name.startswith('__'):
                    total_functions += 1
                    if ast.get_docstring(node):
                        documented_functions += 1

                # Count public methods in classes
                if self._is_method(node) and not node.name.startswith('_'):
                    total_public_methods += 1
                    if ast.get_docstring(node):
                        documented_public_methods += 1

            elif isinstance(node, ast.ClassDef):
                total_classes += 1
                if ast.get_docstring(node):
                    documented_classes += 1

        # Calculate comment density
        lines = code.split('\n')
        comment_lines = sum(1 for line in lines if line.strip().startswith('#'))
        total_lines = len([line for line in lines if line.strip()])
        comment_density = (comment_lines / total_lines * 100) if total_lines > 0 else 0

        # Calculate overall coverage
        total_entities = total_functions + total_classes + total_public_methods
        documented_entities = documented_functions + documented_classes + documented_public_methods
        overall_coverage = (documented_entities / total_entities * 100) if total_entities > 0 else 100

        return {
            "overall_coverage": overall_coverage,
            "functions_total": total_functions,
            "functions_documented": documented_functions,
            "classes_total": total_classes,
            "classes_documented": documented_classes,
            "public_methods_total": total_public_methods,
            "public_methods_documented": documented_public_methods,
            "comment_density": comment_density,
        }

    def _analyze_documentation_quality(self, code: str, ast_tree: Optional[Any] = None) -> List[CleaningIssue]:
        """
        Analyze documentation quality issues.

        Args:
            code: Source code
            ast_tree: Optional pre-parsed AST

        Returns:
            List of documentation issues
        """
        issues = []

        try:
            tree = ast_tree if ast_tree else ast.parse(code)
        except SyntaxError:
            return issues

        # Check for missing docstrings
        issues.extend(self._check_missing_docstrings(tree))

        # Check docstring quality
        issues.extend(self._check_docstring_quality(tree))

        # Check for outdated comments
        issues.extend(self._check_outdated_comments(code))

        # Check for unclear variable names
        issues.extend(self._check_unclear_names(tree))

        return issues

    def _check_missing_docstrings(self, tree: ast.AST) -> List[CleaningIssue]:
        """Check for missing docstrings in public functions/classes."""
        issues = []

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                # Check public functions and methods
                if not node.name.startswith('_') and not ast.get_docstring(node):
                    # Special case: __init__ should have docstring if it has complex parameters
                    if node.name == '__init__' and len(node.args.args) > 2:
                        issues.append(
                            CleaningIssue(
                                issue_type=CleaningIssueType.MISSING_DOC,
                                description=f"Constructor '{node.name}' with {len(node.args.args)} parameters needs docstring",
                                line_number=node.lineno,
                                severity=CleaningIssueSeverity.MEDIUM,
                            )
                        )
                    elif not node.name.startswith('__'):
                        issues.append(
                            CleaningIssue(
                                issue_type=CleaningIssueType.MISSING_DOC,
                                description=f"Public function '{node.name}' missing docstring",
                                line_number=node.lineno,
                                severity=CleaningIssueSeverity.MEDIUM,
                            )
                        )

            elif isinstance(node, ast.ClassDef):
                if not ast.get_docstring(node):
                    issues.append(
                        CleaningIssue(
                            issue_type=CleaningIssueType.MISSING_DOC,
                            description=f"Class '{node.name}' missing docstring",
                            line_number=node.lineno,
                            severity=CleaningIssueSeverity.MEDIUM,
                        )
                    )

        return issues

    def _check_docstring_quality(self, tree: ast.AST) -> List[CleaningIssue]:
        """Check quality of existing docstrings."""
        issues = []

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                docstring = ast.get_docstring(node)
                if docstring:
                    # Check for minimal docstrings
                    if len(docstring.split()) < 3:
                        issues.append(
                            CleaningIssue(
                                issue_type=CleaningIssueType.POOR_DOC,
                                description=f"Docstring for '{node.name}' is too brief",
                                line_number=node.lineno,
                                severity=CleaningIssueSeverity.LOW,
                            )
                        )

                    # Check for missing parameter documentation in functions
                    if isinstance(node, ast.FunctionDef) and node.args.args:
                        params = [arg.arg for arg in node.args.args if arg.arg != 'self']
                        if params:
                            # Check if parameters are documented (simple heuristic)
                            has_params_section = any(
                                keyword in docstring.lower()
                                for keyword in ['args:', 'arguments:', 'parameters:', 'params:']
                            )

                            if not has_params_section:
                                issues.append(
                                    CleaningIssue(
                                        issue_type=CleaningIssueType.POOR_DOC,
                                        description=f"Function '{node.name}' docstring missing parameter documentation",
                                        line_number=node.lineno,
                                        severity=CleaningIssueSeverity.LOW,
                                    )
                                )

                            # Check for return documentation if not None
                            if not self._returns_none(node):
                                has_return_doc = any(
                                    keyword in docstring.lower()
                                    for keyword in ['returns:', 'return:', 'yields:', 'yield:']
                                )
                                if not has_return_doc:
                                    issues.append(
                                        CleaningIssue(
                                            issue_type=CleaningIssueType.POOR_DOC,
                                            description=f"Function '{node.name}' docstring missing return value documentation",
                                            line_number=node.lineno,
                                            severity=CleaningIssueSeverity.LOW,
                                        )
                                    )

        return issues

    def _check_outdated_comments(self, code: str) -> List[CleaningIssue]:
        """Check for potentially outdated comments."""
        issues = []
        lines = code.split('\n')

        # Patterns that might indicate outdated comments
        outdated_patterns = [
            (r'#\s*TODO\s*[:]*\s*\d{4}', "Old TODO from {}", CleaningIssueSeverity.LOW),
            (r'#\s*FIXME\s*[:]*\s*\d{4}', "Old FIXME from {}", CleaningIssueSeverity.MEDIUM),
            (r'#\s*HACK', "HACK comment indicates technical debt", CleaningIssueSeverity.MEDIUM),
            (r'#\s*XXX', "XXX comment indicates problem", CleaningIssueSeverity.MEDIUM),
            (r'#\s*BUG', "BUG comment should be addressed", CleaningIssueSeverity.HIGH),
            (r'#\s*DEPRECATED', "Deprecated code should be removed", CleaningIssueSeverity.HIGH),
        ]

        for line_num, line in enumerate(lines, 1):
            for pattern, message, severity in outdated_patterns:
                if re.search(pattern, line):
                    issues.append(
                        CleaningIssue(
                            issue_type=CleaningIssueType.POOR_DOC,
                            description=message.format(re.search(r'\d{4}', line).group() if re.search(r'\d{4}', line) else ""),
                            line_number=line_num,
                            severity=severity,
                        )
                    )

        return issues

    def _check_unclear_names(self, tree: ast.AST) -> List[CleaningIssue]:
        """Check for unclear or non-descriptive names."""
        issues = []

        # Common unclear names
        unclear_names = {
            'data', 'info', 'temp', 'tmp', 'obj', 'val', 'var',
            'foo', 'bar', 'baz', 'test', 'thing', 'stuff',
            'a', 'b', 'c', 'd', 'e', 'x', 'y', 'z',
        }

        for node in ast.walk(tree):
            # Check function names
            if isinstance(node, ast.FunctionDef):
                if node.name.lower() in unclear_names or len(node.name) < 3:
                    issues.append(
                        CleaningIssue(
                            issue_type=CleaningIssueType.POOR_NAMING,
                            description=f"Function name '{node.name}' is not descriptive",
                            line_number=node.lineno,
                            severity=CleaningIssueSeverity.LOW,
                        )
                    )

            # Check class names
            elif isinstance(node, ast.ClassDef):
                if node.name.lower() in unclear_names or len(node.name) < 3:
                    issues.append(
                        CleaningIssue(
                            issue_type=CleaningIssueType.POOR_NAMING,
                            description=f"Class name '{node.name}' is not descriptive",
                            line_number=node.lineno,
                            severity=CleaningIssueSeverity.MEDIUM,
                        )
                    )

            # Check variable names (assignments)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        if target.id.lower() in unclear_names and not target.id.startswith('_'):
                            issues.append(
                                CleaningIssue(
                                    issue_type=CleaningIssueType.POOR_NAMING,
                                    description=f"Variable name '{target.id}' is not descriptive",
                                    line_number=node.lineno,
                                    severity=CleaningIssueSeverity.LOW,
                                )
                            )

        return issues

    def _is_method(self, node: ast.FunctionDef) -> bool:
        """Check if a function is a method (inside a class)."""
        # This is a simplified check - proper implementation would track parent nodes
        return len(node.args.args) > 0 and node.args.args[0].arg == 'self'

    def _returns_none(self, node: ast.FunctionDef) -> bool:
        """Check if function returns None or has no return statement."""
        for child in ast.walk(node):
            if isinstance(child, ast.Return):
                if child.value is not None:
                    return False
        return True

    def _create_suggestion(self, issue: CleaningIssue, code: str) -> CleaningSuggestion:
        """Create a cleanup suggestion from an issue."""
        # Extract code snippet
        code_snippet = self._get_code_snippet(code, issue.line_number, context=2)
        issue.code_snippet = code_snippet

        # Generate suggestion based on issue type
        if issue.issue_type == CleaningIssueType.MISSING_DOC:
            if "function" in issue.description.lower():
                suggestion = "Add a comprehensive docstring describing purpose, parameters, and return value"
                example_code = '''"""
    Brief description of what this function does.

    Args:
        param1: Description of first parameter
        param2: Description of second parameter

    Returns:
        Description of return value

    Raises:
        ExceptionType: When this exception occurs
    """'''
            else:
                suggestion = "Add a docstring describing the class purpose and usage"
                example_code = '''"""
    Brief description of this class.

    This class handles...

    Attributes:
        attr1: Description of attribute
        attr2: Description of attribute

    Example:
        >>> obj = MyClass()
        >>> obj.method()
    """'''

            rationale = "Good documentation improves code maintainability and helps other developers"

        elif issue.issue_type == CleaningIssueType.POOR_DOC:
            suggestion = "Improve docstring with more details and proper formatting"
            rationale = "Complete documentation reduces onboarding time and prevents misuse"
            example_code = "Follow Google, NumPy, or Sphinx docstring style consistently"

        elif issue.issue_type == CleaningIssueType.POOR_NAMING:
            suggestion = "Use descriptive names that clearly indicate purpose"
            rationale = "Good naming makes code self-documenting and reduces need for comments"
            example_code = """# Instead of: data, obj, tmp
# Use: user_profile, payment_processor, temporary_cache"""

        elif "TODO" in issue.description or "FIXME" in issue.description:
            suggestion = "Address or remove outdated TODO/FIXME comments"
            rationale = "Old TODOs clutter code and may reference outdated requirements"
            example_code = "Either implement the TODO or remove if no longer relevant"

        elif "HACK" in issue.description or "BUG" in issue.description:
            suggestion = "Replace hack/workaround with proper implementation"
            rationale = "Technical debt accumulates and makes code harder to maintain"
            example_code = "Refactor to use proper design patterns instead of hacks"

        else:
            suggestion = "Improve documentation quality"
            rationale = "Better documentation improves code maintainability"
            example_code = ""

        return CleaningSuggestion(
            issue=issue,
            suggestion=suggestion,
            rationale=rationale,
            example_code=example_code,
        )