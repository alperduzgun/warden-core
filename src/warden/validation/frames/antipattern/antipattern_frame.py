"""
Anti-Pattern Detection Frame (Universal AST)

Detects common code anti-patterns across ALL Tree-sitter supported languages (50+).

Architecture:
1. ASTProviderRegistry → Best provider for language
2. Universal AST queries → Language-agnostic pattern detection
3. Regex fallback → When AST unavailable

Detections:
- Exception swallowing (bare/empty catch blocks)
- God classes (classes > 500 lines)
- Debug output in production
- TODO/FIXME comments (technical debt markers)
- Generic exception raising/throwing

Priority: HIGH
Blocker: TRUE (for critical anti-patterns)
Scope: FILE_LEVEL

Author: Warden Team
Version: 3.0.0 (Universal AST)
"""

import ast
import re
import time
from dataclasses import dataclass
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

# AST imports
from warden.ast.domain.models import ASTNode
from warden.ast.domain.enums import ASTNodeType, CodeLanguage
from warden.ast.application.provider_registry import ASTProviderRegistry

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
# UNIVERSAL AST NODE TYPE MAPPINGS
# =============================================================================

# Tree-sitter node types that represent try-catch/exception handling
TRY_CATCH_NODE_TYPES: Set[str] = {
    # Python
    "try_statement", "except_clause",
    # JavaScript/TypeScript
    "try_statement", "catch_clause",
    # Java/Kotlin
    "try_statement", "catch_clause", "try_with_resources_statement",
    # C#
    "try_statement", "catch_clause", "catch_declaration",
    # Go (error handling is different but we check for patterns)
    "if_statement",  # if err != nil {...}
    # Ruby
    "begin", "rescue", "rescue_block",
    # PHP
    "try_statement", "catch_clause",
    # Rust (Result/Option handling)
    "match_expression", "if_let_expression",
    # Swift
    "do_statement", "catch_clause",
    # Scala
    "try_expression", "catch_clause",
}

# Tree-sitter node types for class definitions
CLASS_NODE_TYPES: Set[str] = {
    # Python
    "class_definition",
    # JavaScript/TypeScript
    "class_declaration", "class",
    # Java
    "class_declaration", "interface_declaration",
    # C#
    "class_declaration", "interface_declaration", "struct_declaration",
    # Go
    "type_declaration", "type_spec",  # struct
    # Rust
    "struct_item", "impl_item", "trait_item",
    # Ruby
    "class", "module",
    # PHP
    "class_declaration", "interface_declaration",
    # Kotlin
    "class_declaration", "object_declaration",
    # Swift
    "class_declaration", "struct_declaration", "protocol_declaration",
    # Scala
    "class_definition", "object_definition", "trait_definition",
}

# Tree-sitter node types for function calls (debug output detection)
CALL_NODE_TYPES: Set[str] = {
    "call_expression", "call", "invocation_expression",
    "method_invocation", "function_call", "application",
}

# Debug function names by category (language-agnostic where possible)
DEBUG_FUNCTION_NAMES: Set[str] = {
    # Python
    "print", "pprint",
    # JavaScript/TypeScript (console methods detected separately)
    # Java
    "println", "print", "printStackTrace",
    # Go
    "Println", "Printf", "Print",
    # Rust
    "println!", "print!", "dbg!", "eprintln!",  # Rust macros
    # Ruby
    "puts", "p", "pp",
    # PHP
    "var_dump", "print_r", "dd", "dump", "die",
    # Kotlin
    "println", "print",
    # Swift
    "print", "debugPrint", "dump",
    # Scala
    "println", "print",
    # Dart
    "print", "debugPrint",
    # C/C++
    "printf", "fprintf", "cout",
}

