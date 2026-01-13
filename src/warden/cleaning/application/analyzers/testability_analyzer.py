"""
Testability Analyzer

Analyzes code testability and test coverage potential:
- Test file detection and coverage estimation
- Mockability analysis
- Dependency injection patterns
- Side effect detection
- Test complexity assessment
"""

import ast
import re
import structlog
from typing import List, Optional, Dict, Any, Set
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


class TestabilityAnalyzer(BaseCleaningAnalyzer):
    """
    Analyzer for code testability metrics.

    Checks:
    - Test coverage potential
    - Mockability of dependencies
    - Dependency injection usage
    - Side effects in functions
    - Test complexity factors
    """

    @property
    def name(self) -> str:
        """Analyzer name."""
        return "Testability Analyzer"

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
        Analyze code testability.

        Args:
            code_file: The code file to analyze
            cancellation_token: Optional cancellation token
            ast_tree: Optional pre-parsed AST tree of the code file

        Returns:
            CleaningResult with testability metrics
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
            # Check if this is a test file
            is_test_file = self._is_test_file(code_file.path)

            if is_test_file:
                # Analyze test quality instead of testability
                test_quality = self._analyze_test_quality(code_file.content, ast_tree)
                quality_score = test_quality.get("quality_score", 5.0)
                issues = test_quality.get("issues", [])
            else:
                # Analyze testability
                testability_metrics = self._analyze_testability(code_file.content, ast_tree)
                issues = testability_metrics.get("issues", [])
                quality_score = testability_metrics.get("testability_score", 5.0)

            logger.info(
                "testability_analysis_complete",
                file_path=code_file.path,
                is_test_file=is_test_file,
                quality_score=quality_score,
                issues_found=len(issues),
            )

            # Convert issues to suggestions
            suggestions = [self._create_suggestion(issue, code_file.content) for issue in issues]

            # Calculate cleanup score
            total_lines = len(code_file.content.split("\n"))
            cleanup_score = self._calculate_cleanup_score(len(issues), total_lines)

            summary = (
                f"Test quality score: {quality_score:.1f}/10"
                if is_test_file
                else f"Testability score: {quality_score:.1f}/10"
            )

            return CleaningResult(
                success=True,
                file_path=code_file.path,
                issues_found=len(issues),
                suggestions=suggestions,
                cleanup_score=cleanup_score,
                summary=summary,
                analyzer_name=self.name,
                metrics={
                    "testability_score": quality_score,
                    "is_test_file": is_test_file,
                },
            )

        except Exception as e:
            logger.error(
                "testability_analysis_failed",
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

    def _is_test_file(self, file_path: str) -> bool:
        """Check if file is a test file based on path and naming."""
        path = Path(file_path)
        name_lower = path.name.lower()

        # Check file name patterns
        test_patterns = [
            'test_', '_test.py', 'tests.py',
            'spec_', '_spec.py', 'specs.py'
        ]

        for pattern in test_patterns:
            if pattern in name_lower:
                return True

        # Check if in test directory
        path_parts = [p.lower() for p in path.parts]
        test_dirs = ['test', 'tests', 'spec', 'specs', '__tests__']

        for test_dir in test_dirs:
            if test_dir in path_parts:
                return True

        return False

    def _analyze_testability(self, code: str, ast_tree: Optional[Any] = None) -> Dict[str, Any]:
        """
        Analyze code testability factors.

        Returns:
            Dictionary with testability metrics and issues
        """
        try:
            tree = ast_tree if ast_tree else ast.parse(code)
        except SyntaxError:
            return {"testability_score": 0, "issues": []}

        issues = []
        metrics = {
            "functions": 0,
            "testable_functions": 0,
            "classes": 0,
            "testable_classes": 0,
            "global_state_usage": 0,
            "side_effects": 0,
            "hard_dependencies": 0,
        }

        # Analyze functions
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                metrics["functions"] += 1
                func_issues = self._analyze_function_testability(node, tree)
                if not func_issues:
                    metrics["testable_functions"] += 1
                issues.extend(func_issues)

            elif isinstance(node, ast.ClassDef):
                metrics["classes"] += 1
                class_issues = self._analyze_class_testability(node)
                if not class_issues:
                    metrics["testable_classes"] += 1
                issues.extend(class_issues)

        # Detect global state usage
        global_issues = self._detect_global_state_usage(tree)
        metrics["global_state_usage"] = len(global_issues)
        issues.extend(global_issues)

        # Calculate testability score (0-10)
        score = 10.0

        # Deduct for untestable functions
        if metrics["functions"] > 0:
            testable_ratio = metrics["testable_functions"] / metrics["functions"]
            score -= (1 - testable_ratio) * 3

        # Deduct for untestable classes
        if metrics["classes"] > 0:
            testable_ratio = metrics["testable_classes"] / metrics["classes"]
            score -= (1 - testable_ratio) * 2

        # Deduct for global state usage
        score -= min(metrics["global_state_usage"] * 0.5, 3)

        # Ensure score is within bounds
        score = max(0, min(10, score))

        return {
            "testability_score": score,
            "issues": issues,
            "metrics": metrics,
        }

    def _analyze_function_testability(self, node: ast.FunctionDef, tree: ast.AST) -> List[CleaningIssue]:
        """Analyze testability issues in a function."""
        issues = []

        # Check for side effects
        has_side_effects = self._has_side_effects(node)
        if has_side_effects:
            issues.append(
                CleaningIssue(
                    issue_type=CleaningIssueType.TESTABILITY_ISSUE,
                    description=f"Function '{node.name}' has side effects that make testing difficult",
                    line_number=node.lineno,
                    severity=CleaningIssueSeverity.MEDIUM,
                )
            )

        # Check for hard dependencies
        hard_deps = self._detect_hard_dependencies(node)
        if hard_deps:
            issues.append(
                CleaningIssue(
                    issue_type=CleaningIssueType.TESTABILITY_ISSUE,
                    description=f"Function '{node.name}' has hard dependencies: {', '.join(hard_deps)}",
                    line_number=node.lineno,
                    severity=CleaningIssueSeverity.MEDIUM,
                )
            )

        # Check for complex control flow
        complexity = self._calculate_complexity(node)
        if complexity > 10:
            issues.append(
                CleaningIssue(
                    issue_type=CleaningIssueType.TESTABILITY_ISSUE,
                    description=f"Function '{node.name}' has high complexity ({complexity}) making it hard to test",
                    line_number=node.lineno,
                    severity=CleaningIssueSeverity.HIGH,
                )
            )

        # Check for global variable access
        if self._uses_global_variables(node):
            issues.append(
                CleaningIssue(
                    issue_type=CleaningIssueType.TESTABILITY_ISSUE,
                    description=f"Function '{node.name}' accesses global variables",
                    line_number=node.lineno,
                    severity=CleaningIssueSeverity.MEDIUM,
                )
            )

        return issues

    def _analyze_class_testability(self, node: ast.ClassDef) -> List[CleaningIssue]:
        """Analyze testability issues in a class."""
        issues = []

        # Check for singleton pattern (hard to test)
        if self._is_singleton(node):
            issues.append(
                CleaningIssue(
                    issue_type=CleaningIssueType.TESTABILITY_ISSUE,
                    description=f"Class '{node.name}' uses singleton pattern which is hard to test",
                    line_number=node.lineno,
                    severity=CleaningIssueSeverity.HIGH,
                )
            )

        # Check for static methods that use external resources
        static_issues = self._check_static_methods(node)
        issues.extend(static_issues)

        # Check for tight coupling in __init__
        init_method = self._get_init_method(node)
        if init_method:
            # Check if __init__ creates dependencies instead of receiving them
            if self._creates_dependencies_in_init(init_method):
                issues.append(
                    CleaningIssue(
                        issue_type=CleaningIssueType.TESTABILITY_ISSUE,
                        description=f"Class '{node.name}' creates dependencies in __init__ instead of using dependency injection",
                        line_number=init_method.lineno,
                        severity=CleaningIssueSeverity.MEDIUM,
                    )
                )

        return issues

    def _analyze_test_quality(self, code: str, ast_tree: Optional[Any] = None) -> Dict[str, Any]:
        """
        Analyze test file quality.

        Returns:
            Dictionary with test quality metrics
        """
        try:
            tree = ast_tree if ast_tree else ast.parse(code)
        except SyntaxError:
            return {"quality_score": 0, "issues": []}

        issues = []
        test_count = 0
        assertion_count = 0
        mock_usage = 0

        for node in ast.walk(tree):
            # Count test functions
            if isinstance(node, ast.FunctionDef) and node.name.startswith('test'):
                test_count += 1

                # Check for assertions
                has_assertion = False
                for child in ast.walk(node):
                    if isinstance(child, ast.Assert):
                        has_assertion = True
                        assertion_count += 1
                    elif isinstance(child, ast.Call):
                        if hasattr(child.func, 'attr'):
                            # Check for unittest assertions
                            if child.func.attr.startswith('assert'):
                                has_assertion = True
                                assertion_count += 1

                if not has_assertion:
                    issues.append(
                        CleaningIssue(
                            issue_type=CleaningIssueType.TESTABILITY_ISSUE,
                            description=f"Test '{node.name}' has no assertions",
                            line_number=node.lineno,
                            severity=CleaningIssueSeverity.HIGH,
                        )
                    )

                # Check test complexity
                complexity = self._calculate_complexity(node)
                if complexity > 5:
                    issues.append(
                        CleaningIssue(
                            issue_type=CleaningIssueType.TESTABILITY_ISSUE,
                            description=f"Test '{node.name}' is too complex (complexity: {complexity})",
                            line_number=node.lineno,
                            severity=CleaningIssueSeverity.MEDIUM,
                        )
                    )

        # Calculate quality score
        score = 10.0

        if test_count == 0:
            score = 0
        else:
            # Deduct for tests without assertions
            tests_without_assertions = sum(1 for issue in issues if "no assertions" in issue.description)
            score -= (tests_without_assertions / test_count) * 5

            # Deduct for complex tests
            complex_tests = sum(1 for issue in issues if "too complex" in issue.description)
            score -= (complex_tests / test_count) * 3

        return {
            "quality_score": max(0, min(10, score)),
            "issues": issues,
            "test_count": test_count,
            "assertion_count": assertion_count,
        }

    def _has_side_effects(self, node: ast.FunctionDef) -> bool:
        """Check if function has side effects."""
        for child in ast.walk(node):
            # File I/O
            if isinstance(child, ast.Call):
                if hasattr(child.func, 'id') and child.func.id in ['open', 'print']:
                    return True
                if hasattr(child.func, 'attr') and child.func.attr in ['write', 'read', 'save']:
                    return True

            # Global modifications
            if isinstance(child, ast.Global):
                return True

            # Database/network calls (heuristic)
            if isinstance(child, ast.Attribute):
                if hasattr(child, 'attr'):
                    if any(keyword in child.attr.lower() for keyword in ['save', 'delete', 'update', 'insert', 'fetch', 'post', 'get']):
                        return True

        return False

    def _detect_hard_dependencies(self, node: ast.FunctionDef) -> List[str]:
        """Detect hard-coded dependencies in function."""
        hard_deps = []

        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                # Direct instantiation of external classes
                if hasattr(child.func, 'id'):
                    class_name = child.func.id
                    # Common external dependencies
                    if class_name in ['HTTPClient', 'DatabaseConnection', 'FileManager', 'Logger']:
                        hard_deps.append(class_name)

                # Import and instantiate pattern
                if isinstance(child.func, ast.Attribute):
                    if hasattr(child.func.value, 'id'):
                        module = child.func.value.id
                        if module in ['requests', 'urllib', 'socket', 'subprocess']:
                            hard_deps.append(f"{module}.{child.func.attr}")

        return hard_deps

    def _calculate_complexity(self, node: ast.FunctionDef) -> int:
        """Calculate cyclomatic complexity of a function."""
        complexity = 1

        for child in ast.walk(node):
            if isinstance(child, (ast.If, ast.While, ast.For)):
                complexity += 1
            elif isinstance(child, ast.BoolOp):
                complexity += len(child.values) - 1
            elif isinstance(child, ast.ExceptHandler):
                complexity += 1

        return complexity

    def _uses_global_variables(self, node: ast.FunctionDef) -> bool:
        """Check if function uses global variables."""
        for child in ast.walk(node):
            if isinstance(child, (ast.Global, ast.Nonlocal)):
                return True
        return False

    def _detect_global_state_usage(self, tree: ast.AST) -> List[CleaningIssue]:
        """Detect global state usage in module."""
        issues = []
        global_vars = set()

        # Find global variable assignments
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        if target.id.isupper():  # Constants are OK
                            continue
                        global_vars.add(target.id)

        # Check if globals are modified in functions
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                for child in ast.walk(node):
                    if isinstance(child, ast.Global):
                        for name in child.names:
                            if name in global_vars:
                                issues.append(
                                    CleaningIssue(
                                        issue_type=CleaningIssueType.TESTABILITY_ISSUE,
                                        description=f"Global variable '{name}' modified in function '{node.name}'",
                                        line_number=child.lineno,
                                        severity=CleaningIssueSeverity.HIGH,
                                    )
                                )

        return issues

    def _is_singleton(self, node: ast.ClassDef) -> bool:
        """Check if class implements singleton pattern."""
        has_instance = False
        has_new = False

        for child in node.body:
            if isinstance(child, ast.Assign):
                for target in child.targets:
                    if isinstance(target, ast.Name) and '_instance' in target.id.lower():
                        has_instance = True

            if isinstance(child, ast.FunctionDef):
                if child.name == '__new__':
                    has_new = True

        return has_instance or has_new

    def _check_static_methods(self, node: ast.ClassDef) -> List[CleaningIssue]:
        """Check static methods for testability issues."""
        issues = []

        for child in node.body:
            if isinstance(child, ast.FunctionDef):
                # Check if it's a static method
                is_static = any(
                    isinstance(dec, ast.Name) and dec.id == 'staticmethod'
                    for dec in child.decorator_list
                )

                if is_static and self._has_side_effects(child):
                    issues.append(
                        CleaningIssue(
                            issue_type=CleaningIssueType.TESTABILITY_ISSUE,
                            description=f"Static method '{child.name}' has side effects",
                            line_number=child.lineno,
                            severity=CleaningIssueSeverity.MEDIUM,
                        )
                    )

        return issues

    def _get_init_method(self, node: ast.ClassDef) -> Optional[ast.FunctionDef]:
        """Get __init__ method from class."""
        for child in node.body:
            if isinstance(child, ast.FunctionDef) and child.name == '__init__':
                return child
        return None

    def _creates_dependencies_in_init(self, init_method: ast.FunctionDef) -> bool:
        """Check if __init__ creates dependencies instead of receiving them."""
        for child in ast.walk(init_method):
            if isinstance(child, ast.Call):
                # Check for instantiation of external classes
                if hasattr(child.func, 'id'):
                    class_name = child.func.id
                    # Common dependencies that should be injected
                    if any(keyword in class_name.lower() for keyword in ['client', 'connection', 'manager', 'service', 'repository']):
                        # Check if it's assigned to self
                        parent = child
                        while parent:
                            if isinstance(parent, ast.Assign):
                                for target in parent.targets:
                                    if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == 'self':
                                        return True
                            parent = getattr(parent, 'parent', None)

        return False

    def _create_suggestion(self, issue: CleaningIssue, code: str) -> CleaningSuggestion:
        """Create a cleanup suggestion from an issue."""
        # Extract code snippet
        code_snippet = self._get_code_snippet(code, issue.line_number, context=3)
        issue.code_snippet = code_snippet

        # Generate suggestion based on issue description
        if "side effects" in issue.description:
            suggestion = "Refactor to pure functions or isolate side effects"
            rationale = "Pure functions are easier to test and reason about"
            example_code = """# Separate I/O from logic:
def calculate_result(data):
    # Pure logic
    return processed_data

def save_result(result, file_path):
    # Side effect isolated
    with open(file_path, 'w') as f:
        f.write(result)"""

        elif "hard dependencies" in issue.description:
            suggestion = "Use dependency injection to make code testable"
            rationale = "Dependency injection allows mocking in tests"
            example_code = """# Inject dependencies:
def process_data(data, http_client=None):
    client = http_client or HTTPClient()
    return client.fetch(data)"""

        elif "high complexity" in issue.description:
            suggestion = "Break down complex function into smaller, testable units"
            rationale = "Simple functions are easier to test comprehensively"
            example_code = """# Extract complex logic:
def main_function(data):
    validated = validate_data(data)
    processed = process_step1(validated)
    return process_step2(processed)"""

        elif "global variables" in issue.description:
            suggestion = "Pass state as parameters instead of using globals"
            rationale = "Functions without global state are predictable and testable"
            example_code = """# Pass state explicitly:
def process(data, config):
    # Use config parameter instead of global
    return apply_config(data, config)"""

        elif "singleton pattern" in issue.description:
            suggestion = "Consider using dependency injection instead of singleton"
            rationale = "Singletons make testing difficult due to shared state"
            example_code = """# Use dependency injection:
class Service:
    def __init__(self, config):
        self.config = config"""

        elif "no assertions" in issue.description:
            suggestion = "Add assertions to verify test expectations"
            rationale = "Tests without assertions don't verify behavior"
            example_code = """def test_addition():
    result = add(2, 3)
    assert result == 5
    assert isinstance(result, int)"""

        elif "too complex" in issue.description:
            suggestion = "Simplify test by focusing on single behavior"
            rationale = "Simple tests are easier to understand and maintain"
            example_code = """# One test per behavior:
def test_valid_input():
    assert process("valid") == "result"

def test_invalid_input():
    with pytest.raises(ValueError):
        process("invalid")"""

        else:
            suggestion = "Improve code testability"
            rationale = "Testable code is more maintainable and reliable"
            example_code = ""

        return CleaningSuggestion(
            issue=issue,
            suggestion=suggestion,
            rationale=rationale,
            example_code=example_code,
        )