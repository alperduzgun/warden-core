"""
Anti-Pattern Detection Frame

Detects common code anti-patterns and quality issues using AST analysis:
- Bare except clauses (catches all exceptions including system signals)
- God classes (classes > 500 lines violating SRP)
- Thread-unsafe singleton patterns
- Generic exception raising (raise Exception instead of specific types)
- Debug print statements in production code
- TODO/FIXME comments (technical debt markers)
- Built-in name shadowing (e.g., class TimeoutError)
- Missing await on coroutines

This frame works on ANY Python project, not just Warden.

Priority: HIGH
Blocker: TRUE (for critical anti-patterns)
Scope: FILE_LEVEL

Author: Warden Team
Version: 1.0.0
"""

import ast
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from warden.shared.infrastructure.logging import get_logger
from warden.validation.domain.enums import (
    FrameApplicability,
    FrameCategory,
    FramePriority,
    FrameScope,
)
from warden.validation.domain.frame import (
    CodeFile,
    Finding,
    FrameResult,
    Remediation,
    ValidationFrame,
)

logger = get_logger(__name__)


class AntiPatternSeverity(Enum):
    """Severity levels for anti-patterns."""
    CRITICAL = "critical"  # Blocks CI, must fix
    HIGH = "high"          # Should fix soon
    MEDIUM = "medium"      # Should fix
    LOW = "low"            # Nice to fix


@dataclass
class AntiPatternViolation:
    """Represents a detected anti-pattern."""

    pattern_id: str
    pattern_name: str
    severity: AntiPatternSeverity
    message: str
    file_path: str
    line: int
    column: int = 0
    code_snippet: Optional[str] = None
    suggestion: Optional[str] = None
    is_blocker: bool = False


# Python built-in names that should not be shadowed
PYTHON_BUILTINS: Set[str] = {
    # Exception types
    "Exception", "BaseException", "ValueError", "TypeError", "KeyError",
    "IndexError", "AttributeError", "ImportError", "RuntimeError",
    "StopIteration", "GeneratorExit", "SystemExit", "KeyboardInterrupt",
    "TimeoutError", "ConnectionError", "FileNotFoundError", "PermissionError",
    "OSError", "IOError", "EOFError", "MemoryError", "RecursionError",
    # Built-in functions/types
    "id", "type", "list", "dict", "set", "str", "int", "float", "bool",
    "tuple", "bytes", "object", "None", "True", "False",
    "len", "range", "print", "input", "open", "file",
    "map", "filter", "reduce", "zip", "enumerate", "sorted", "reversed",
    "min", "max", "sum", "abs", "round", "pow", "divmod",
    "hash", "hex", "oct", "bin", "chr", "ord", "ascii", "repr",
    "format", "vars", "dir", "help", "locals", "globals",
    "iter", "next", "slice", "property", "classmethod", "staticmethod",
    "super", "isinstance", "issubclass", "hasattr", "getattr", "setattr", "delattr",
    "callable", "exec", "eval", "compile",
}


