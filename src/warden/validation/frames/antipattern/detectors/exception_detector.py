"""
Exception Handling Detector

Detects exception handling anti-patterns:
- Empty catch blocks (exception swallowing)
- Bare/broad catch blocks (catches everything)
- Generic exception throwing
"""

import re
from typing import List, Optional

from warden.ast.domain.models import ASTNode
from warden.ast.domain.enums import ASTNodeType, CodeLanguage
from warden.validation.domain.frame import CodeFile
from warden.validation.frames.antipattern.types import (
    AntiPatternSeverity,
    AntiPatternViolation,
)
from warden.validation.frames.antipattern.constants import (
    TRY_CATCH_NODE_TYPES,
    get_exception_patterns,
)
from warden.validation.frames.antipattern.detectors.base import BaseDetector


class ExceptionDetector(BaseDetector):
    """Detector for exception handling anti-patterns."""

    def detect_ast(
        self,
        code_file: CodeFile,
        language: CodeLanguage,
        lines: List[str],
        ast_root: ASTNode,
    ) -> List[AntiPatternViolation]:
        """Detect exception handling anti-patterns using Universal AST."""
        violations = []
        violations.extend(self._detect_catch_issues_ast(code_file, language, lines, ast_root))
        violations.extend(self._detect_generic_exception_ast(code_file, language, lines, ast_root))
        return violations

    def detect_regex(
        self,
        code_file: CodeFile,
        language: CodeLanguage,
        lines: List[str],
    ) -> List[AntiPatternViolation]:
        """Detect exception handling anti-patterns using regex."""
        violations = []
        violations.extend(self._detect_catch_issues_regex(code_file, language, lines))
        violations.extend(self._detect_generic_exception_regex(code_file, language, lines))
        return violations

    # =========================================================================
    # AST-BASED DETECTION
    # =========================================================================

    def _detect_catch_issues_ast(
        self,
        code_file: CodeFile,
        language: CodeLanguage,
        lines: List[str],
        ast_root: ASTNode,
    ) -> List[AntiPatternViolation]:
        """Detect catch block issues using AST."""
        violations = []

        def walk(node: ASTNode, parent: Optional[ASTNode] = None):
            original_type = node.attributes.get("original_type", "")

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
                        code_snippet=self.get_line(lines, line),
                        suggestion="Log the error or handle it properly",
                        is_blocker=True,
                    ))

                # Check for bare catch (catches everything without proper handling)
                if self._is_bare_catch(node, original_type, language, lines):
                    line = node.location.start_line if node.location else 0
                    violations.append(AntiPatternViolation(
                        pattern_id="bare-catch",
                        pattern_name="Bare/Broad Catch Block",
                        severity=AntiPatternSeverity.CRITICAL,
                        message="Catches all exceptions including system signals",
                        file_path=code_file.path,
                        line=line,
                        code_snippet=self.get_line(lines, line),
                        suggestion=self._get_catch_suggestion(language),
                        is_blocker=True,
                    ))

            for child in node.children:
                walk(child, node)

        walk(ast_root)
        return violations

    def _is_empty_catch_block(self, node: ASTNode, original_type: str) -> bool:
        """Check if a catch block is empty."""
        if original_type not in {"except_clause", "catch_clause", "rescue", "rescue_block"}:
            return False

        # Check if block has no meaningful statements
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
                if child_type == "block" and len(body_children[0].children) == 0:
                    return True
                if child_type in {"pass_statement", "empty_statement"}:
                    return True

        return False

    def _is_bare_catch(
        self, node: ASTNode, original_type: str, language: CodeLanguage, lines: List[str]
    ) -> bool:
        """Check if catch block catches all exceptions without proper handling."""
        if original_type not in {"except_clause", "catch_clause", "rescue"}:
            return False

        if not node.location:
            return False

        # Get the except line from source code (more reliable than AST names)
        line_num = node.location.start_line
        if line_num < 1 or line_num > len(lines):
            return False

        except_line = lines[line_num - 1].strip()

        # Check for bare except (no exception type at all)
        if re.match(r'^except\s*:', except_line):
            return True

        # Check for tuple of exceptions - this is always intentional/specific
        if re.search(r'except\s*\([^)]+,[^)]+\)', except_line):
            return False  # Multiple exceptions = specific handling

        # Check for overly broad single exception types
        broad_patterns = [
            r'except\s+Exception\s*:',
            r'except\s+Exception\s+as\s+\w+:',
            r'except\s+BaseException\s*:',
            r'except\s+BaseException\s+as\s+\w+:',
        ]

        is_broad = any(re.search(p, except_line) for p in broad_patterns)

        if not is_broad:
            return False  # Specific exception type = OK

        # Broad exception - check if properly handled
        start_line = line_num
        end_line = node.location.end_line or start_line + 10

        # Check the exception handler body for proper handling patterns
        handler_lines = lines[start_line - 1:min(end_line, len(lines))]
        handler_text = "\n".join(handler_lines).lower()

        # Proper handling patterns - if any exist, don't flag
        proper_handling_patterns = [
            "logger.", "logging.", "log.",  # Logging
            "raise",  # Re-raising
            "traceback",  # Traceback handling
            "print(",  # Even print is better than silent
            "sys.exc_info",  # Exception info access
            "exc_info=true",  # Logging with exc_info
            "exc_info=",  # Any exc_info usage
        ]

        for pattern in proper_handling_patterns:
            if pattern in handler_text:
                return False  # Has proper handling, not a bare catch

        # Check for return with meaningful value
        if re.search(r'return\s+[^N\s]', handler_text) or re.search(r'return\s+\S+[^None]', handler_text):
            return False

        # No proper handling found = bare/dangerous catch
        return True

    def _detect_generic_exception_ast(
        self,
        code_file: CodeFile,
        language: CodeLanguage,
        lines: List[str],
        ast_root: ASTNode,
    ) -> List[AntiPatternViolation]:
        """Detect generic exception throwing using Universal AST."""
        violations = []

        throw_types = {"throw_statement", "raise_statement", "raise"}

        def walk(node: ASTNode):
            original_type = node.attributes.get("original_type", "")

            if original_type in throw_types or node.node_type == ASTNodeType.THROW_STATEMENT:
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
                        code_snippet=self.get_line(lines, line),
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
            if child.node_type == ASTNodeType.CALL_EXPRESSION:
                func_name = self._extract_function_name(child)
                if func_name:
                    return func_name.replace("new ", "")

            if child.node_type == ASTNodeType.IDENTIFIER:
                return child.name

        return None

    def _extract_function_name(self, call_node: ASTNode) -> Optional[str]:
        """Extract function name from a call expression node."""
        if call_node.name:
            return call_node.name

        for child in call_node.children:
            if child.node_type == ASTNodeType.IDENTIFIER:
                return child.name

        return None

    # =========================================================================
    # REGEX FALLBACK DETECTION
    # =========================================================================

    def _detect_catch_issues_regex(
        self, code_file: CodeFile, language: CodeLanguage, lines: List[str]
    ) -> List[AntiPatternViolation]:
        """Detect catch issues using regex (fallback)."""
        violations = []
        content = code_file.content
        lang_str = language.value if isinstance(language, CodeLanguage) else str(language)

        patterns = get_exception_patterns(lang_str)
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
                    code_snippet=self.get_line(lines, line_num),
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
                    code_snippet=self.get_line(lines, line_num),
                    suggestion="Log the error or handle it properly",
                    is_blocker=True,
                ))

        return violations

    def _detect_generic_exception_regex(
        self, code_file: CodeFile, language: CodeLanguage, lines: List[str]
    ) -> List[AntiPatternViolation]:
        """Detect generic exception throwing using regex."""
        violations = []
        content = code_file.content
        lang_str = language.value if isinstance(language, CodeLanguage) else str(language)

        patterns = get_exception_patterns(lang_str)
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
                    code_snippet=self.get_line(lines, line_num),
                    suggestion="Use or create a specific exception type",
                    is_blocker=False,
                ))

        return violations

    # =========================================================================
    # HELPERS
    # =========================================================================

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
