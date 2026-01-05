"""
Duplication Analyzer

Detects code duplication:
- Duplicate code blocks
- Similar functions
- Repeated patterns
"""

import ast
import structlog
from typing import List, Optional, Tuple, Any
from difflib import SequenceMatcher

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

# Minimum lines for duplication detection
MIN_DUPLICATE_LINES = 3
# Similarity threshold (0.0 to 1.0)
SIMILARITY_THRESHOLD = 0.8


class DuplicationAnalyzer(BaseCleaningAnalyzer):
    """
    Analyzer for detecting code duplication.

    Checks:
    - Duplicate code blocks
    - Similar functions
    - Repeated patterns
    """

    @property
    def name(self) -> str:
        """Analyzer name."""
        return "Duplication Analyzer"

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
        Analyze code for duplication.

        Args:
            code_file: The code file to analyze
            cancellation_token: Optional cancellation token

        Returns:
            CleaningResult with duplication issues
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
            issues = self._analyze_duplication(code_file.content, ast_tree)

            if not issues:
                logger.info(
                    "no_duplication_issues",
                    file_path=code_file.path,
                    analyzer=self.name,
                )
                return CleaningResult(
                    success=True,
                    file_path=code_file.path,
                    issues_found=0,
                    suggestions=[],
                    cleanup_score=100.0,
                    summary="No code duplication found",
                    analyzer_name=self.name,
                )

            logger.info(
                "duplication_issues_found",
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
                summary=f"Found {len(issues)} code duplication issues",
                analyzer_name=self.name,
                metrics={
                    "duplicate_blocks": len(issues),
                    "total_duplicated_lines": sum(
                        int(i.description.split("lines")[0].split()[-1])
                        for i in issues if "lines" in i.description
                    ) if issues else 0,
                },
            )

        except Exception as e:
            logger.error(
                "duplication_analysis_failed",
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

    def _analyze_duplication(self, code: str, ast_tree: Optional[Any] = None) -> List[CleaningIssue]:
        """
        Analyze code for duplication.

        Args:
            code: Source code to analyze
            ast_tree: Optional pre-parsed AST

        Returns:
            List of duplication issues
        """
        issues = []
        lines = code.split("\n")

        # Check for duplicate code blocks
        duplicate_blocks = self._find_duplicate_blocks(lines)
        for block1_start, block2_start, length in duplicate_blocks:
            issues.append(
                CleaningIssue(
                    issue_type=CleaningIssueType.CODE_DUPLICATION,
                    description=f"Duplicate code block of {length} lines (also at line {block2_start})",
                    line_number=block1_start,
                    severity=CleaningIssueSeverity.HIGH if length > 5 else CleaningIssueSeverity.MEDIUM,
                )
            )

        # Check for similar functions using AST
        try:
            tree = ast_tree if ast_tree else ast.parse(code)
            similar_functions = self._find_similar_functions(tree, code)
            for func1_name, func2_name, line_number, similarity in similar_functions:
                issues.append(
                    CleaningIssue(
                        issue_type=CleaningIssueType.CODE_DUPLICATION,
                        description=f"Function '{func1_name}' is {int(similarity*100)}% similar to '{func2_name}'",
                        line_number=line_number,
                        severity=CleaningIssueSeverity.MEDIUM,
                    )
                )
        except SyntaxError:
            logger.warning("syntax_error_in_duplication_analysis")

        return issues

    def _find_duplicate_blocks(self, lines: List[str]) -> List[Tuple[int, int, int]]:
        """
        Find duplicate code blocks.

        Args:
            lines: Code lines

        Returns:
            List of (block1_start, block2_start, length) tuples
        """
        duplicates = []
        processed_pairs = set()

        for i in range(len(lines)):
            for j in range(i + MIN_DUPLICATE_LINES, len(lines)):
                # Skip if we already processed this pair
                if (i, j) in processed_pairs:
                    continue

                # Check for duplicate starting from i and j
                match_length = 0
                while (i + match_length < j and
                       j + match_length < len(lines) and
                       self._lines_similar(lines[i + match_length], lines[j + match_length])):
                    match_length += 1

                if match_length >= MIN_DUPLICATE_LINES:
                    duplicates.append((i + 1, j + 1, match_length))  # 1-indexed
                    # Mark as processed
                    for k in range(match_length):
                        processed_pairs.add((i + k, j + k))

        return duplicates

    def _lines_similar(self, line1: str, line2: str) -> bool:
        """
        Check if two lines are similar.

        Args:
            line1: First line
            line2: Second line

        Returns:
            True if lines are similar
        """
        # Strip whitespace for comparison
        l1 = line1.strip()
        l2 = line2.strip()

        # Ignore blank lines and comments
        if not l1 or not l2 or l1.startswith("#") or l2.startswith("#"):
            return False

        # Use sequence matcher for similarity
        similarity = SequenceMatcher(None, l1, l2).ratio()
        return similarity >= SIMILARITY_THRESHOLD

    def _find_similar_functions(
        self,
        tree: ast.AST,
        code: str
    ) -> List[Tuple[str, str, int, float]]:
        """
        Find similar functions using AST.

        Args:
            tree: AST tree
            code: Source code

        Returns:
            List of (func1_name, func2_name, line_number, similarity)
        """
        similar_functions = []
        functions = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]

        # Compare each pair of functions
        for i, func1 in enumerate(functions):
            for func2 in functions[i + 1:]:
                similarity = self._calculate_function_similarity(func1, func2, code)
                if similarity >= SIMILARITY_THRESHOLD:
                    similar_functions.append(
                        (func1.name, func2.name, func1.lineno, similarity)
                    )

        return similar_functions

    def _calculate_function_similarity(
        self,
        func1: ast.FunctionDef,
        func2: ast.FunctionDef,
        code: str
    ) -> float:
        """
        Calculate similarity between two functions.

        Args:
            func1: First function AST node
            func2: Second function AST node
            code: Source code

        Returns:
            Similarity score (0.0 to 1.0)
        """
        # Extract function bodies
        lines = code.split("\n")

        # Get function body lines
        func1_lines = self._get_function_body_lines(func1, lines)
        func2_lines = self._get_function_body_lines(func2, lines)

        if not func1_lines or not func2_lines:
            return 0.0

        # Compare bodies
        func1_body = "\n".join(func1_lines)
        func2_body = "\n".join(func2_lines)

        return SequenceMatcher(None, func1_body, func2_body).ratio()

    def _get_function_body_lines(
        self,
        func: ast.FunctionDef,
        lines: List[str]
    ) -> List[str]:
        """
        Extract function body lines.

        Args:
            func: Function AST node
            lines: All code lines

        Returns:
            Function body lines
        """
        start_line = func.lineno - 1

        # Find end line (simplified - just take next 20 lines or until blank)
        end_line = min(start_line + 20, len(lines))

        return [line.strip() for line in lines[start_line:end_line] if line.strip()]

    def _create_suggestion(self, issue: CleaningIssue, code: str) -> CleaningSuggestion:
        """Create a cleanup suggestion from an issue."""
        # Extract code snippet
        code_snippet = self._get_code_snippet(code, issue.line_number)
        issue.code_snippet = code_snippet

        suggestion = "Extract duplicated code into a reusable function or method"
        rationale = "Code duplication makes maintenance harder and increases the risk of bugs"

        if "similar to" in issue.description:
            suggestion = "Consider extracting common logic into a shared function or using inheritance"
            rationale = "Similar functions suggest opportunities for abstraction and code reuse"

        return CleaningSuggestion(
            issue=issue,
            suggestion=suggestion,
            rationale=rationale,
        )