class AntiPatternFrame(ValidationFrame):
    """
    Anti-Pattern Detection Frame

    Detects common Python anti-patterns using AST analysis.
    Works on any Python project.

    Detections:
    - bare-except: Bare except clauses that catch everything
    - god-class: Classes with 500+ lines (SRP violation)
    - thread-unsafe-singleton: Non-thread-safe singleton patterns
    - generic-exception-raise: Using `raise Exception()` instead of specific types
    - debug-print: Debug print statements in production
    - todo-fixme: TODO/FIXME comments indicating tech debt
    - builtin-shadow: Shadowing Python built-in names
    - missing-await: Calling async functions without await
    """

    # Frame metadata
    name = "Anti-Pattern Detection"
    description = "Detects common Python anti-patterns using AST analysis"
    category = FrameCategory.LANGUAGE_SPECIFIC
    priority = FramePriority.HIGH
    scope = FrameScope.FILE_LEVEL
    is_blocker = True  # Critical anti-patterns should block
    version = "1.0.0"
    author = "Warden Team"
    applicability = [FrameApplicability.PYTHON]

    @property
    def frame_id(self) -> str:
        return "antipattern"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize AntiPatternFrame.

        Config options:
            - max_class_lines: int (default: 500) - God class threshold
            - max_function_lines: int (default: 100) - Long function threshold
            - check_bare_except: bool (default: True)
            - check_god_class: bool (default: True)
            - check_singleton: bool (default: True)
            - check_generic_exception: bool (default: True)
            - check_debug_print: bool (default: True)
            - check_todo_fixme: bool (default: True)
            - check_builtin_shadow: bool (default: True)
            - check_missing_await: bool (default: True)
            - ignore_test_files: bool (default: True)
        """
        super().__init__(config)

        config_dict = self.config if isinstance(self.config, dict) else {}

        # Thresholds
        self.max_class_lines = config_dict.get("max_class_lines", 500)
        self.max_function_lines = config_dict.get("max_function_lines", 100)

        # Check toggles
        self.check_bare_except = config_dict.get("check_bare_except", True)
        self.check_god_class = config_dict.get("check_god_class", True)
        self.check_singleton = config_dict.get("check_singleton", True)
        self.check_generic_exception = config_dict.get("check_generic_exception", True)
        self.check_debug_print = config_dict.get("check_debug_print", True)
        self.check_todo_fixme = config_dict.get("check_todo_fixme", True)
        self.check_builtin_shadow = config_dict.get("check_builtin_shadow", True)
        self.check_missing_await = config_dict.get("check_missing_await", True)

        # Filtering
        self.ignore_test_files = config_dict.get("ignore_test_files", True)

    async def execute_async(self, code_file: CodeFile) -> FrameResult:
        """Execute anti-pattern detection on a code file."""
        start_time = time.perf_counter()

        logger.info(
            "antipattern_frame_started",
            file_path=code_file.path,
            language=code_file.language,
        )

        # Skip non-Python files
        if code_file.language.lower() != "python":
            return self._create_skipped_result(
                start_time, "Not a Python file"
            )

        # Skip test files if configured
        if self.ignore_test_files and self._is_test_file(code_file.path):
            return self._create_skipped_result(
                start_time, "Test file (ignored)"
            )

        violations: List[AntiPatternViolation] = []
        checks_executed: List[str] = []

        try:
            # Parse AST
            tree = ast.parse(code_file.content)
            lines = code_file.content.split("\n")

            # Run AST-based checks
            if self.check_bare_except:
                checks_executed.append("bare_except")
                violations.extend(self._detect_bare_except(tree, code_file, lines))

            if self.check_god_class:
                checks_executed.append("god_class")
                violations.extend(self._detect_god_class(tree, code_file, lines))

            if self.check_singleton:
                checks_executed.append("singleton")
                violations.extend(self._detect_unsafe_singleton(tree, code_file, lines))

            if self.check_generic_exception:
                checks_executed.append("generic_exception")
                violations.extend(self._detect_generic_exception_raise(tree, code_file, lines))

            if self.check_debug_print:
                checks_executed.append("debug_print")
                violations.extend(self._detect_debug_prints(tree, code_file, lines))

            if self.check_builtin_shadow:
                checks_executed.append("builtin_shadow")
                violations.extend(self._detect_builtin_shadowing(tree, code_file, lines))

            if self.check_missing_await:
                checks_executed.append("missing_await")
                violations.extend(self._detect_missing_await(tree, code_file, lines))

            # Run text-based checks
            if self.check_todo_fixme:
                checks_executed.append("todo_fixme")
                violations.extend(self._detect_todo_fixme(code_file, lines))

        except SyntaxError as e:
            logger.warning(
                "antipattern_syntax_error",
                file_path=code_file.path,
                error=str(e),
            )
            # Return partial result with syntax error noted
            duration = time.perf_counter() - start_time
            return FrameResult(
                frame_id=self.frame_id,
                frame_name=self.name,
                status="warning",
                duration=duration,
                issues_found=0,
                is_blocker=False,
                findings=[],
                metadata={
                    "error": f"Syntax error: {e}",
                    "checks_executed": checks_executed,
                },
            )

        # Convert violations to findings
        findings = self._violations_to_findings(violations)

        # Determine status and blocker
        has_critical = any(v.severity == AntiPatternSeverity.CRITICAL for v in violations)
        has_high = any(v.severity == AntiPatternSeverity.HIGH for v in violations)

        if has_critical:
            status = "failed"
            result_is_blocker = True
        elif has_high:
            status = "failed"
            result_is_blocker = False
        elif violations:
            status = "warning"
            result_is_blocker = False
        else:
            status = "passed"
            result_is_blocker = False

        duration = time.perf_counter() - start_time

        logger.info(
            "antipattern_frame_completed",
            file_path=code_file.path,
            status=status,
            violations=len(violations),
            duration=f"{duration:.2f}s",
        )

        return FrameResult(
            frame_id=self.frame_id,
            frame_name=self.name,
            status=status,
            duration=duration,
            issues_found=len(violations),
            is_blocker=result_is_blocker,
            findings=findings,
            metadata={
                "total_violations": len(violations),
                "critical": sum(1 for v in violations if v.severity == AntiPatternSeverity.CRITICAL),
                "high": sum(1 for v in violations if v.severity == AntiPatternSeverity.HIGH),
                "medium": sum(1 for v in violations if v.severity == AntiPatternSeverity.MEDIUM),
                "low": sum(1 for v in violations if v.severity == AntiPatternSeverity.LOW),
                "checks_executed": checks_executed,
            },
        )

    # =========================================================================
    # DETECTION METHODS
    # =========================================================================

    def _detect_bare_except(
        self, tree: ast.AST, code_file: CodeFile, lines: List[str]
    ) -> List[AntiPatternViolation]:
        """
        Detect bare except clauses.

        Anti-patterns:
        - except:  (catches everything including KeyboardInterrupt, SystemExit)
        - except Exception:  (too broad)
        - except BaseException:  (catches system signals)
        """
        violations = []

        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                # Bare except (no type specified)
                if node.type is None:
                    violations.append(AntiPatternViolation(
                        pattern_id="bare-except",
                        pattern_name="Bare Except Clause",
                        severity=AntiPatternSeverity.CRITICAL,
                        message="Bare 'except:' catches all exceptions including KeyboardInterrupt and SystemExit",
                        file_path=code_file.path,
                        line=node.lineno,
                        column=node.col_offset,
                        code_snippet=self._get_line(lines, node.lineno),
                        suggestion="Catch specific exceptions: except (ValueError, TypeError) as e:",
                        is_blocker=True,
                    ))

                # except Exception (too broad)
                elif isinstance(node.type, ast.Name) and node.type.id == "Exception":
                    # Check if body is just 'pass' (worse)
                    is_silent = (
                        len(node.body) == 1 and
                        isinstance(node.body[0], ast.Pass)
                    )

                    if is_silent:
                        violations.append(AntiPatternViolation(
                            pattern_id="except-pass",
                            pattern_name="Silent Exception Swallowing",
                            severity=AntiPatternSeverity.CRITICAL,
                            message="'except Exception: pass' silently swallows all errors",
                            file_path=code_file.path,
                            line=node.lineno,
                            column=node.col_offset,
                            code_snippet=self._get_line(lines, node.lineno),
                            suggestion="Log the error or handle it properly",
                            is_blocker=True,
                        ))
                    else:
                        violations.append(AntiPatternViolation(
                            pattern_id="broad-except",
                            pattern_name="Broad Exception Catch",
                            severity=AntiPatternSeverity.HIGH,
                            message="'except Exception' is too broad - catch specific exceptions",
                            file_path=code_file.path,
                            line=node.lineno,
                            column=node.col_offset,
                            code_snippet=self._get_line(lines, node.lineno),
                            suggestion="Catch specific exceptions: except (ValueError, IOError) as e:",
                            is_blocker=False,
                        ))

                # except BaseException (very dangerous)
                elif isinstance(node.type, ast.Name) and node.type.id == "BaseException":
                    violations.append(AntiPatternViolation(
                        pattern_id="baseexception-catch",
                        pattern_name="BaseException Catch",
                        severity=AntiPatternSeverity.CRITICAL,
                        message="'except BaseException' catches KeyboardInterrupt and SystemExit",
                        file_path=code_file.path,
                        line=node.lineno,
                        column=node.col_offset,
                        code_snippet=self._get_line(lines, node.lineno),
                        suggestion="Never catch BaseException - use specific exception types",
                        is_blocker=True,
                    ))

        return violations

    def _detect_god_class(
        self, tree: ast.AST, code_file: CodeFile, lines: List[str]
    ) -> List[AntiPatternViolation]:
        """
        Detect god classes (classes with too many lines).

        God classes violate Single Responsibility Principle and are
        hard to test, maintain, and understand.
        """
        violations = []

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                if hasattr(node, "end_lineno") and node.end_lineno:
                    class_lines = node.end_lineno - node.lineno + 1

                    if class_lines > self.max_class_lines:
                        violations.append(AntiPatternViolation(
                            pattern_id="god-class",
                            pattern_name="God Class",
                            severity=AntiPatternSeverity.HIGH,
                            message=f"Class '{node.name}' has {class_lines} lines (max: {self.max_class_lines})",
                            file_path=code_file.path,
                            line=node.lineno,
                            column=node.col_offset,
                            code_snippet=f"class {node.name}:  # {class_lines} lines",
                            suggestion="Split into smaller, focused classes using composition",
                            is_blocker=False,
                        ))

        return violations

    def _detect_unsafe_singleton(
        self, tree: ast.AST, code_file: CodeFile, lines: List[str]
    ) -> List[AntiPatternViolation]:
        """
        Detect thread-unsafe singleton patterns.

        Pattern: if cls._instance is None: cls._instance = ...
        This is not thread-safe and can create multiple instances.
        """
        violations = []

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                # Look for _instance class attribute
                has_instance_attr = False
                singleton_check_line = None

                for item in node.body:
                    # Check for _instance = None
                    if isinstance(item, ast.AnnAssign):
                        if isinstance(item.target, ast.Name) and item.target.id == "_instance":
                            has_instance_attr = True
                    elif isinstance(item, ast.Assign):
                        for target in item.targets:
                            if isinstance(target, ast.Name) and target.id == "_instance":
                                has_instance_attr = True

                    # Check for get_instance method with if not cls._instance
                    if isinstance(item, ast.FunctionDef) and item.name in ("get_instance", "instance", "getInstance"):
                        for stmt in ast.walk(item):
                            if isinstance(stmt, ast.If):
                                # Check for "if not cls._instance" or "if cls._instance is None"
                                test = stmt.test
                                if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
                                    if isinstance(test.operand, ast.Attribute):
                                        if test.operand.attr == "_instance":
                                            singleton_check_line = stmt.lineno
                                elif isinstance(test, ast.Compare):
                                    if isinstance(test.left, ast.Attribute):
                                        if test.left.attr == "_instance":
                                            singleton_check_line = stmt.lineno

                if has_instance_attr and singleton_check_line:
                    violations.append(AntiPatternViolation(
                        pattern_id="thread-unsafe-singleton",
                        pattern_name="Thread-Unsafe Singleton",
                        severity=AntiPatternSeverity.CRITICAL,
                        message=f"Class '{node.name}' has thread-unsafe singleton pattern",
                        file_path=code_file.path,
                        line=singleton_check_line,
                        column=0,
                        code_snippet=self._get_line(lines, singleton_check_line),
                        suggestion="Use threading.Lock() or dependency injection instead",
                        is_blocker=True,
                    ))

        return violations

    def _detect_generic_exception_raise(
        self, tree: ast.AST, code_file: CodeFile, lines: List[str]
    ) -> List[AntiPatternViolation]:
        """
        Detect raising generic Exception.

        Anti-pattern: raise Exception("message")
        Should use: raise SpecificError("message")
        """
        violations = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Raise):
                exc = node.exc

                # raise Exception(...)
                if isinstance(exc, ast.Call):
                    if isinstance(exc.func, ast.Name):
                        if exc.func.id in ("Exception", "BaseException"):
                            violations.append(AntiPatternViolation(
                                pattern_id="generic-exception-raise",
                                pattern_name="Generic Exception Raise",
                                severity=AntiPatternSeverity.HIGH,
                                message=f"Raising generic '{exc.func.id}' instead of specific exception type",
                                file_path=code_file.path,
                                line=node.lineno,
                                column=node.col_offset,
                                code_snippet=self._get_line(lines, node.lineno),
                                suggestion="Define and raise a specific exception class",
                                is_blocker=False,
                            ))

        return violations

    def _detect_debug_prints(
        self, tree: ast.AST, code_file: CodeFile, lines: List[str]
    ) -> List[AntiPatternViolation]:
        """
        Detect debug print statements.

        Patterns:
        - print("DEBUG...")
        - print(f"...{var}...")  (likely debug)
        - print("debug...")
        """
        violations = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                # Check for print() call
                if isinstance(node.func, ast.Name) and node.func.id == "print":
                    is_debug = False

                    if node.args:
                        first_arg = node.args[0]

                        # Check string literals
                        if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                            value_lower = first_arg.value.lower()
                            if any(marker in value_lower for marker in ["debug", "todo", "fixme", "xxx", "hack"]):
                                is_debug = True

                        # Check f-strings (JoinedStr) - likely debug output
                        elif isinstance(first_arg, ast.JoinedStr):
                            # F-strings with variables are often debug statements
                            has_format_value = any(
                                isinstance(v, ast.FormattedValue)
                                for v in first_arg.values
                            )
                            # Check if any part contains DEBUG
                            for v in first_arg.values:
                                if isinstance(v, ast.Constant) and isinstance(v.value, str):
                                    if "debug" in v.value.lower():
                                        is_debug = True
                                        break

                    if is_debug:
                        violations.append(AntiPatternViolation(
                            pattern_id="debug-print",
                            pattern_name="Debug Print Statement",
                            severity=AntiPatternSeverity.MEDIUM,
                            message="Debug print() statement found - use logger instead",
                            file_path=code_file.path,
                            line=node.lineno,
                            column=node.col_offset,
                            code_snippet=self._get_line(lines, node.lineno),
                            suggestion="Use logger.debug() for debug output",
                            is_blocker=False,
                        ))

        return violations

    def _detect_builtin_shadowing(
        self, tree: ast.AST, code_file: CodeFile, lines: List[str]
    ) -> List[AntiPatternViolation]:
        """
        Detect shadowing of Python built-in names.

        Anti-patterns:
        - class TimeoutError(Exception):  # Shadows asyncio.TimeoutError
        - id = get_id()  # Shadows built-in id()
        - type = "user"  # Shadows built-in type()
        """
        violations = []

        for node in ast.walk(tree):
            # Check class definitions
            if isinstance(node, ast.ClassDef):
                if node.name in PYTHON_BUILTINS:
                    violations.append(AntiPatternViolation(
                        pattern_id="builtin-shadow-class",
                        pattern_name="Built-in Class Shadowing",
                        severity=AntiPatternSeverity.HIGH,
                        message=f"Class '{node.name}' shadows Python built-in",
                        file_path=code_file.path,
                        line=node.lineno,
                        column=node.col_offset,
                        code_snippet=self._get_line(lines, node.lineno),
                        suggestion=f"Rename to a more specific name (e.g., Operation{node.name}, Custom{node.name})",
                        is_blocker=False,
                    ))

            # Check function definitions
            elif isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                if node.name in PYTHON_BUILTINS:
                    violations.append(AntiPatternViolation(
                        pattern_id="builtin-shadow-function",
                        pattern_name="Built-in Function Shadowing",
                        severity=AntiPatternSeverity.MEDIUM,
                        message=f"Function '{node.name}' shadows Python built-in",
                        file_path=code_file.path,
                        line=node.lineno,
                        column=node.col_offset,
                        code_snippet=self._get_line(lines, node.lineno),
                        suggestion=f"Rename to a more specific name",
                        is_blocker=False,
                    ))

            # Check variable assignments (only at module/class level to reduce noise)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in PYTHON_BUILTINS:
                        # Skip common false positives in type hints
                        if target.id in ("type", "id"):
                            violations.append(AntiPatternViolation(
                                pattern_id="builtin-shadow-variable",
                                pattern_name="Built-in Variable Shadowing",
                                severity=AntiPatternSeverity.MEDIUM,
                                message=f"Variable '{target.id}' shadows Python built-in",
                                file_path=code_file.path,
                                line=node.lineno,
                                column=target.col_offset,
                                code_snippet=self._get_line(lines, node.lineno),
                                suggestion=f"Rename to 'entity_{target.id}' or similar",
                                is_blocker=False,
                            ))

        return violations

    def _detect_missing_await(
        self, tree: ast.AST, code_file: CodeFile, lines: List[str]
    ) -> List[AntiPatternViolation]:
        """
        Detect potentially missing await on async function calls.

        This is a heuristic check - looks for calls to *_async functions
        without await.
        """
        violations = []

        # Collect all async function names in the file
        async_func_names: Set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef):
                async_func_names.add(node.name)

        # Also check for common async patterns
        async_suffixes = ("_async", "_coroutine")

        # Walk and check calls
        for node in ast.walk(tree):
            if isinstance(node, ast.Expr):
                # Standalone expression (not assigned, not awaited)
                if isinstance(node.value, ast.Call):
                    call = node.value
                    func_name = None

                    if isinstance(call.func, ast.Name):
                        func_name = call.func.id
                    elif isinstance(call.func, ast.Attribute):
                        func_name = call.func.attr

                    if func_name:
                        # Check if it's an async function call without await
                        is_async_call = (
                            func_name in async_func_names or
                            any(func_name.endswith(suffix) for suffix in async_suffixes)
                        )

                        if is_async_call:
                            violations.append(AntiPatternViolation(
                                pattern_id="missing-await",
                                pattern_name="Missing Await",
                                severity=AntiPatternSeverity.HIGH,
                                message=f"Async function '{func_name}' called without await",
                                file_path=code_file.path,
                                line=node.lineno,
                                column=node.col_offset,
                                code_snippet=self._get_line(lines, node.lineno),
                                suggestion=f"Add 'await' before the call: await {func_name}(...)",
                                is_blocker=False,
                            ))

        return violations

    def _detect_todo_fixme(
        self, code_file: CodeFile, lines: List[str]
    ) -> List[AntiPatternViolation]:
        """
        Detect TODO, FIXME, XXX, HACK comments.

        These indicate technical debt that should be tracked.
        """
        violations = []

        # Patterns to detect
        patterns = [
            (r"#\s*(TODO|FIXME|XXX|HACK)\s*:?\s*(.*)", "todo-fixme"),
            (r"//\s*(TODO|FIXME|XXX|HACK)\s*:?\s*(.*)", "todo-fixme"),  # For mixed files
        ]

        for line_num, line in enumerate(lines, start=1):
            for pattern, pattern_id in patterns:
                match = re.search(pattern, line, re.IGNORECASE)
                if match:
                    marker = match.group(1).upper()
                    description = match.group(2).strip() if match.group(2) else ""

                    violations.append(AntiPatternViolation(
                        pattern_id=pattern_id,
                        pattern_name=f"{marker} Comment",
                        severity=AntiPatternSeverity.LOW,
                        message=f"{marker} found: {description[:50]}..." if len(description) > 50 else f"{marker} found: {description}" if description else f"{marker} marker found",
                        file_path=code_file.path,
                        line=line_num,
                        column=match.start(),
                        code_snippet=line.strip(),
                        suggestion="Convert to a tracked issue or resolve it",
                        is_blocker=False,
                    ))

        return violations

    # =========================================================================
    # HELPERS
    # =========================================================================

    def _is_test_file(self, file_path: str) -> bool:
        """Check if file is a test file."""
        path = Path(file_path)
        return (
            "test" in path.parts or
            path.name.startswith("test_") or
            path.name.endswith("_test.py") or
            "tests" in path.parts
        )

    def _get_line(self, lines: List[str], line_num: int) -> str:
        """Get a line from the file (1-indexed)."""
        if 1 <= line_num <= len(lines):
            return lines[line_num - 1].strip()
        return ""

    def _violations_to_findings(
        self, violations: List[AntiPatternViolation]
    ) -> List[Finding]:
        """Convert violations to Frame findings."""
        findings = []

        for v in violations:
            severity_map = {
                AntiPatternSeverity.CRITICAL: "critical",
                AntiPatternSeverity.HIGH: "high",
                AntiPatternSeverity.MEDIUM: "medium",
                AntiPatternSeverity.LOW: "low",
            }

            location = f"{Path(v.file_path).name}:{v.line}"

            remediation = None
            if v.suggestion:
                remediation = Remediation(
                    description=v.suggestion,
                    code="",  # No auto-fix for now
                )

            finding = Finding(
                id=v.pattern_id,
                severity=severity_map.get(v.severity, "medium"),
                message=v.message,
                location=location,
                line=v.line,
                column=v.column,
                detail=f"**Pattern:** {v.pattern_name}\n\n**Code:**\n```python\n{v.code_snippet}\n```\n\n**Suggestion:** {v.suggestion}",
                code=v.code_snippet,
                is_blocker=v.is_blocker,
                remediation=remediation,
            )
            findings.append(finding)

        return findings

    def _create_skipped_result(self, start_time: float, reason: str) -> FrameResult:
        """Create a skipped result."""
        duration = time.perf_counter() - start_time
        return FrameResult(
            frame_id=self.frame_id,
            frame_name=self.name,
            status="passed",
            duration=duration,
            issues_found=0,
            is_blocker=False,
            findings=[],
            metadata={"skipped": True, "reason": reason},
        )
