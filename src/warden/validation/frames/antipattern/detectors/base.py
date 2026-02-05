"""
Base Detector Class

Abstract base for all anti-pattern detectors.
"""

from abc import ABC, abstractmethod
from typing import List, Optional

from warden.ast.domain.models import ASTNode
from warden.ast.domain.enums import CodeLanguage
from warden.validation.domain.frame import CodeFile
from warden.validation.frames.antipattern.types import AntiPatternViolation


class BaseDetector(ABC):
    """Base class for anti-pattern detectors."""

    @abstractmethod
    def detect_ast(
        self,
        code_file: CodeFile,
        language: CodeLanguage,
        lines: List[str],
        ast_root: ASTNode,
    ) -> List[AntiPatternViolation]:
        """Detect anti-patterns using Universal AST."""
        pass

    @abstractmethod
    def detect_regex(
        self,
        code_file: CodeFile,
        language: CodeLanguage,
        lines: List[str],
    ) -> List[AntiPatternViolation]:
        """Detect anti-patterns using regex (fallback)."""
        pass

    def detect(
        self,
        code_file: CodeFile,
        language: CodeLanguage,
        lines: List[str],
        ast_root: Optional[ASTNode] = None,
    ) -> List[AntiPatternViolation]:
        """Detect anti-patterns using AST if available, else regex."""
        if ast_root:
            return self.detect_ast(code_file, language, lines, ast_root)
        return self.detect_regex(code_file, language, lines)

    @staticmethod
    def get_line(lines: List[str], line_num: int) -> str:
        """Get a line from the file (1-indexed)."""
        if 1 <= line_num <= len(lines):
            return lines[line_num - 1].strip()
        return ""

    @staticmethod
    def is_in_comment(line: str, language: str) -> bool:
        """Check if code is in a comment."""
        stripped = line.strip()
        comment_prefixes = ["//", "#", "/*", "*", "///", "//!"]
        return any(stripped.startswith(p) for p in comment_prefixes)
