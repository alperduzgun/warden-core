"""
TODO/FIXME Detector

Detects TODO/FIXME comments (technical debt markers):
- TODO comments
- FIXME comments
- XXX/HACK/BUG markers
"""

import re
from typing import List

from warden.ast.domain.enums import CodeLanguage
from warden.ast.domain.models import ASTNode
from warden.validation.domain.frame import CodeFile
from warden.validation.frames.antipattern.detectors.base import BaseDetector
from warden.validation.frames.antipattern.types import (
    AntiPatternSeverity,
    AntiPatternViolation,
)


class TodoDetector(BaseDetector):
    """Detector for TODO/FIXME comment anti-patterns."""

    # TODO/FIXME is always regex-based (comment content), so AST uses same logic
    def detect_ast(
        self,
        code_file: CodeFile,
        language: CodeLanguage,
        lines: list[str],
        ast_root: ASTNode,
    ) -> list[AntiPatternViolation]:
        """Detect TODO/FIXME using regex (AST not needed for comments)."""
        return self._detect_todo_fixme(code_file, lines)

    def detect_regex(
        self,
        code_file: CodeFile,
        language: CodeLanguage,
        lines: list[str],
    ) -> list[AntiPatternViolation]:
        """Detect TODO/FIXME comments."""
        return self._detect_todo_fixme(code_file, lines)

    def _detect_todo_fixme(self, code_file: CodeFile, lines: list[str]) -> list[AntiPatternViolation]:
        """Detect TODO/FIXME comments (universal, regex-based)."""
        violations = []

        # Pattern matches common comment styles and markers
        pattern = r"(#|//|/\*|\*|--|<!--|;)\s*(TODO|FIXME|XXX|HACK|BUG)\s*:?\s*(.*)"

        for line_num, line in enumerate(lines, start=1):
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                marker = match.group(2).upper()
                description = match.group(3).strip()[:50]

                violations.append(
                    AntiPatternViolation(
                        pattern_id="todo-fixme",
                        pattern_name=f"{marker} Comment",
                        severity=AntiPatternSeverity.LOW,
                        message=f"{marker}: {description}..." if description else f"{marker} marker found",
                        file_path=code_file.path,
                        line=line_num,
                        code_snippet=line.strip(),
                        suggestion="Convert to tracked issue or resolve",
                        is_blocker=False,
                    )
                )

        return violations
