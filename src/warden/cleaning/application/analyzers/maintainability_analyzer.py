"""
Maintainability Analyzer

Calculates Maintainability Index and detects code smells:
- Maintainability Index (MI) based on Halstead metrics
- SOLID principle violations
- Code smell detection
- Coupling and cohesion analysis
"""

import ast
import math
import structlog
from typing import List, Optional, Dict, Any, Set
from collections import defaultdict

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


class MaintainabilityAnalyzer(BaseCleaningAnalyzer):
    """
    Analyzer for code maintainability metrics.

    Calculates:
    - Maintainability Index (0-100)
    - Code smells detection
    - SOLID violations
    - Coupling metrics
    """

    @property
    def name(self) -> str:
        """Analyzer name."""
        return "Maintainability Analyzer"

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
        Analyze code maintainability.

        Args:
            code_file: The code file to analyze
            cancellation_token: Optional cancellation token

        Returns:
            CleaningResult with maintainability metrics and issues
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
            # Calculate maintainability metrics
            mi_score, halstead_metrics = self._calculate_maintainability_index(code_file.content, ast_tree)
            issues = self._detect_maintainability_issues(code_file.content, ast_tree)

            # Calculate quality score (0-10 scale from MI 0-100)
            quality_score = mi_score / 10.0

            logger.info(
                "maintainability_analysis_complete",
                file_path=code_file.path,
                mi_score=mi_score,
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
                summary=f"Maintainability Index: {mi_score:.1f}/100",
                analyzer_name=self.name,
                metrics={
                    "maintainability_index": mi_score,
                    "quality_score": quality_score,
                    "halstead_volume": halstead_metrics.get("volume", 0),
                    "halstead_difficulty": halstead_metrics.get("difficulty", 0),
                    "code_smells": len(issues),
                },
            )

        except Exception as e:
            logger.error(
                "maintainability_analysis_failed",
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

    def _calculate_maintainability_index(self, code: str, ast_tree: Optional[Any] = None) -> tuple[float, Dict[str, Any]]:
        """
        Calculate Maintainability Index based on Halstead metrics.

        MI = 171 - 5.2*ln(V) - 0.23*CC - 16.2*ln(LOC)

        Where:
        - V = Halstead Volume
        - CC = Cyclomatic Complexity
        - LOC = Lines of Code

        Args:
            code: Source code
            ast_tree: Optional pre-parsed AST

        Returns:
            (MI score 0-100, Halstead metrics dict)
        """
        try:
            tree = ast_tree if ast_tree else ast.parse(code)
        except SyntaxError:
            return 50.0, {}  # Default middle score on parse error

        # Calculate metrics
        halstead = self._calculate_halstead_metrics(tree, code)
        cyclomatic = self._calculate_cyclomatic_complexity(tree)
        loc = len([line for line in code.split('\n') if line.strip() and not line.strip().startswith('#')])

        # Calculate MI with safe logarithms
        volume = halstead.get("volume", 1)
        mi = 171.0

        if volume > 0:
            mi -= 5.2 * math.log(volume)

        mi -= 0.23 * cyclomatic

        if loc > 0:
            mi -= 16.2 * math.log(loc)

        # Normalize to 0-100 range
        mi = max(0, min(100, mi))

        return mi, halstead

    def _calculate_halstead_metrics(self, tree: ast.AST, code: str) -> Dict[str, Any]:
        """
        Calculate Halstead complexity metrics.

        Returns:
            Dictionary with Halstead metrics
        """
        operators = set()
        operands = set()
        total_operators = 0
        total_operands = 0

        for node in ast.walk(tree):
            # Count operators
            if isinstance(node, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod,
                                 ast.Pow, ast.FloorDiv, ast.And, ast.Or, ast.Not,
                                 ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
                                 ast.Is, ast.IsNot, ast.In, ast.NotIn)):
                operators.add(type(node).__name__)
                total_operators += 1

            # Count operands (variables, constants)
            elif isinstance(node, ast.Name):
                operands.add(node.id)
                total_operands += 1
            elif isinstance(node, (ast.Constant, ast.Num, ast.Str)):
                value = getattr(node, 'value', getattr(node, 'n', getattr(node, 's', '')))
                operands.add(str(value))
                total_operands += 1

        # Calculate Halstead metrics
        n1 = len(operators)  # Unique operators
        n2 = len(operands)   # Unique operands
        N1 = total_operators # Total operators
        N2 = total_operands  # Total operands

        vocabulary = n1 + n2
        length = N1 + N2

        # Volume
        volume = length * math.log2(vocabulary) if vocabulary > 0 else 0

        # Difficulty
        difficulty = (n1 / 2) * (N2 / n2) if n2 > 0 else 0

        # Effort
        effort = difficulty * volume

        return {
            "volume": volume,
            "difficulty": difficulty,
            "effort": effort,
            "vocabulary": vocabulary,
            "length": length,
        }

    def _calculate_cyclomatic_complexity(self, tree: ast.AST) -> int:
        """Calculate cyclomatic complexity of entire code."""
        complexity = 1

        for node in ast.walk(tree):
            if isinstance(node, (ast.If, ast.While, ast.For)):
                complexity += 1
            elif isinstance(node, ast.BoolOp):
                complexity += len(node.values) - 1
            elif isinstance(node, ast.ExceptHandler):
                complexity += 1
            elif isinstance(node, ast.comprehension):
                complexity += len(node.ifs)

        return complexity

    def _detect_maintainability_issues(self, code: str, ast_tree: Optional[Any] = None) -> List[CleaningIssue]:
        """
        Detect maintainability issues and code smells.

        Args:
            code: Source code
            ast_tree: Optional pre-parsed AST

        Returns:
            List of maintainability issues
        """
        issues = []

        try:
            tree = ast_tree if ast_tree else ast.parse(code)
        except SyntaxError:
            return issues

        # Detect various maintainability issues
        issues.extend(self._detect_god_classes(tree))
        issues.extend(self._detect_long_parameter_lists(tree))
        issues.extend(self._detect_deep_inheritance(tree))
        issues.extend(self._detect_feature_envy(tree))
        issues.extend(self._detect_inappropriate_intimacy(tree))
        issues.extend(self._detect_data_clumps(tree))

        return issues

    def _detect_god_classes(self, tree: ast.AST) -> List[CleaningIssue]:
        """Detect God Classes (classes doing too much)."""
        issues = []

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                methods = [n for n in node.body if isinstance(n, ast.FunctionDef)]
                attributes = [n for n in node.body if isinstance(n, ast.Assign)]

                # Check for too many methods or attributes
                if len(methods) > 20:
                    issues.append(
                        CleaningIssue(
                            issue_type=CleaningIssueType.DESIGN_SMELL,
                            description=f"God Class: '{node.name}' has {len(methods)} methods (max 20)",
                            line_number=node.lineno,
                            severity=CleaningIssueSeverity.HIGH,
                        )
                    )

                if len(attributes) > 15:
                    issues.append(
                        CleaningIssue(
                            issue_type=CleaningIssueType.DESIGN_SMELL,
                            description=f"God Class: '{node.name}' has {len(attributes)} attributes (max 15)",
                            line_number=node.lineno,
                            severity=CleaningIssueSeverity.MEDIUM,
                        )
                    )

        return issues

    def _detect_long_parameter_lists(self, tree: ast.AST) -> List[CleaningIssue]:
        """Detect functions with too many parameters."""
        issues = []
        MAX_PARAMS = 5

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                param_count = len(node.args.args)
                if param_count > MAX_PARAMS:
                    issues.append(
                        CleaningIssue(
                            issue_type=CleaningIssueType.DESIGN_SMELL,
                            description=f"Long Parameter List: '{node.name}' has {param_count} parameters (max {MAX_PARAMS})",
                            line_number=node.lineno,
                            severity=CleaningIssueSeverity.MEDIUM,
                        )
                    )

        return issues

    def _detect_deep_inheritance(self, tree: ast.AST) -> List[CleaningIssue]:
        """Detect deep inheritance hierarchies."""
        issues = []

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.bases:
                # Check for multiple inheritance
                if len(node.bases) > 2:
                    issues.append(
                        CleaningIssue(
                            issue_type=CleaningIssueType.DESIGN_SMELL,
                            description=f"Multiple Inheritance: '{node.name}' inherits from {len(node.bases)} classes",
                            line_number=node.lineno,
                            severity=CleaningIssueSeverity.MEDIUM,
                        )
                    )

        return issues

    def _detect_feature_envy(self, tree: ast.AST) -> List[CleaningIssue]:
        """Detect Feature Envy (methods using other class's data excessively)."""
        issues = []

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                # Count attribute accesses per object
                attr_access_count = defaultdict(int)

                for child in ast.walk(node):
                    if isinstance(child, ast.Attribute):
                        if isinstance(child.value, ast.Name):
                            obj_name = child.value.id
                            if obj_name != 'self':
                                attr_access_count[obj_name] += 1

                # Check if any external object is accessed too much
                for obj_name, count in attr_access_count.items():
                    if count > 5:
                        issues.append(
                            CleaningIssue(
                                issue_type=CleaningIssueType.DESIGN_SMELL,
                                description=f"Feature Envy: '{node.name}' accesses '{obj_name}' attributes {count} times",
                                line_number=node.lineno,
                                severity=CleaningIssueSeverity.LOW,
                            )
                        )

        return issues

    def _detect_inappropriate_intimacy(self, tree: ast.AST) -> List[CleaningIssue]:
        """Detect classes that know too much about each other."""
        issues = []

        # Track cross-class references
        class_references = defaultdict(set)

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                current_class = node.name

                for child in ast.walk(node):
                    if isinstance(child, ast.Name):
                        # Detect references to other classes
                        name = child.id
                        if name != current_class and name[0].isupper():
                            class_references[current_class].add(name)

        # Check for bidirectional dependencies
        for class1, refs1 in class_references.items():
            for class2 in refs1:
                if class2 in class_references and class1 in class_references[class2]:
                    issues.append(
                        CleaningIssue(
                            issue_type=CleaningIssueType.DESIGN_SMELL,
                            description=f"Inappropriate Intimacy: Bidirectional dependency between '{class1}' and '{class2}'",
                            line_number=1,  # Can't determine exact line
                            severity=CleaningIssueSeverity.MEDIUM,
                        )
                    )

        return issues

    def _detect_data_clumps(self, tree: ast.AST) -> List[CleaningIssue]:
        """Detect Data Clumps (parameters that always appear together)."""
        issues = []
        param_combinations = defaultdict(int)

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                # Get parameter names
                param_names = [arg.arg for arg in node.args.args]

                # Track combinations of 3+ parameters
                if len(param_names) >= 3:
                    for i in range(len(param_names) - 2):
                        combo = tuple(sorted(param_names[i:i+3]))
                        param_combinations[combo] += 1

        # Report combinations that appear multiple times
        for combo, count in param_combinations.items():
            if count > 2:
                issues.append(
                    CleaningIssue(
                        issue_type=CleaningIssueType.DESIGN_SMELL,
                        description=f"Data Clump: Parameters {combo} appear together {count} times",
                        line_number=1,  # Can't determine exact line
                        severity=CleaningIssueSeverity.LOW,
                    )
                )

        return issues

    def _create_suggestion(self, issue: CleaningIssue, code: str) -> CleaningSuggestion:
        """Create a cleanup suggestion from an issue."""
        # Extract code snippet
        code_snippet = self._get_code_snippet(code, issue.line_number, context=3)
        issue.code_snippet = code_snippet

        # Generate suggestion based on issue type
        if "God Class" in issue.description:
            suggestion = "Split this class into smaller, focused classes"
            rationale = "Large classes are hard to understand and maintain. Follow Single Responsibility Principle."
            example_code = """# Extract related methods into separate classes:
class UserManager:
    def create_user(self): ...
    def delete_user(self): ...

class UserValidator:
    def validate_email(self): ...
    def validate_password(self): ..."""

        elif "Long Parameter List" in issue.description:
            suggestion = "Group related parameters into a configuration object or data class"
            rationale = "Long parameter lists make functions hard to use and understand."
            example_code = """# Use dataclass or named tuple:
@dataclass
class UserConfig:
    name: str
    email: str
    age: int

def create_user(config: UserConfig):
    ..."""

        elif "Multiple Inheritance" in issue.description:
            suggestion = "Consider using composition instead of multiple inheritance"
            rationale = "Multiple inheritance can lead to complex and confusing hierarchies."
            example_code = """# Use composition:
class User:
    def __init__(self):
        self.auth_handler = AuthHandler()
        self.data_manager = DataManager()"""

        elif "Feature Envy" in issue.description:
            suggestion = "Move this method to the class whose data it uses"
            rationale = "Methods should be close to the data they operate on."
            example_code = """# Move method to appropriate class:
class Order:
    def calculate_total(self):
        # This method belongs here
        return sum(self.items)"""

        elif "Inappropriate Intimacy" in issue.description:
            suggestion = "Reduce coupling between classes using interfaces or dependency injection"
            rationale = "Classes should not know too much about each other's internals."
            example_code = """# Use dependency injection:
class Service:
    def __init__(self, repository):
        self.repository = repository"""

        elif "Data Clump" in issue.description:
            suggestion = "Extract these parameters into a value object"
            rationale = "Parameters that travel together should be encapsulated."
            example_code = """# Create value object:
@dataclass
class Address:
    street: str
    city: str
    zip_code: str"""

        else:
            suggestion = "Refactor to improve maintainability"
            rationale = "This code has maintainability issues that should be addressed."
            example_code = ""

        return CleaningSuggestion(
            issue=issue,
            suggestion=suggestion,
            rationale=rationale,
            example_code=example_code,
        )