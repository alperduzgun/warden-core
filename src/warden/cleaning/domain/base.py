"""
Base Cleanup Analyzer Interface

Abstract base class for all cleanup analyzers.
Follows Python ABC pattern (not C# interfaces).

Universal AST Support:
- All analyzers automatically support multi-language analysis via tree-sitter
- Base class provides AST parsing and common helper methods
- Analyzers can focus on logic, not parsing boilerplate
"""

from abc import ABC, abstractmethod
from typing import Optional, Any, Set, List
import structlog

from warden.cleaning.domain.models import CleaningResult
from warden.validation.domain.frame import CodeFile
from warden.ast.application.provider_registry import ASTProviderRegistry
from warden.ast.domain.enums import CodeLanguage, ASTNodeType, ParseStatus
from warden.ast.domain.models import ASTNode

logger = structlog.get_logger()


class CleaningAnalyzerPriority:
    """
    Priority levels for cleanup analyzers.

    Lower values execute first.
    """
    CRITICAL = 0  # Critical issues (e.g., severe naming problems)
    HIGH = 1      # High priority (e.g., complexity, duplication)
    MEDIUM = 2    # Medium priority (e.g., magic numbers)
    LOW = 3       # Low priority (e.g., minor style issues)


class BaseCleaningAnalyzer(ABC):
    """
    Abstract base class for code cleanup analyzers.

    Each analyzer implements a specific cleanup check:
    - Naming conventions
    - Code duplication
    - Magic numbers
    - Complexity
    - Documentation
    - Dead code

    IMPORTANT: Warden is a REPORTER, not a code modifier.
    Analyzers ONLY detect and report issues, NEVER modify code.

    Universal AST Support:
    - Automatically initializes AST provider registry
    - Provides helper methods for AST parsing
    - Supports all tree-sitter languages (Python, Swift, Dart, Go, etc.)
    """

    def __init__(self):
        """Initialize analyzer with Universal AST support."""
        self._ast_registry: Optional[ASTProviderRegistry] = None

    async def _ensure_ast_registry(self) -> None:
        """Ensure AST provider registry is initialized (lazy init)."""
        if self._ast_registry is None:
            self._ast_registry = ASTProviderRegistry()
            await self._ast_registry.discover_providers()

    async def _get_ast_root(
        self,
        code_file: CodeFile,
        ast_tree: Optional[Any] = None
    ) -> Optional[ASTNode]:
        """
        Get Universal AST root for a code file.

        Auto-handles parsing with appropriate provider (Python native or tree-sitter).

        Args:
            code_file: Code file to parse
            ast_tree: Optional pre-parsed AST tree (if provided, returns it)

        Returns:
            ASTNode root or None if parsing failed
        """
        # If AST already provided, use it
        if ast_tree and isinstance(ast_tree, ASTNode):
            return ast_tree

        # Ensure registry initialized
        await self._ensure_ast_registry()

        # Parse using Universal AST provider
        try:
            language = CodeLanguage(code_file.language.lower())
        except (ValueError, AttributeError):
            language = CodeLanguage.UNKNOWN

        provider = self._ast_registry.get_provider(language)
        if not provider:
            logger.debug(
                "no_ast_provider_for_language",
                language=language,
                file_path=code_file.path,
                analyzer=self.name,
            )
            return None

        parse_result = await provider.parse(
            code_file.content,
            language,
            code_file.path
        )

        if parse_result.status == ParseStatus.FAILED:
            logger.debug(
                "ast_parse_failed",
                error=parse_result.errors[0].message if parse_result.errors else "Unknown error",
                file_path=code_file.path,
                analyzer=self.name,
            )
            return None

        return parse_result.ast_root

    @property
    @abstractmethod
    def name(self) -> str:
        """Analyzer name (e.g., 'Naming Analyzer')."""
        pass

    @property
    @abstractmethod
    def priority(self) -> int:
        """
        Execution priority.

        Returns:
            Priority value (0 = highest, 3 = lowest)
        """
        pass

    @property
    def supported_languages(self) -> Set[str]:
        """
        Languages supported by this analyzer.

        Returns:
            Set of language names (lowercase). Empty set means all languages.

        Examples:
            {"python"} - Python only
            {"python", "javascript", "typescript"} - Multiple languages
            set() - All languages (universal analyzer)
        """
        return {"python"}  # Default: Python only (legacy behavior)

    @abstractmethod
    async def analyze_async(
        self,
        code_file: CodeFile,
        cancellation_token: Optional[str] = None,
        ast_tree: Optional[Any] = None,
    ) -> CleaningResult:
        """
        Analyze code for cleanup opportunities.

        Args:
            code_file: The code file to analyze
            cancellation_token: Optional cancellation token

        Returns:
            CleaningResult with detected issues and suggestions

        Note:
            This method REPORTS issues only. It NEVER modifies code.
        """
        pass

    def _get_code_snippet(self, code: str, line_number: int, context: int = 2) -> str:
        """
        Extract code snippet around a specific line.

        Args:
            code: Full source code
            line_number: Target line number (1-indexed)
            context: Number of lines before/after to include

        Returns:
            Code snippet as string
        """
        lines = code.split("\n")
        start = max(0, line_number - context - 1)
        end = min(len(lines), line_number + context)

        snippet_lines = lines[start:end]
        return "\n".join(snippet_lines)

    def _calculate_cleanup_score(self, issues_count: int, total_lines: int) -> float:
        """
        Calculate cleanup score (0-100).

        Args:
            issues_count: Number of issues found
            total_lines: Total lines of code

        Returns:
            Score from 0-100 (100 = perfect, no issues)
        """
        if total_lines == 0:
            return 100.0

        # Score decreases based on issue density
        issue_density = issues_count / total_lines
        score = max(0.0, 100.0 - (issue_density * 100.0))
        return round(score, 2)

    # =========================================================================
    # Universal AST Helper Methods (Multi-Language Support)
    # =========================================================================

    def _get_functions_and_methods(self, ast_root: ASTNode) -> List[ASTNode]:
        """
        Find all functions and methods in Universal AST.

        Works for all languages (Python, Swift, Dart, Go, JS, etc.)

        Args:
            ast_root: Universal AST root node

        Returns:
            List of function/method nodes
        """
        functions = ast_root.find_nodes(ASTNodeType.FUNCTION)
        methods = ast_root.find_nodes(ASTNodeType.METHOD)
        return functions + methods

    def _count_function_lines_universal(self, node: ASTNode, lines: List[str]) -> int:
        """
        Count non-empty lines in a function (Universal AST).

        Args:
            node: Universal AST function/method node
            lines: Source code split into lines

        Returns:
            Number of non-empty lines
        """
        if not node.location:
            return 0

        start_line = node.location.start_line - 1
        end_line = node.location.end_line

        # Count non-empty, non-comment lines
        count = 0
        for i in range(start_line, min(end_line, len(lines))):
            line = lines[i].strip()
            # Skip empty lines and comments (Python #, C-style //, /* */)
            if line and not line.startswith(("#", "//", "/*")):
                count += 1

        return count

    def _calculate_nesting_depth_universal(self, node: ASTNode) -> int:
        """
        Calculate maximum nesting depth in a function (Universal AST).

        Works for all languages.

        Args:
            node: Universal AST function/method node

        Returns:
            Maximum nesting depth
        """
        def get_depth(node: ASTNode, current_depth: int = 0) -> int:
            """Recursively calculate depth."""
            max_depth = current_depth

            for child in node.children:
                # Increase depth for control structures
                if child.node_type in (
                    ASTNodeType.IF_STATEMENT,
                    ASTNodeType.LOOP_STATEMENT,
                    ASTNodeType.TRY_CATCH,
                ):
                    child_depth = get_depth(child, current_depth + 1)
                    max_depth = max(max_depth, child_depth)
                else:
                    child_depth = get_depth(child, current_depth)
                    max_depth = max(max_depth, child_depth)

            return max_depth

        return get_depth(node, 0)

    def _calculate_cyclomatic_complexity_universal(self, node: ASTNode) -> int:
        """
        Calculate cyclomatic complexity of a function (Universal AST).

        Cyclomatic complexity = number of decision points + 1
        Works for all languages.

        Args:
            node: Universal AST function/method node

        Returns:
            Cyclomatic complexity
        """
        complexity = 1  # Base complexity

        def count_decision_points(node: ASTNode) -> int:
            """Recursively count decision points."""
            count = 0

            # Count decision points based on node type
            if node.node_type in (
                ASTNodeType.IF_STATEMENT,
                ASTNodeType.LOOP_STATEMENT,
            ):
                count += 1
            elif node.node_type == ASTNodeType.TRY_CATCH:
                count += 1
            elif node.node_type == ASTNodeType.BINARY_EXPRESSION:
                # Boolean operators (&&, ||) add complexity
                if node.attributes.get("operator") in ("&&", "||", "and", "or"):
                    count += 1

            # Recursively count in children
            for child in node.children:
                count += count_decision_points(child)

            return count

        complexity += count_decision_points(node)
        return complexity

    def _count_parameters_universal(self, node: ASTNode) -> int:
        """
        Count parameters in a function (Universal AST).

        Args:
            node: Universal AST function/method node

        Returns:
            Number of parameters
        """
        # Check if parameter count is stored in attributes
        if "parameter_count" in node.attributes:
            return node.attributes["parameter_count"]

        # Count by looking for parameter-related attributes
        if "parameters" in node.attributes:
            params = node.attributes["parameters"]
            if isinstance(params, list):
                return len(params)

        # Fallback: estimate from node structure
        return 0
