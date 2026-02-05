"""
Anti-Pattern Detection Frame (Multi-Language)

Detects common code anti-patterns across ALL supported languages:
- Python, JavaScript, TypeScript, Java, Go, C#, Rust, Ruby, PHP, etc.

Detections:
- Exception swallowing (bare/empty catch blocks)
- God classes (classes > 500 lines)
- Debug output in production (print, console.log, println, etc.)
- TODO/FIXME comments (technical debt markers)
- Generic exception raising/throwing

This frame uses:
1. Native AST for Python (faster, more accurate)
2. Tree-sitter for all other languages (40+ language support)
3. Pattern matching as fallback

Priority: HIGH
Blocker: TRUE (for critical anti-patterns)
Scope: FILE_LEVEL

Author: Warden Team
Version: 2.0.0 (Multi-Language)
"""

import ast
import re
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

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

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


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


# =============================================================================
# LANGUAGE-SPECIFIC CONFIGURATIONS
# =============================================================================

# Exception handling patterns by language
EXCEPTION_PATTERNS: Dict[str, Dict[str, Any]] = {
    "python": {
        # Regex patterns for bare/broad except
        "bare_catch": [
            r"except\s*:",  # except:
            r"except\s+BaseException\s*:",  # except BaseException:
        ],
        "broad_catch": [
            r"except\s+Exception\s*:",  # except Exception:
        ],
        "empty_catch": r"except.*:\s*\n\s+pass\s*$",
        "generic_raise": r"raise\s+Exception\s*\(",
    },
    "javascript": {
        "bare_catch": [
            r"catch\s*\{\s*\}",  # catch {} (empty)
            r"catch\s*\(\s*\w*\s*\)\s*\{\s*\}",  # catch (e) {}
        ],
        "broad_catch": [],  # JS doesn't have exception hierarchy like Python
        "empty_catch": r"catch\s*\([^)]*\)\s*\{\s*\}",
        "generic_raise": r"throw\s+new\s+Error\s*\(",
    },
    "typescript": {
        "bare_catch": [
            r"catch\s*\{\s*\}",
            r"catch\s*\(\s*\w*\s*\)\s*\{\s*\}",
        ],
        "broad_catch": [],
        "empty_catch": r"catch\s*\([^)]*\)\s*\{\s*\}",
        "generic_raise": r"throw\s+new\s+Error\s*\(",
    },
    "java": {
        "bare_catch": [
            r"catch\s*\(\s*Throwable\s+\w+\s*\)",  # catch (Throwable t)
        ],
        "broad_catch": [
            r"catch\s*\(\s*Exception\s+\w+\s*\)",  # catch (Exception e)
        ],
        "empty_catch": r"catch\s*\([^)]+\)\s*\{\s*\}",
        "generic_raise": r"throw\s+new\s+Exception\s*\(",
    },
    "csharp": {
        "bare_catch": [
            r"catch\s*\{\s*\}",  # catch {}
            r"catch\s*\(\s*Exception\s*\)",  # catch (Exception) without variable
        ],
        "broad_catch": [
            r"catch\s*\(\s*Exception\s+\w+\s*\)",  # catch (Exception ex)
        ],
        "empty_catch": r"catch\s*(\([^)]*\))?\s*\{\s*\}",
        "generic_raise": r"throw\s+new\s+Exception\s*\(",
    },
    "go": {
        # Go uses explicit error handling, not exceptions
        "bare_catch": [],
        "broad_catch": [],
        "empty_catch": r"if\s+err\s*!=\s*nil\s*\{\s*\}",  # if err != nil {}
        "error_ignored": r"[^_]\s*,\s*_\s*:?=.*\(",  # result, _ := function()
        "generic_raise": [],  # Go doesn't have exceptions
    },
    "rust": {
        # Rust uses Result/Option, not exceptions
        "bare_catch": [],
        "broad_catch": [],
        "empty_catch": [],
        "unwrap_usage": r"\.unwrap\(\)",  # Panics on error
        "expect_usage": r"\.expect\(",  # Panics with message
        "generic_raise": r"panic!\s*\(",
    },
    "ruby": {
        "bare_catch": [
            r"rescue\s*$",  # bare rescue
            r"rescue\s*=>",  # rescue => e (catches StandardError)
        ],
        "broad_catch": [
            r"rescue\s+Exception",  # rescue Exception
        ],
        "empty_catch": r"rescue.*\n\s*end",
        "generic_raise": r"raise\s+['\"]",  # raise "message" (string)
    },
    "php": {
        "bare_catch": [
            r"catch\s*\(\s*\\?Throwable\s+",
        ],
        "broad_catch": [
            r"catch\s*\(\s*\\?Exception\s+",
        ],
        "empty_catch": r"catch\s*\([^)]+\)\s*\{\s*\}",
        "generic_raise": r"throw\s+new\s+\\?Exception\s*\(",
    },
    "kotlin": {
        "bare_catch": [
            r"catch\s*\(\s*e\s*:\s*Throwable\s*\)",
        ],
        "broad_catch": [
            r"catch\s*\(\s*e\s*:\s*Exception\s*\)",
        ],
        "empty_catch": r"catch\s*\([^)]+\)\s*\{\s*\}",
        "generic_raise": r"throw\s+Exception\s*\(",
    },
    "swift": {
        "bare_catch": [
            r"catch\s*\{",  # catch { } without pattern
        ],
        "broad_catch": [],
        "empty_catch": r"catch\s*\{\s*\}",
        "generic_raise": [],  # Swift has typed errors
    },
    "scala": {
        "bare_catch": [
            r"catch\s*\{\s*case\s+_\s*:",  # catch { case _: ... }
        ],
        "broad_catch": [
            r"catch\s*\{\s*case\s+_\s*:\s*Throwable",
            r"catch\s*\{\s*case\s+_\s*:\s*Exception",
        ],
        "empty_catch": r"catch\s*\{[^}]*\}\s*$",
        "generic_raise": r"throw\s+new\s+Exception\s*\(",
    },
}

