"""
Class Size Detector

Detects class/file size anti-patterns:
- God classes (classes > 500 lines)
- Large files (files > 1000 lines)
"""

import ast
from typing import List

from warden.ast.domain.enums import ASTNodeType, CodeLanguage
from warden.ast.domain.models import ASTNode
from warden.validation.domain.frame import CodeFile
from warden.validation.frames.antipattern.constants import CLASS_NODE_TYPES
from warden.validation.frames.antipattern.detectors.base import BaseDetector
from warden.validation.frames.antipattern.types import (
    AntiPatternSeverity,
    AntiPatternViolation,
)


class ClassSizeDetector(BaseDetector):
    """Detector for class/file size anti-patterns."""

    def __init__(self, max_class_lines: int = 500, max_file_lines: int = 1000):
        """Initialize with thresholds."""
        self.max_class_lines = max_class_lines
        self.max_file_lines = max_file_lines

    def detect_ast(
        self,
        code_file: CodeFile,
        language: CodeLanguage,
        lines: list[str],
        ast_root: ASTNode,
    ) -> list[AntiPatternViolation]:
        """Detect god classes using Universal AST."""
        violations = []

        def walk(node: ASTNode):
            original_type = node.attributes.get("original_type", "")

            # Check for class definitions
            if original_type in CLASS_NODE_TYPES or node.node_type == ASTNodeType.CLASS:
                if node.location:
                    class_lines = node.location.end_line - node.location.start_line + 1
                    if class_lines > self.max_class_lines:
                        violations.append(
                            AntiPatternViolation(
                                pattern_id="god-class",
                                pattern_name="God Class",
                                severity=AntiPatternSeverity.HIGH,
                                message=f"Class '{node.name or 'anonymous'}' has {class_lines} lines (max: {self.max_class_lines})",
                                file_path=code_file.path,
                                line=node.location.start_line,
                                code_snippet=f"class {node.name or '?'}:  # {class_lines} lines",
                                suggestion="Split into smaller, focused classes",
                                is_blocker=False,
                            )
                        )

            for child in node.children:
                walk(child)

        walk(ast_root)

        # Also check file size
        violations.extend(self._check_file_size(code_file, lines))

        return violations

    def detect_regex(
        self,
        code_file: CodeFile,
        language: CodeLanguage,
        lines: list[str],
    ) -> list[AntiPatternViolation]:
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
                                violations.append(
                                    AntiPatternViolation(
                                        pattern_id="god-class",
                                        pattern_name="God Class",
                                        severity=AntiPatternSeverity.HIGH,
                                        message=f"Class '{node.name}' has {class_lines} lines (max: {self.max_class_lines})",
                                        file_path=code_file.path,
                                        line=node.lineno,
                                        code_snippet=f"class {node.name}:  # {class_lines} lines",
                                        suggestion="Split into smaller, focused classes",
                                        is_blocker=False,
                                    )
                                )
            except SyntaxError:
                pass

        # Check file size for all languages
        violations.extend(self._check_file_size(code_file, lines))

        return violations

    def _check_file_size(self, code_file: CodeFile, lines: list[str]) -> list[AntiPatternViolation]:
        """Check if file exceeds maximum line count."""
        violations = []
        total_lines = len(lines)

        if total_lines > self.max_file_lines:
            violations.append(
                AntiPatternViolation(
                    pattern_id="large-file",
                    pattern_name="Large File",
                    severity=AntiPatternSeverity.MEDIUM,
                    message=f"File has {total_lines} lines (max: {self.max_file_lines})",
                    file_path=code_file.path,
                    line=1,
                    code_snippet=f"// {total_lines} lines",
                    suggestion="Consider splitting into smaller modules",
                    is_blocker=False,
                )
            )

        return violations
