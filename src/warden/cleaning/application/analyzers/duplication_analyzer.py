"""
Duplication Analyzer

Detects code duplication:
- Duplicate code blocks
- Similar functions
- Repeated patterns

Universal multi-language support via tree-sitter AST (uses BaseCleaningAnalyzer helpers).
"""

from difflib import SequenceMatcher
from typing import Any, List, Optional, Tuple

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

    Universal multi-language support via tree-sitter AST.
    """

    @property
    def name(self) -> str:
        """Analyzer name."""
        return "Duplication Analyzer"

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
        Analyze code for duplication using Universal AST.

        Args:
            code_file: The code file to analyze
            cancellation_token: Optional cancellation token
            ast_tree: Optional pre-parsed Universal AST tree

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
            lines = code_file.content.split("\n")
            issues = []

            # Check for duplicate code blocks (line-based, no AST needed)
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

            # Check for similar functions using Universal AST
            ast_root = await self._get_ast_root(code_file, ast_tree)
            if ast_root:
                similar_functions = self._find_similar_functions_universal(ast_root, code_file.content)
                for func1_name, func2_name, line_number, similarity in similar_functions:
                    issues.append(
                        CleaningIssue(
                            issue_type=CleaningIssueType.CODE_DUPLICATION,
                            description=f"Function '{func1_name}' is {int(similarity * 100)}% similar to '{func2_name}'",
                            line_number=line_number,
                            severity=CleaningIssueSeverity.MEDIUM,
                        )
                    )

            if not issues:
                return CleaningResult(
                    success=True,
                    file_path=code_file.path,
                    issues_found=0,
                    suggestions=[],
                    cleanup_score=100.0,
                    summary="No code duplication found",
                    analyzer_name=self.name,
                )

            # Convert issues to suggestions
            suggestions = [self._create_suggestion(issue, code_file.content) for issue in issues]

            # Calculate score
            total_lines = len(lines)
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
                    "duplicate_blocks": len(duplicate_blocks),
                    "similar_functions": len(similar_functions) if ast_root else 0,
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
                error_message=f"Analysis failed: {e!s}",
                analyzer_name=self.name,
            )

    def _find_duplicate_blocks(self, lines: list[str]) -> list[tuple[int, int, int]]:
        """
        Find duplicate code blocks (line-based, language-agnostic).

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
                while (
                    i + match_length < j
                    and j + match_length < len(lines)
                    and self._lines_similar(lines[i + match_length], lines[j + match_length])
                ):
                    match_length += 1

                if match_length >= MIN_DUPLICATE_LINES:
                    duplicates.append((i + 1, j + 1, match_length))  # 1-indexed
                    # Mark as processed
                    for k in range(match_length):
                        processed_pairs.add((i + k, j + k))

        return duplicates

    def _lines_similar(self, line1: str, line2: str) -> bool:
        """
        Check if two lines are similar (language-agnostic).

        Args:
            line1: First line
            line2: Second line

        Returns:
            True if lines are similar
        """
        # Strip whitespace for comparison
        l1 = line1.strip()
        l2 = line2.strip()

        # Ignore blank lines and comments (#, //)
        if not l1 or not l2:
            return False
        if l1.startswith(("#", "//")) or l2.startswith(("#", "//")):
            return False

        # Use sequence matcher for similarity
        similarity = SequenceMatcher(None, l1, l2).ratio()
        return similarity >= SIMILARITY_THRESHOLD

    def _find_similar_functions_universal(self, ast_root: ASTNode, code: str) -> list[tuple[str, str, int, float]]:
        """
        Find similar functions using Universal AST.

        Works for all languages (Python, Swift, Dart, Go, JS, etc.)

        Args:
            ast_root: Universal AST root node
            code: Source code

        Returns:
            List of (func1_name, func2_name, line_number, similarity)
        """
        similar_functions = []
        lines = code.split("\n")

        # Get all functions/methods using base class helper
        functions = self._get_functions_and_methods(ast_root)

        # Compare each pair of functions
        for i, func1 in enumerate(functions):
            for func2 in functions[i + 1 :]:
                similarity = self._calculate_function_similarity_universal(func1, func2, lines)
                if similarity >= SIMILARITY_THRESHOLD:
                    line_number = func1.location.start_line if func1.location else 0
                    similar_functions.append(
                        (func1.name or "<anonymous>", func2.name or "<anonymous>", line_number, similarity)
                    )

        return similar_functions

    def _calculate_function_similarity_universal(self, func1: ASTNode, func2: ASTNode, lines: list[str]) -> float:
        """
        Calculate similarity between two functions using Universal AST.

        Args:
            func1: First function node
            func2: Second function node
            lines: Source code lines

        Returns:
            Similarity score (0.0 to 1.0)
        """
        # Extract function body lines from locations
        func1_lines = self._get_function_body_lines_universal(func1, lines)
        func2_lines = self._get_function_body_lines_universal(func2, lines)

        if not func1_lines or not func2_lines:
            return 0.0

        # Compare bodies
        func1_body = "\n".join(func1_lines)
        func2_body = "\n".join(func2_lines)

        return SequenceMatcher(None, func1_body, func2_body).ratio()

    def _get_function_body_lines_universal(self, func: ASTNode, lines: list[str]) -> list[str]:
        """
        Extract function body lines from Universal AST node.

        Args:
            func: Universal AST function/method node
            lines: All code lines

        Returns:
            Function body lines
        """
        if not func.location:
            return []

        start_line = func.location.start_line - 1
        end_line = func.location.end_line

        # Extract and clean lines
        body_lines = []
        for i in range(start_line, min(end_line, len(lines))):
            line = lines[i].strip()
            if line and not line.startswith(("#", "//")):
                body_lines.append(line)

        return body_lines

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