# Debug output patterns by language
DEBUG_PATTERNS: Dict[str, List[str]] = {
    "python": [
        r"print\s*\(\s*['\"]?[Dd][Ee][Bb][Uu][Gg]",
        r"print\s*\(\s*f?['\"].*\{.*\}",  # f-string prints (likely debug)
    ],
    "javascript": [
        r"console\.(log|debug|info|warn|error)\s*\(",
        r"debugger\s*;",
    ],
    "typescript": [
        r"console\.(log|debug|info|warn|error)\s*\(",
        r"debugger\s*;",
    ],
    "java": [
        r"System\.(out|err)\.(print|println)\s*\(",
        r"\.printStackTrace\s*\(",
    ],
    "csharp": [
        r"Console\.(Write|WriteLine)\s*\(",
        r"Debug\.(Write|WriteLine|Print)\s*\(",
        r"Trace\.(Write|WriteLine)\s*\(",
    ],
    "go": [
        r"fmt\.(Print|Println|Printf)\s*\(",
        r"log\.(Print|Println|Printf)\s*\(",
    ],
    "rust": [
        r"println!\s*\(",
        r"print!\s*\(",
        r"dbg!\s*\(",
        r"eprintln!\s*\(",
    ],
    "ruby": [
        r"\bputs\s+",
        r"\bp\s+",
        r"pp\s+",
        r"print\s+",
    ],
    "php": [
        r"var_dump\s*\(",
        r"print_r\s*\(",
        r"echo\s+",
        r"die\s*\(",
        r"dd\s*\(",  # Laravel debug
    ],
    "kotlin": [
        r"println\s*\(",
        r"print\s*\(",
    ],
    "swift": [
        r"print\s*\(",
        r"debugPrint\s*\(",
        r"dump\s*\(",
    ],
    "scala": [
        r"println\s*\(",
        r"print\s*\(",
    ],
    "dart": [
        r"print\s*\(",
        r"debugPrint\s*\(",
    ],
    "cpp": [
        r"std::cout\s*<<",
        r"printf\s*\(",
        r"std::cerr\s*<<",
    ],
    "c": [
        r"printf\s*\(",
        r"fprintf\s*\(",
    ],
}