# Debug member access patterns (e.g., console.log, System.out.println)
DEBUG_MEMBER_PATTERNS: Dict[str, Set[str]] = {
    "console": {"log", "debug", "info", "warn", "error", "trace"},
    "System.out": {"print", "println", "printf"},
    "System.err": {"print", "println", "printf"},
    "Debug": {"Write", "WriteLine", "Print"},
    "Trace": {"Write", "WriteLine"},
    "Console": {"Write", "WriteLine"},
    "fmt": {"Print", "Println", "Printf"},
    "log": {"Print", "Println", "Printf"},
    "std::cout": {"<<"},
    "std::cerr": {"<<"},
}


class AntiPatternFrame(ValidationFrame):
    """
    Universal Anti-Pattern Detection Frame (50+ Languages)

    Uses Universal AST via Tree-sitter for language-agnostic detection.
    Falls back to regex patterns when AST unavailable.

    Supported via Tree-sitter:
    - Python, JavaScript, TypeScript, Java, C#, Go, Rust, Ruby, PHP,
    - Kotlin, Swift, Scala, Dart, C, C++, and 35+ more languages

    Detections:
    - Empty/bare catch blocks (exception swallowing)
    - God classes (500+ lines)
    - Debug output in production
    - TODO/FIXME comments
    - Generic exception throwing
    - Language-specific anti-patterns
    """

    # Frame metadata
    name = "Anti-Pattern Detection"
    description = "Detects anti-patterns across 50+ languages using Universal AST"
    category = FrameCategory.GLOBAL
    priority = FramePriority.HIGH
    scope = FrameScope.FILE_LEVEL
    is_blocker = True
    version = "3.0.0"
    author = "Warden Team"
    applicability = [FrameApplicability.ALL]

    # Singleton registry instance (lazy loaded)
    _registry: Optional[ASTProviderRegistry] = None

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

        # Use AST when available
        self.prefer_ast = config_dict.get("prefer_ast", True)

    @classmethod
    def _get_registry(cls) -> ASTProviderRegistry:
        """Get or create AST provider registry (lazy singleton)."""
        if cls._registry is None:
            cls._registry = ASTProviderRegistry()
            # Register tree-sitter provider
            try:
                from warden.ast.providers.tree_sitter_provider import TreeSitterProvider
                cls._registry.register(TreeSitterProvider())
            except ImportError:
                logger.debug("tree_sitter_provider_not_available")
            # Register Python native provider if available
            try:
                from warden.ast.providers.python_provider import PythonASTProvider
                cls._registry.register(PythonASTProvider())
            except ImportError:
                pass
        return cls._registry

    async def execute_async(self, code_file: CodeFile) -> FrameResult:
        """Execute anti-pattern detection on a code file."""
        start_time = time.perf_counter()

        # Detect language from CodeFile or extension
        language = self._detect_language(code_file)

        if not language:
            return self._create_skipped_result(start_time, "Unsupported file type")

        logger.info(
            "antipattern_frame_started",
            file_path=code_file.path,
            language=language.value if isinstance(language, CodeLanguage) else language,
        )

        # Skip test files if configured
        if self.ignore_test_files and self._is_test_file(code_file.path):
            return self._create_skipped_result(start_time, "Test file (ignored)")

        violations: List[AntiPatternViolation] = []
        checks_executed: List[str] = []
        lines = code_file.content.split("\n")

        # Try to get Universal AST
        ast_root: Optional[ASTNode] = None
        if self.prefer_ast and isinstance(language, CodeLanguage):
            ast_root = await self._get_ast(code_file.content, language, code_file.path)

        # Run detections (AST-first with regex fallback)
        if self.check_exception_handling:
            checks_executed.append("exception_handling")
            violations.extend(
                self._detect_exception_issues_ast(code_file, language, lines, ast_root)
                if ast_root else
                self._detect_exception_issues_regex(code_file, language, lines)
            )

        if self.check_god_class:
            checks_executed.append("god_class")
            violations.extend(
                self._detect_god_class_ast(code_file, language, lines, ast_root)
                if ast_root else
                self._detect_god_class_regex(code_file, language, lines)
            )

        if self.check_debug_output:
            checks_executed.append("debug_output")
            violations.extend(
                self._detect_debug_output_ast(code_file, language, lines, ast_root)
                if ast_root else
                self._detect_debug_output_regex(code_file, language, lines)
            )

        if self.check_todo_fixme:
            checks_executed.append("todo_fixme")
            # TODO/FIXME is always regex-based (comment content)
            violations.extend(self._detect_todo_fixme(code_file, lines))

        if self.check_generic_exception:
            checks_executed.append("generic_exception")
            violations.extend(
                self._detect_generic_exception_ast(code_file, language, lines, ast_root)
                if ast_root else
                self._detect_generic_exception_regex(code_file, language, lines)
            )

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

        lang_str = language.value if isinstance(language, CodeLanguage) else str(language)
        logger.info(
            "antipattern_frame_completed",
            file_path=code_file.path,
            language=lang_str,
            status=status,
            violations=len(violations),
            duration=f"{duration:.2f}s",
            used_ast=ast_root is not None,
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
                "language": lang_str,
                "total_violations": len(violations),
                "critical": sum(1 for v in violations if v.severity == AntiPatternSeverity.CRITICAL),
                "high": sum(1 for v in violations if v.severity == AntiPatternSeverity.HIGH),
                "checks_executed": checks_executed,
                "used_ast": ast_root is not None,
            },
        )

    # =========================================================================
    # LANGUAGE DETECTION
    # =========================================================================

    def _detect_language(self, code_file: CodeFile) -> Optional[CodeLanguage]:
        """Detect language from file, returning CodeLanguage enum."""
        # Try LanguageRegistry first
        try:
            from warden.shared.languages.registry import LanguageRegistry
            lang = LanguageRegistry.get_language_from_path(code_file.path)
            if lang and lang != CodeLanguage.UNKNOWN:
                return lang
        except ImportError:
            pass

        # Fallback: map extension manually
        ext_map = {
            ".py": CodeLanguage.PYTHON,
            ".js": CodeLanguage.JAVASCRIPT,
            ".mjs": CodeLanguage.JAVASCRIPT,
            ".ts": CodeLanguage.TYPESCRIPT,
            ".tsx": CodeLanguage.TSX,
            ".jsx": CodeLanguage.JAVASCRIPT,
            ".java": CodeLanguage.JAVA,
            ".cs": CodeLanguage.CSHARP,
            ".go": CodeLanguage.GO,
            ".rs": CodeLanguage.RUST,
            ".rb": CodeLanguage.RUBY,
            ".php": CodeLanguage.PHP,
            ".kt": CodeLanguage.KOTLIN,
            ".swift": CodeLanguage.SWIFT,
            ".scala": CodeLanguage.SCALA,
            ".dart": CodeLanguage.DART,
            ".cpp": CodeLanguage.CPP,
            ".cc": CodeLanguage.CPP,
            ".c": CodeLanguage.C,
            ".h": CodeLanguage.C,
            ".hpp": CodeLanguage.CPP,
        }
        ext = Path(code_file.path).suffix.lower()
        return ext_map.get(ext)

    def _is_test_file(self, file_path: str) -> bool:
        """Check if file is a test file (language-agnostic)."""
        path = Path(file_path)
        path_str = str(path).lower()

        # Common test directories
        if any(d in path_str for d in ["/test/", "/tests/", "/__tests__/", "/spec/", "/specs/"]):
            return True

        name = path.stem.lower()
        test_patterns = ["test_", "_test", ".test", ".spec", "_spec"]
        return any(p in name for p in test_patterns)

    # =========================================================================
    # AST ACQUISITION
    # =========================================================================

    async def _get_ast(
        self, content: str, language: CodeLanguage, file_path: str
    ) -> Optional[ASTNode]:
        """Get Universal AST for content using best available provider."""
        registry = self._get_registry()
        provider = registry.get_provider(language)

        if not provider:
            logger.debug("no_ast_provider", language=language.value)
            return None

        try:
            result = await provider.parse(content, language, file_path)
            if result.is_success() or result.is_partial():
                return result.ast_root
        except Exception as e:
            logger.debug("ast_parse_failed", language=language.value, error=str(e))

        return None

    # =========================================================================
    # AST-BASED DETECTION METHODS
    # =========================================================================

    def _detect_exception_issues_ast(
        self,
        code_file: CodeFile,
        language: CodeLanguage,
        lines: List[str],
        ast_root: ASTNode,
    ) -> List[AntiPatternViolation]:
        """Detect exception handling anti-patterns using Universal AST."""
        violations = []

        def walk(node: ASTNode, parent: Optional[ASTNode] = None):
            original_type = node.attributes.get("original_type", "")

            # Check for try-catch nodes
            if original_type in TRY_CATCH_NODE_TYPES or node.node_type == ASTNodeType.TRY_CATCH:
                # Check for empty catch blocks
                if self._is_empty_catch_block(node, original_type):
                    line = node.location.start_line if node.location else 0
                    violations.append(AntiPatternViolation(
                        pattern_id="empty-catch",
                        pattern_name="Empty Catch Block",
                        severity=AntiPatternSeverity.CRITICAL,
                        message="Silently swallows exceptions",
                        file_path=code_file.path,
                        line=line,
                        code_snippet=self._get_line(lines, line),
                        suggestion="Log the error or handle it properly",
                        is_blocker=True,
                    ))

                # Check for bare catch (catches everything)
                if self._is_bare_catch(node, original_type, language):
                    line = node.location.start_line if node.location else 0
                    violations.append(AntiPatternViolation(
                        pattern_id="bare-catch",
                        pattern_name="Bare/Broad Catch Block",
                        severity=AntiPatternSeverity.CRITICAL,
                        message="Catches all exceptions including system signals",
                        file_path=code_file.path,
                        line=line,
                        code_snippet=self._get_line(lines, line),
                        suggestion=self._get_catch_suggestion(language),
                        is_blocker=True,
                    ))

            for child in node.children:
                walk(child, node)

        walk(ast_root)
        return violations

    def _is_empty_catch_block(self, node: ASTNode, original_type: str) -> bool:
        """Check if a catch block is empty."""
        # Look for catch clause patterns
        if original_type not in {"except_clause", "catch_clause", "rescue", "rescue_block"}:
            return False

        # Check if block has no meaningful statements
        # (only pass/empty or single comment)
        body_children = [
            c for c in node.children
            if c.node_type not in {ASTNodeType.COMMENT, ASTNodeType.IDENTIFIER}
        ]

        # Empty or only has "pass" equivalent
        if len(body_children) == 0:
            return True

        # Check for single "pass" statement (Python)
        if len(body_children) == 1:
            child_type = body_children[0].attributes.get("original_type", "")
            if child_type in {"pass_statement", "empty_statement", "block"}:
                # Check if block itself is empty
                if child_type == "block" and len(body_children[0].children) == 0:
                    return True
                if child_type in {"pass_statement", "empty_statement"}:
                    return True

        return False

    def _is_bare_catch(
        self, node: ASTNode, original_type: str, language: CodeLanguage
    ) -> bool:
        """Check if catch block catches all exceptions."""
        if original_type not in {"except_clause", "catch_clause", "rescue"}:
            return False

        # Look for exception type parameter
        exception_type = None
        for child in node.children:
            child_type = child.attributes.get("original_type", "")
            if child_type in {"type", "type_identifier", "identifier", "scoped_identifier"}:
                exception_type = child.name
                break

        # No exception type = bare catch
        if exception_type is None:
            return True

        # Check for overly broad exception types
        broad_types = {
            # Python
            "BaseException", "Exception",
            # Java/Kotlin
            "Throwable", "Exception",
            # C#
            "Exception", "System.Exception",
            # Ruby
            "Exception", "StandardError",
            # PHP
            "Throwable", "Exception",
        }

        return exception_type in broad_types

    def _detect_god_class_ast(
        self,
        code_file: CodeFile,
        language: CodeLanguage,
        lines: List[str],
        ast_root: ASTNode,
    ) -> List[AntiPatternViolation]:
        """Detect god classes using Universal AST."""
        violations = []

        def walk(node: ASTNode):
            original_type = node.attributes.get("original_type", "")

            # Check for class definitions
            if original_type in CLASS_NODE_TYPES or node.node_type == ASTNodeType.CLASS:
                if node.location:
                    class_lines = node.location.end_line - node.location.start_line + 1
                    if class_lines > self.max_class_lines:
                        violations.append(AntiPatternViolation(
                            pattern_id="god-class",
                            pattern_name="God Class",
                            severity=AntiPatternSeverity.HIGH,
                            message=f"Class '{node.name or 'anonymous'}' has {class_lines} lines (max: {self.max_class_lines})",
                            file_path=code_file.path,
                            line=node.location.start_line,
                            code_snippet=f"class {node.name or '?'}:  # {class_lines} lines",
                            suggestion="Split into smaller, focused classes",
                            is_blocker=False,
                        ))

            for child in node.children:
                walk(child)

        walk(ast_root)

        # Also check file size
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

    def _detect_debug_output_ast(
        self,
        code_file: CodeFile,
        language: CodeLanguage,
        lines: List[str],
        ast_root: ASTNode,
    ) -> List[AntiPatternViolation]:
        """Detect debug output using Universal AST."""
        violations = []

        def walk(node: ASTNode):
            original_type = node.attributes.get("original_type", "")

            # Check for call expressions
            if original_type in CALL_NODE_TYPES or node.node_type == ASTNodeType.CALL_EXPRESSION:
                func_name = self._extract_function_name(node)

                if func_name and self._is_debug_function(func_name):
                    line = node.location.start_line if node.location else 0
                    violations.append(AntiPatternViolation(
                        pattern_id="debug-output",
                        pattern_name="Debug Output",
                        severity=AntiPatternSeverity.MEDIUM,
                        message=f"Debug output statement: {func_name}",
                        file_path=code_file.path,
                        line=line,
                        code_snippet=self._get_line(lines, line),
                        suggestion=self._get_logging_suggestion(language),
                        is_blocker=False,
                    ))

            for child in node.children:
                walk(child)

        walk(ast_root)
        return violations

    def _extract_function_name(self, call_node: ASTNode) -> Optional[str]:
        """Extract function name from a call expression node."""
        # Direct function call: print(...)
        if call_node.name:
            return call_node.name

        # Look for function/identifier child
        for child in call_node.children:
            if child.node_type == ASTNodeType.IDENTIFIER:
                return child.name

            # Member access: console.log(...)
            if child.node_type == ASTNodeType.MEMBER_ACCESS:
                parts = self._extract_member_chain(child)
                if parts:
                    return ".".join(parts)

        return None

    def _extract_member_chain(self, node: ASTNode) -> List[str]:
        """Extract member access chain (e.g., ['console', 'log'])."""
        parts = []

        if node.name:
            parts.append(node.name)

        for child in node.children:
            if child.node_type == ASTNodeType.IDENTIFIER and child.name:
                parts.append(child.name)
            elif child.node_type == ASTNodeType.MEMBER_ACCESS:
                parts.extend(self._extract_member_chain(child))

        return parts

    def _is_debug_function(self, func_name: str) -> bool:
        """Check if function name is a debug output function."""
        # Direct match
        if func_name in DEBUG_FUNCTION_NAMES:
            return True

        # Check member patterns (console.log, System.out.println, etc.)
        parts = func_name.split(".")
        if len(parts) >= 2:
            obj = ".".join(parts[:-1])
            method = parts[-1]
            if obj in DEBUG_MEMBER_PATTERNS:
                return method in DEBUG_MEMBER_PATTERNS[obj]

        return False

    def _detect_generic_exception_ast(
        self,
        code_file: CodeFile,
        language: CodeLanguage,
        lines: List[str],
        ast_root: ASTNode,
    ) -> List[AntiPatternViolation]:
        """Detect generic exception throwing using Universal AST."""
        violations = []

        # Exception throwing node types
        throw_types = {"throw_statement", "raise_statement", "raise"}

        def walk(node: ASTNode):
            original_type = node.attributes.get("original_type", "")

            if original_type in throw_types or node.node_type == ASTNodeType.THROW_STATEMENT:
                # Check what is being thrown
                exception_type = self._extract_thrown_type(node)

                generic_types = {"Exception", "Error", "RuntimeError", "panic"}
                if exception_type in generic_types:
                    line = node.location.start_line if node.location else 0
                    violations.append(AntiPatternViolation(
                        pattern_id="generic-exception-raise",
                        pattern_name="Generic Exception Thrown",
                        severity=AntiPatternSeverity.HIGH,
                        message=f"Throwing generic exception type: {exception_type}",
                        file_path=code_file.path,
                        line=line,
                        code_snippet=self._get_line(lines, line),
                        suggestion="Use or create a specific exception type",
                        is_blocker=False,
                    ))

            for child in node.children:
                walk(child)

        walk(ast_root)
        return violations

    def _extract_thrown_type(self, throw_node: ASTNode) -> Optional[str]:
        """Extract the exception type being thrown."""
        for child in throw_node.children:
            # new Exception(...) or Exception(...)
            if child.node_type == ASTNodeType.CALL_EXPRESSION:
                func_name = self._extract_function_name(child)
                if func_name:
                    # Remove 'new ' prefix if present
                    return func_name.replace("new ", "")

            # Direct identifier
            if child.node_type == ASTNodeType.IDENTIFIER:
                return child.name

        return None

    # =========================================================================
    # REGEX FALLBACK DETECTION METHODS
    # =========================================================================

    def _detect_exception_issues_regex(
        self, code_file: CodeFile, language: CodeLanguage, lines: List[str]
    ) -> List[AntiPatternViolation]:
        """Detect exception handling anti-patterns using regex (fallback)."""
        violations = []
        content = code_file.content
        lang_str = language.value if isinstance(language, CodeLanguage) else str(language)

        # Language-specific patterns
        patterns = self._get_exception_patterns(lang_str)
        if not patterns:
            return violations

        # Bare catch patterns
        for pattern in patterns.get("bare_catch", []):
            for match in re.finditer(pattern, content, re.MULTILINE):
                line_num = content[:match.start()].count("\n") + 1
                violations.append(AntiPatternViolation(
                    pattern_id="bare-catch",
                    pattern_name="Bare/Broad Catch Block",
                    severity=AntiPatternSeverity.CRITICAL,
                    message=f"Catches all exceptions ({lang_str})",
                    file_path=code_file.path,
                    line=line_num,
                    code_snippet=self._get_line(lines, line_num),
                    suggestion=self._get_catch_suggestion(language),
                    is_blocker=True,
                ))

        # Empty catch pattern
        empty_pattern = patterns.get("empty_catch")
        if empty_pattern:
            for match in re.finditer(empty_pattern, content, re.MULTILINE):
                line_num = content[:match.start()].count("\n") + 1
                violations.append(AntiPatternViolation(
                    pattern_id="empty-catch",
                    pattern_name="Empty Catch Block",
                    severity=AntiPatternSeverity.CRITICAL,
                    message=f"Silently swallows exceptions ({lang_str})",
                    file_path=code_file.path,
                    line=line_num,
                    code_snippet=self._get_line(lines, line_num),
                    suggestion="Log the error or handle it properly",
                    is_blocker=True,
                ))

        return violations

    def _detect_god_class_regex(
        self, code_file: CodeFile, language: CodeLanguage, lines: List[str]
    ) -> List[AntiPatternViolation]:
        """Detect god classes using regex (fallback)."""
        violations = []

        # For Python, use native AST
        if language == CodeLanguage.PYTHON:
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

        # Simple heuristic for other languages: check file size
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

    def _detect_debug_output_regex(
        self, code_file: CodeFile, language: CodeLanguage, lines: List[str]
    ) -> List[AntiPatternViolation]:
        """Detect debug output using regex (fallback)."""
        violations = []
        content = code_file.content
        lang_str = language.value if isinstance(language, CodeLanguage) else str(language)

        patterns = self._get_debug_patterns(lang_str)
        if not patterns:
            return violations

        for pattern in patterns:
            for match in re.finditer(pattern, content, re.MULTILINE | re.IGNORECASE):
                line_num = content[:match.start()].count("\n") + 1
                line_content = self._get_line(lines, line_num)

                # Skip if in a comment
                if self._is_in_comment(line_content, lang_str):
                    continue

                violations.append(AntiPatternViolation(
                    pattern_id="debug-output",
                    pattern_name="Debug Output",
                    severity=AntiPatternSeverity.MEDIUM,
                    message=f"Debug output statement found ({lang_str})",
                    file_path=code_file.path,
                    line=line_num,
                    code_snippet=line_content,
                    suggestion=self._get_logging_suggestion(language),
                    is_blocker=False,
                ))

        return violations

    def _detect_generic_exception_regex(
        self, code_file: CodeFile, language: CodeLanguage, lines: List[str]
    ) -> List[AntiPatternViolation]:
        """Detect generic exception throwing using regex (fallback)."""
        violations = []
        content = code_file.content
        lang_str = language.value if isinstance(language, CodeLanguage) else str(language)

        patterns = self._get_exception_patterns(lang_str)
        generic_pattern = patterns.get("generic_raise") if patterns else None

        if not generic_pattern:
            return violations

        patterns_to_check = generic_pattern if isinstance(generic_pattern, list) else [generic_pattern]

        for pattern in patterns_to_check:
            for match in re.finditer(pattern, content, re.MULTILINE):
                line_num = content[:match.start()].count("\n") + 1
                violations.append(AntiPatternViolation(
                    pattern_id="generic-exception-raise",
                    pattern_name="Generic Exception Thrown",
                    severity=AntiPatternSeverity.HIGH,
                    message=f"Throwing generic exception type ({lang_str})",
                    file_path=code_file.path,
                    line=line_num,
                    code_snippet=self._get_line(lines, line_num),
                    suggestion="Use or create a specific exception type",
                    is_blocker=False,
                ))

        return violations

    # =========================================================================
    # TODO/FIXME DETECTION (Always regex-based)
    # =========================================================================

    def _detect_todo_fixme(
        self, code_file: CodeFile, lines: List[str]
    ) -> List[AntiPatternViolation]:
        """Detect TODO/FIXME comments (universal, regex-based)."""
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

    # =========================================================================
    # PATTERN CONFIGURATION
    # =========================================================================

    def _get_exception_patterns(self, language: str) -> Dict[str, Any]:
        """Get exception handling patterns for a language."""
        patterns = {
            "python": {
                "bare_catch": [r"except\s*:", r"except\s+BaseException\s*:"],
                "empty_catch": r"except.*:\s*\n\s+pass\s*$",
                "generic_raise": r"raise\s+Exception\s*\(",
            },
            "javascript": {
                "bare_catch": [r"catch\s*\{\s*\}", r"catch\s*\(\s*\w*\s*\)\s*\{\s*\}"],
                "empty_catch": r"catch\s*\([^)]*\)\s*\{\s*\}",
                "generic_raise": r"throw\s+new\s+Error\s*\(",
            },
            "typescript": {
                "bare_catch": [r"catch\s*\{\s*\}", r"catch\s*\(\s*\w*\s*\)\s*\{\s*\}"],
                "empty_catch": r"catch\s*\([^)]*\)\s*\{\s*\}",
                "generic_raise": r"throw\s+new\s+Error\s*\(",
            },
            "java": {
                "bare_catch": [r"catch\s*\(\s*Throwable\s+\w+\s*\)"],
                "empty_catch": r"catch\s*\([^)]+\)\s*\{\s*\}",
                "generic_raise": r"throw\s+new\s+Exception\s*\(",
            },
            "csharp": {
                "bare_catch": [r"catch\s*\{\s*\}", r"catch\s*\(\s*Exception\s*\)"],
                "empty_catch": r"catch\s*(\([^)]*\))?\s*\{\s*\}",
                "generic_raise": r"throw\s+new\s+Exception\s*\(",
            },
            "go": {
                "bare_catch": [],
                "empty_catch": r"if\s+err\s*!=\s*nil\s*\{\s*\}",
                "generic_raise": [],
            },
            "rust": {
                "bare_catch": [],
                "empty_catch": [],
                "generic_raise": r"panic!\s*\(",
            },
            "ruby": {
                "bare_catch": [r"rescue\s*$", r"rescue\s+Exception"],
                "empty_catch": r"rescue.*\n\s*end",
                "generic_raise": r"raise\s+['\"]",
            },
            "php": {
                "bare_catch": [r"catch\s*\(\s*\\?Throwable\s+"],
                "empty_catch": r"catch\s*\([^)]+\)\s*\{\s*\}",
                "generic_raise": r"throw\s+new\s+\\?Exception\s*\(",
            },
        }
        return patterns.get(language, {})

    def _get_debug_patterns(self, language: str) -> List[str]:
        """Get debug output patterns for a language."""
        patterns = {
            "python": [r"print\s*\("],
            "javascript": [r"console\.(log|debug|info|warn|error)\s*\(", r"debugger\s*;"],
            "typescript": [r"console\.(log|debug|info|warn|error)\s*\(", r"debugger\s*;"],
            "java": [r"System\.(out|err)\.(print|println)\s*\(", r"\.printStackTrace\s*\("],
            "csharp": [r"Console\.(Write|WriteLine)\s*\(", r"Debug\.(Write|WriteLine)\s*\("],
            "go": [r"fmt\.(Print|Println|Printf)\s*\("],
            "rust": [r"println!\s*\(", r"dbg!\s*\("],
            "ruby": [r"\bputs\s+", r"\bp\s+"],
            "php": [r"var_dump\s*\(", r"print_r\s*\(", r"dd\s*\("],
            "kotlin": [r"println\s*\("],
            "swift": [r"print\s*\(", r"debugPrint\s*\("],
        }
        return patterns.get(language, [])

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
        comment_prefixes = ["//", "#", "/*", "*", "///", "//!"]
        return any(stripped.startswith(p) for p in comment_prefixes)

    def _get_catch_suggestion(self, language: CodeLanguage) -> str:
        """Get language-specific suggestion for exception handling."""
        suggestions = {
            CodeLanguage.PYTHON: "Catch specific exceptions: except (ValueError, IOError) as e:",
            CodeLanguage.JAVASCRIPT: "Catch specific error types or add error handling logic",
            CodeLanguage.TYPESCRIPT: "Use typed catch or add proper error handling",
            CodeLanguage.JAVA: "Catch specific exceptions: catch (IOException | SQLException e)",
            CodeLanguage.CSHARP: "Catch specific exceptions: catch (IOException ex)",
            CodeLanguage.GO: "Handle error properly: if err != nil { return err }",
            CodeLanguage.RUBY: "Catch specific exceptions: rescue ArgumentError, TypeError",
            CodeLanguage.PHP: "Catch specific exceptions: catch (InvalidArgumentException $e)",
        }
        return suggestions.get(language, "Catch specific exception types")

    def _get_logging_suggestion(self, language: CodeLanguage) -> str:
        """Get language-specific logging suggestion."""
        suggestions = {
            CodeLanguage.PYTHON: "Use logging module: logger.debug(...)",
            CodeLanguage.JAVASCRIPT: "Use a logging library or remove before production",
            CodeLanguage.TYPESCRIPT: "Use a logging library or remove before production",
            CodeLanguage.JAVA: "Use SLF4J/Log4j: logger.debug(...)",
            CodeLanguage.CSHARP: "Use ILogger: _logger.LogDebug(...)",
            CodeLanguage.GO: "Use structured logging: log.Debug(...)",
            CodeLanguage.RUST: "Use log crate: debug!(...) or tracing",
            CodeLanguage.RUBY: "Use Rails.logger or a logging gem",
            CodeLanguage.PHP: "Use Monolog or PSR-3 logger",
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
