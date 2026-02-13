"""
Debug Output Detector

Detects debug output in production code:
- print statements
- console.log calls
- Debug.Write calls
- var_dump, dd, etc.
"""

import re
from typing import List, Optional

from warden.ast.domain.enums import ASTNodeType, CodeLanguage
from warden.ast.domain.models import ASTNode
from warden.validation.domain.frame import CodeFile
from warden.validation.frames.antipattern.constants import (
    CALL_NODE_TYPES,
    DEBUG_FUNCTION_NAMES,
    DEBUG_MEMBER_PATTERNS,
    get_debug_patterns,
)
from warden.validation.frames.antipattern.detectors.base import BaseDetector
from warden.validation.frames.antipattern.types import (
    AntiPatternSeverity,
    AntiPatternViolation,
)


class DebugDetector(BaseDetector):
    """Detector for debug output anti-patterns."""

    def detect_ast(
        self,
        code_file: CodeFile,
        language: CodeLanguage,
        lines: list[str],
        ast_root: ASTNode,
    ) -> list[AntiPatternViolation]:
        """Detect debug output using Universal AST."""
        violations = []

        def walk(node: ASTNode):
            original_type = node.attributes.get("original_type", "")

            # Check for call expressions
            if original_type in CALL_NODE_TYPES or node.node_type == ASTNodeType.CALL_EXPRESSION:
                func_name = self._extract_function_name(node)

                if func_name and self._is_debug_function(func_name):
                    line = node.location.start_line if node.location else 0
                    violations.append(
                        AntiPatternViolation(
                            pattern_id="debug-output",
                            pattern_name="Debug Output",
                            severity=AntiPatternSeverity.MEDIUM,
                            message=f"Debug output statement: {func_name}",
                            file_path=code_file.path,
                            line=line,
                            code_snippet=self.get_line(lines, line),
                            suggestion=self._get_logging_suggestion(language),
                            is_blocker=False,
                        )
                    )

            for child in node.children:
                walk(child)

        walk(ast_root)
        return violations

    def detect_regex(
        self,
        code_file: CodeFile,
        language: CodeLanguage,
        lines: list[str],
    ) -> list[AntiPatternViolation]:
        """Detect debug output using regex (fallback)."""
        violations = []
        content = code_file.content
        lang_str = language.value if isinstance(language, CodeLanguage) else str(language)

        patterns = get_debug_patterns(lang_str)
        if not patterns:
            return violations

        for pattern in patterns:
            for match in re.finditer(pattern, content, re.MULTILINE | re.IGNORECASE):
                line_num = content[: match.start()].count("\n") + 1
                line_content = self.get_line(lines, line_num)

                # Skip if in a comment
                if self.is_in_comment(line_content, lang_str):
                    continue

                violations.append(
                    AntiPatternViolation(
                        pattern_id="debug-output",
                        pattern_name="Debug Output",
                        severity=AntiPatternSeverity.MEDIUM,
                        message=f"Debug output statement found ({lang_str})",
                        file_path=code_file.path,
                        line=line_num,
                        code_snippet=line_content,
                        suggestion=self._get_logging_suggestion(language),
                        is_blocker=False,
                    )
                )

        return violations

    # =========================================================================
    # HELPERS
    # =========================================================================

    def _extract_function_name(self, call_node: ASTNode) -> str | None:
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

    def _extract_member_chain(self, node: ASTNode) -> list[str]:
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