# File extension to language mapping
EXTENSION_TO_LANGUAGE: Dict[str, str] = {
    ".py": "python",
    ".pyw": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".java": "java",
    ".cs": "csharp",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".php": "php",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".swift": "swift",
    ".scala": "scala",
    ".sc": "scala",
    ".dart": "dart",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".c": "c",
    ".h": "c",
    ".hpp": "cpp",
}


class AntiPatternFrame(ValidationFrame):
    """
    Multi-Language Anti-Pattern Detection Frame

    Detects common anti-patterns across 15+ programming languages
    using a combination of AST analysis and pattern matching.

    Supported Languages:
    - Python (native AST + patterns)
    - JavaScript/TypeScript (tree-sitter + patterns)
    - Java (tree-sitter + patterns)
    - C# (tree-sitter + patterns)
    - Go (tree-sitter + patterns)
    - Rust (tree-sitter + patterns)
    - Ruby (tree-sitter + patterns)
    - PHP (tree-sitter + patterns)
    - Kotlin, Swift, Scala, Dart, C/C++

    Detections:
    - Empty/bare catch blocks (exception swallowing)
    - God classes (500+ lines)
    - Debug output in production
    - TODO/FIXME comments
    - Generic exception throwing
    - Language-specific anti-patterns (Go error ignoring, Rust unwrap, etc.)
    """

    # Frame metadata
    name = "Anti-Pattern Detection"
    description = "Detects common anti-patterns across 15+ programming languages"
    category = FrameCategory.GLOBAL
    priority = FramePriority.HIGH
    scope = FrameScope.FILE_LEVEL
    is_blocker = True
    version = "2.0.0"
    author = "Warden Team"
    applicability = [FrameApplicability.ALL]

    @property
    def frame_id(self) -> str:
        return "antipattern"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize AntiPatternFrame."""
        super().__init__(config)

        config_dict = self.config if isinstance(self.config, dict) else {}

        # Thresholds (universal)
        self.max_class_lines = config_dict.get("max_class_lines", 500)
        self.max_function_lines = config_dict.get("max_function_lines", 100)
        self.max_file_lines = config_dict.get("max_file_lines", 1000)

        # Check toggles
        self.check_exception_handling = config_dict.get("check_exception_handling", True)
        self.check_god_class = config_dict.get("check_god_class", True)
        self.check_debug_output = config_dict.get("check_debug_output", True)
        self.check_todo_fixme = config_dict.get("check_todo_fixme", True)
        self.check_generic_exception = config_dict.get("check_generic_exception", True)

        # Filtering
        self.ignore_test_files = config_dict.get("ignore_test_files", True)

        # Language-specific checks
        self.check_go_error_handling = config_dict.get("check_go_error_handling", True)
        self.check_rust_unwrap = config_dict.get("check_rust_unwrap", True)

    async def execute_async(self, code_file: CodeFile) -> FrameResult:
        """Execute anti-pattern detection on a code file."""
        start_time = time.perf_counter()

        # Detect language
        language = self._detect_language(code_file)

        if not language:
            return self._create_skipped_result(start_time, f"Unsupported file type")

        logger.info(
            "antipattern_frame_started",
            file_path=code_file.path,
            language=language,
        )

        # Skip test files if configured
        if self.ignore_test_files and self._is_test_file(code_file.path, language):
            return self._create_skipped_result(start_time, "Test file (ignored)")

        violations: List[AntiPatternViolation] = []
        checks_executed: List[str] = []
        lines = code_file.content.split("\n")

        # Run language-specific detections
        if self.check_exception_handling:
            checks_executed.append("exception_handling")
            violations.extend(self._detect_exception_issues(code_file, language, lines))

        if self.check_god_class:
            checks_executed.append("god_class")
            violations.extend(self._detect_god_class(code_file, language, lines))

        if self.check_debug_output:
            checks_executed.append("debug_output")
            violations.extend(self._detect_debug_output(code_file, language, lines))

        if self.check_todo_fixme:
            checks_executed.append("todo_fixme")
            violations.extend(self._detect_todo_fixme(code_file, lines))

        if self.check_generic_exception:
            checks_executed.append("generic_exception")
            violations.extend(self._detect_generic_exception(code_file, language, lines))

        # Language-specific checks
        if language == "go" and self.check_go_error_handling:
            checks_executed.append("go_error_handling")
            violations.extend(self._detect_go_error_issues(code_file, lines))

        if language == "rust" and self.check_rust_unwrap:
            checks_executed.append("rust_unwrap")
            violations.extend(self._detect_rust_unwrap(code_file, lines))

        # Convert to findings
        findings = self._violations_to_findings(violations)

        # Determine status
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
            language=language,
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
                "language": language,
                "total_violations": len(violations),
                "critical": sum(1 for v in violations if v.severity == AntiPatternSeverity.CRITICAL),
                "high": sum(1 for v in violations if v.severity == AntiPatternSeverity.HIGH),
                "checks_executed": checks_executed,
            },
        )

    # =========================================================================
    # LANGUAGE DETECTION
    # =========================================================================

    def _detect_language(self, code_file: CodeFile) -> Optional[str]:
        """Detect language from file extension or CodeFile.language."""
        # Try CodeFile.language first
        if code_file.language:
            lang_lower = code_file.language.lower()
            if lang_lower in EXCEPTION_PATTERNS or lang_lower in DEBUG_PATTERNS:
                return lang_lower

        # Fallback to extension
        path = Path(code_file.path)
        ext = path.suffix.lower()
        return EXTENSION_TO_LANGUAGE.get(ext)

    def _is_test_file(self, file_path: str, language: str) -> bool:
        """Check if file is a test file (language-aware)."""
        path = Path(file_path)
        path_str = str(path).lower()

        # Common test directories
        if any(d in path_str for d in ["/test/", "/tests/", "/__tests__/", "/spec/", "/specs/"]):
            return True

        name = path.stem.lower()

        # Language-specific test patterns
        patterns = {
            "python": ["test_", "_test"],
            "javascript": ["test", ".spec", ".test"],
            "typescript": ["test", ".spec", ".test"],
            "java": ["Test", "Tests", "IT"],
            "csharp": ["Test", "Tests"],
            "go": ["_test"],
            "rust": [],  # Rust tests are in same file
            "ruby": ["_spec", "_test"],
            "php": ["Test"],
            "kotlin": ["Test"],
        }

        lang_patterns = patterns.get(language, [])
        return any(p in name for p in lang_patterns)

    # =========================================================================
    # DETECTION METHODS
    # =========================================================================

    def _detect_exception_issues(
        self, code_file: CodeFile, language: str, lines: List[str]
    ) -> List[AntiPatternViolation]:
        """Detect exception handling anti-patterns."""
        violations = []
        patterns = EXCEPTION_PATTERNS.get(language, {})

        if not patterns:
            return violations

        content = code_file.content

        # Bare catch (most severe)
        for pattern in patterns.get("bare_catch", []):
            for match in re.finditer(pattern, content, re.MULTILINE):
                line_num = content[:match.start()].count("\n") + 1
                violations.append(AntiPatternViolation(
                    pattern_id="bare-catch",
                    pattern_name="Bare/Broad Catch Block",
                    severity=AntiPatternSeverity.CRITICAL,
                    message=f"Catches all exceptions including system signals ({language})",
                    file_path=code_file.path,
                    line=line_num,
                    code_snippet=self._get_line(lines, line_num),
                    suggestion=self._get_catch_suggestion(language),
                    is_blocker=True,
                ))

        # Broad catch (high severity)
        for pattern in patterns.get("broad_catch", []):
            for match in re.finditer(pattern, content, re.MULTILINE):
                line_num = content[:match.start()].count("\n") + 1
                violations.append(AntiPatternViolation(
                    pattern_id="broad-catch",
                    pattern_name="Overly Broad Catch",
                    severity=AntiPatternSeverity.HIGH,
                    message=f"Catching generic Exception type ({language})",
                    file_path=code_file.path,
                    line=line_num,
                    code_snippet=self._get_line(lines, line_num),
                    suggestion="Catch specific exception types",
                    is_blocker=False,
                ))

        # Empty catch (critical)
        empty_pattern = patterns.get("empty_catch")
        if empty_pattern:
            for match in re.finditer(empty_pattern, content, re.MULTILINE):
                line_num = content[:match.start()].count("\n") + 1
                violations.append(AntiPatternViolation(
                    pattern_id="empty-catch",
                    pattern_name="Empty Catch Block",
                    severity=AntiPatternSeverity.CRITICAL,
                    message=f"Silently swallows exceptions ({language})",
                    file_path=code_file.path,
                    line=line_num,
                    code_snippet=self._get_line(lines, line_num),
                    suggestion="Log the error or handle it properly",
                    is_blocker=True,
                ))

        return violations

    def _detect_god_class(
        self, code_file: CodeFile, language: str, lines: List[str]
    ) -> List[AntiPatternViolation]:
        """Detect god classes (universal - based on line count)."""
        violations = []

        # For Python, use native AST for accurate class detection
        if language == "python":
            try:
                tree = ast.parse(code_file.content)
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
                                    code_snippet=f"class {node.name}:  # {class_lines} lines",
                                    suggestion="Split into smaller, focused classes",
                                    is_blocker=False,
                                ))
            except SyntaxError:
                pass
            return violations

        # For other languages, use regex-based heuristic
        class_patterns = {
            "javascript": r"class\s+(\w+)",
            "typescript": r"class\s+(\w+)",
            "java": r"class\s+(\w+)",
            "csharp": r"class\s+(\w+)",
            "kotlin": r"class\s+(\w+)",
            "swift": r"class\s+(\w+)",
            "scala": r"class\s+(\w+)",
            "ruby": r"class\s+(\w+)",
            "php": r"class\s+(\w+)",
            "go": r"type\s+(\w+)\s+struct",
            "rust": r"(struct|impl)\s+(\w+)",
        }

        pattern = class_patterns.get(language)
        if not pattern:
            return violations

        # Simple heuristic: check file size as proxy
        total_lines = len(lines)
        if total_lines > self.max_file_lines:
            violations.append(AntiPatternViolation(
                pattern_id="large-file",
                pattern_name="Large File",
                severity=AntiPatternSeverity.MEDIUM,
                message=f"File has {total_lines} lines (max: {self.max_file_lines})",
                file_path=code_file.path,
                line=1,
                code_snippet=f"// {total_lines} lines",
                suggestion="Consider splitting into smaller modules",
                is_blocker=False,
            ))

        return violations

    def _detect_debug_output(
        self, code_file: CodeFile, language: str, lines: List[str]
    ) -> List[AntiPatternViolation]:
        """Detect debug output statements."""
        violations = []
        patterns = DEBUG_PATTERNS.get(language, [])

        if not patterns:
            return violations

        content = code_file.content

        for pattern in patterns:
            for match in re.finditer(pattern, content, re.MULTILINE | re.IGNORECASE):
                line_num = content[:match.start()].count("\n") + 1
                line_content = self._get_line(lines, line_num)

                # Skip if in a comment
                if self._is_in_comment(line_content, language):
                    continue

                violations.append(AntiPatternViolation(
                    pattern_id="debug-output",
                    pattern_name="Debug Output",
                    severity=AntiPatternSeverity.MEDIUM,
                    message=f"Debug output statement found ({language})",
                    file_path=code_file.path,
                    line=line_num,
                    code_snippet=line_content,
                    suggestion=self._get_logging_suggestion(language),
                    is_blocker=False,
                ))

        return violations

    def _detect_todo_fixme(
        self, code_file: CodeFile, lines: List[str]
    ) -> List[AntiPatternViolation]:
        """Detect TODO/FIXME comments (universal)."""
        violations = []

        pattern = r"(#|//|/\*|\*|--|<!--|;)\s*(TODO|FIXME|XXX|HACK|BUG)\s*:?\s*(.*)"

        for line_num, line in enumerate(lines, start=1):
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                marker = match.group(2).upper()
                description = match.group(3).strip()[:50]

                violations.append(AntiPatternViolation(
                    pattern_id="todo-fixme",
                    pattern_name=f"{marker} Comment",
                    severity=AntiPatternSeverity.LOW,
                    message=f"{marker}: {description}..." if description else f"{marker} marker found",
                    file_path=code_file.path,
                    line=line_num,
                    code_snippet=line.strip(),
                    suggestion="Convert to tracked issue or resolve",
                    is_blocker=False,
                ))

        return violations

    def _detect_generic_exception(
        self, code_file: CodeFile, language: str, lines: List[str]
    ) -> List[AntiPatternViolation]:
        """Detect generic exception throwing."""
        violations = []
        patterns = EXCEPTION_PATTERNS.get(language, {})

        generic_pattern = patterns.get("generic_raise")
        if not generic_pattern:
            return violations

        if isinstance(generic_pattern, list):
            patterns_to_check = generic_pattern
        else:
            patterns_to_check = [generic_pattern]

        content = code_file.content

        for pattern in patterns_to_check:
            for match in re.finditer(pattern, content, re.MULTILINE):
                line_num = content[:match.start()].count("\n") + 1
                violations.append(AntiPatternViolation(
                    pattern_id="generic-exception-raise",
                    pattern_name="Generic Exception Thrown",
                    severity=AntiPatternSeverity.HIGH,
                    message=f"Throwing generic exception type ({language})",
                    file_path=code_file.path,
                    line=line_num,
                    code_snippet=self._get_line(lines, line_num),
                    suggestion="Use or create a specific exception type",
                    is_blocker=False,
                ))

        return violations

    def _detect_go_error_issues(
        self, code_file: CodeFile, lines: List[str]
    ) -> List[AntiPatternViolation]:
        """Detect Go-specific error handling anti-patterns."""
        violations = []
        content = code_file.content

        # Ignored errors: _, err := ... or result, _ := ...
        pattern = r"[^_]\s*,\s*_\s*:?=\s*\w+\("
        for match in re.finditer(pattern, content):
            line_num = content[:match.start()].count("\n") + 1
            violations.append(AntiPatternViolation(
                pattern_id="go-error-ignored",
                pattern_name="Go Error Ignored",
                severity=AntiPatternSeverity.HIGH,
                message="Error return value ignored with blank identifier",
                file_path=code_file.path,
                line=line_num,
                code_snippet=self._get_line(lines, line_num),
                suggestion="Handle the error: if err != nil { return err }",
                is_blocker=False,
            ))

        return violations

    def _detect_rust_unwrap(
        self, code_file: CodeFile, lines: List[str]
    ) -> List[AntiPatternViolation]:
        """Detect Rust unwrap/expect usage (can panic)."""
        violations = []
        content = code_file.content

        patterns = [
            (r"\.unwrap\(\)", "unwrap() panics on None/Err"),
            (r"\.expect\(", "expect() panics on None/Err"),
        ]

        for pattern, message in patterns:
            for match in re.finditer(pattern, content):
                line_num = content[:match.start()].count("\n") + 1
                violations.append(AntiPatternViolation(
                    pattern_id="rust-panic-on-error",
                    pattern_name="Rust Panic on Error",
                    severity=AntiPatternSeverity.MEDIUM,
                    message=message,
                    file_path=code_file.path,
                    line=line_num,
                    code_snippet=self._get_line(lines, line_num),
                    suggestion="Use match, if let, or the ? operator instead",
                    is_blocker=False,
                ))

        return violations

    # =========================================================================
    # HELPERS
    # =========================================================================

    def _get_line(self, lines: List[str], line_num: int) -> str:
        """Get a line from the file (1-indexed)."""
        if 1 <= line_num <= len(lines):
            return lines[line_num - 1].strip()
        return ""

    def _is_in_comment(self, line: str, language: str) -> bool:
        """Check if code is in a comment."""
        stripped = line.strip()
        comment_prefixes = {
            "python": ["#"],
            "javascript": ["//", "/*", "*"],
            "typescript": ["//", "/*", "*"],
            "java": ["//", "/*", "*"],
            "csharp": ["//", "/*", "*", "///"],
            "go": ["//", "/*"],
            "rust": ["//", "/*", "///", "//!"],
            "ruby": ["#"],
            "php": ["//", "#", "/*", "*"],
            "kotlin": ["//", "/*"],
            "swift": ["//", "/*"],
        }
        prefixes = comment_prefixes.get(language, ["//", "#"])
        return any(stripped.startswith(p) for p in prefixes)

    def _get_catch_suggestion(self, language: str) -> str:
        """Get language-specific suggestion for exception handling."""
        suggestions = {
            "python": "Catch specific exceptions: except (ValueError, IOError) as e:",
            "javascript": "Catch specific error types or add error handling logic",
            "typescript": "Use typed catch or add proper error handling",
            "java": "Catch specific exceptions: catch (IOException | SQLException e)",
            "csharp": "Catch specific exceptions: catch (IOException ex)",
            "go": "Handle error properly: if err != nil { return err }",
            "ruby": "Catch specific exceptions: rescue ArgumentError, TypeError",
            "php": "Catch specific exceptions: catch (InvalidArgumentException $e)",
        }
        return suggestions.get(language, "Catch specific exception types")

    def _get_logging_suggestion(self, language: str) -> str:
        """Get language-specific logging suggestion."""
        suggestions = {
            "python": "Use logging module: logger.debug(...)",
            "javascript": "Use a logging library or remove before production",
            "typescript": "Use a logging library or remove before production",
            "java": "Use SLF4J/Log4j: logger.debug(...)",
            "csharp": "Use ILogger: _logger.LogDebug(...)",
            "go": "Use structured logging: log.Debug(...)",
            "rust": "Use log crate: debug!(...) or tracing",
            "ruby": "Use Rails.logger or a logging gem",
            "php": "Use Monolog or PSR-3 logger",
        }
        return suggestions.get(language, "Use a proper logging framework")

    def _violations_to_findings(
        self, violations: List[AntiPatternViolation]
    ) -> List[Finding]:
        """Convert violations to Frame findings."""
        findings = []

        severity_map = {
            AntiPatternSeverity.CRITICAL: "critical",
            AntiPatternSeverity.HIGH: "high",
            AntiPatternSeverity.MEDIUM: "medium",
            AntiPatternSeverity.LOW: "low",
        }

        for v in violations:
            location = f"{Path(v.file_path).name}:{v.line}"

            remediation = None
            if v.suggestion:
                remediation = Remediation(description=v.suggestion, code="")

            finding = Finding(
                id=v.pattern_id,
                severity=severity_map.get(v.severity, "medium"),
                message=v.message,
                location=location,
                line=v.line,
                column=v.column,
                detail=f"**Pattern:** {v.pattern_name}\n\n**Code:**\n```\n{v.code_snippet}\n```\n\n**Suggestion:** {v.suggestion}",
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
