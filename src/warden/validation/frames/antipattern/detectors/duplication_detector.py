"""
Duplication Detector

Detects near-duplicate functions within a single file using token-based
Jaccard similarity. Single-file scope only; no cross-file comparison.
"""

import re

from warden.ast.domain.enums import CodeLanguage
from warden.ast.domain.models import ASTNode
from warden.validation.domain.frame import CodeFile
from warden.validation.frames.antipattern.detectors.base import BaseDetector
from warden.validation.frames.antipattern.types import (
    AntiPatternSeverity,
    AntiPatternViolation,
)

# Regex patterns keyed by language family for extracting function start lines.
# Each pattern captures (function_name, body_start_position).
_PYTHON_FUNC = re.compile(r"^(\s*)def\s+(\w+)\s*\(", re.MULTILINE)
_JS_FUNC = re.compile(
    r"^[ \t]*(?:(?:async\s+)?function\s+(\w+)\s*\(|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\(?[^)]*\)?\s*=>)",
    re.MULTILINE,
)

# Languages treated as JS-family (use JS patterns)
_JS_FAMILY = {
    CodeLanguage.JAVASCRIPT,
    CodeLanguage.TYPESCRIPT,
    CodeLanguage.TSX,
}


class DuplicationDetector(BaseDetector):
    """Detects near-duplicate functions within a single file."""

    SIMILARITY_THRESHOLD = 0.8  # 80% Jaccard similarity
    MIN_FUNCTION_LINES = 5  # Skip trivially small functions

    # Both AST and regex paths share the same regex-based extraction logic
    # because cross-language AST normalisation adds complexity beyond scope.

    def detect_ast(
        self,
        code_file: CodeFile,
        language: CodeLanguage,
        lines: list[str],
        ast_root: ASTNode,
    ) -> list[AntiPatternViolation]:
        """Detect duplicate functions (uses regex; AST not required)."""
        return self._detect_duplicates(code_file, language, lines)

    def detect_regex(
        self,
        code_file: CodeFile,
        language: CodeLanguage,
        lines: list[str],
    ) -> list[AntiPatternViolation]:
        """Detect duplicate functions via regex extraction."""
        return self._detect_duplicates(code_file, language, lines)

    # -------------------------------------------------------------------------
    # Core detection
    # -------------------------------------------------------------------------

    def _detect_duplicates(
        self,
        code_file: CodeFile,
        language: CodeLanguage,
        lines: list[str],
    ) -> list[AntiPatternViolation]:
        """Extract functions, compare all pairs, report similar ones."""
        functions = self._extract_functions(code_file.content, language, lines)

        if len(functions) < 2:
            return []

        violations: list[AntiPatternViolation] = []
        reported: set[frozenset[str]] = set()

        for i, (name_a, start_a, body_a) in enumerate(functions):
            # Compare body content only (skip the `def` signature line) so that
            # differing function names don't artificially reduce similarity.
            tokens_a = self._tokenise(self._body_only(body_a))
            if not tokens_a:
                continue

            for name_b, start_b, body_b in functions[i + 1 :]:
                pair_key = frozenset({f"{name_a}:{start_a}", f"{name_b}:{start_b}"})
                if pair_key in reported:
                    continue

                tokens_b = self._tokenise(self._body_only(body_b))
                if not tokens_b:
                    continue

                similarity = self._jaccard(tokens_a, tokens_b)
                if similarity >= self.SIMILARITY_THRESHOLD:
                    reported.add(pair_key)
                    pct = int(similarity * 100)
                    violations.append(
                        AntiPatternViolation(
                            pattern_id="code-duplication",
                            pattern_name="Duplicate Function",
                            severity=AntiPatternSeverity.MEDIUM,
                            message=(
                                f"Functions '{name_a}' (line {start_a}) and "
                                f"'{name_b}' (line {start_b}) are {pct}% similar"
                            ),
                            file_path=code_file.path,
                            line=start_a,
                            code_snippet=f"def {name_a}(...)  ~  def {name_b}(...)",
                            suggestion=(
                                "Extract shared logic into a common helper function "
                                "to eliminate duplication"
                            ),
                            is_blocker=False,
                        )
                    )

        return violations

    # -------------------------------------------------------------------------
    # Function extraction
    # -------------------------------------------------------------------------

    def _extract_functions(
        self,
        content: str,
        language: CodeLanguage,
        lines: list[str],
    ) -> list[tuple[str, int, str]]:
        """Return list of (name, start_line_1indexed, body) tuples."""
        if language == CodeLanguage.PYTHON:
            return self._extract_python_functions(content, lines)
        if language in _JS_FAMILY:
            return self._extract_js_functions(content, lines)
        # Fallback: try Python-style for unknown languages
        return self._extract_python_functions(content, lines)

    def _extract_python_functions(
        self, content: str, lines: list[str]
    ) -> list[tuple[str, int, str]]:
        """Extract Python function bodies by indentation block."""
        results: list[tuple[str, int, str]] = []
        for match in _PYTHON_FUNC.finditer(content):
            # group(1) may contain leading newlines when MULTILINE spans blank
            # lines; only the last segment (actual spaces on the def line) counts.
            raw_indent = match.group(1)
            indent = len(raw_indent.split("\n")[-1])
            name = match.group(2)
            # The def keyword starts after the indent prefix, so offset by len(raw_indent)
            def_pos = match.start() + len(raw_indent)
            start_line = content[:def_pos].count("\n") + 1  # 1-indexed
            body_lines = self._collect_block(lines, start_line, indent)
            if len(body_lines) >= self.MIN_FUNCTION_LINES:
                results.append((name, start_line, "\n".join(body_lines)))
        return results

    def _extract_js_functions(
        self, content: str, lines: list[str]
    ) -> list[tuple[str, int, str]]:
        """Extract JS/TS function bodies using brace counting."""
        results: list[tuple[str, int, str]] = []
        for match in _JS_FUNC.finditer(content):
            name = match.group(1) or match.group(2) or "<anonymous>"
            start_line = content[: match.start()].count("\n") + 1
            body_lines = self._collect_brace_block(lines, start_line)
            if len(body_lines) >= self.MIN_FUNCTION_LINES:
                results.append((name, start_line, "\n".join(body_lines)))
        return results

    def _collect_block(
        self, lines: list[str], start_line: int, base_indent: int
    ) -> list[str]:
        """Collect an indentation-based block (Python style).

        Blank lines inside the block are kept; the block ends when a
        non-blank line is found at or below ``base_indent`` indentation.
        """
        block: list[str] = []
        min_body_indent = base_indent + 1  # at least one space more than def
        pending_blanks: list[str] = []  # blank lines buffered for look-ahead

        for line in lines[start_line - 1 :]:
            rstripped = line.rstrip()

            if not block:
                # First line is the function definition itself
                block.append(rstripped)
                continue

            if rstripped == "":
                # Buffer blank lines; flush only if block continues
                pending_blanks.append(rstripped)
                continue

            # Non-blank line: check indentation
            leading = len(rstripped) - len(rstripped.lstrip())
            if leading >= min_body_indent:
                # Still inside the block
                block.extend(pending_blanks)
                pending_blanks = []
                block.append(rstripped)
            else:
                # Dedented — block is done (discard buffered blanks)
                break

        return block

    def _collect_brace_block(self, lines: list[str], start_line: int) -> list[str]:
        """Collect a brace-delimited block (JS/TS style)."""
        block: list[str] = []
        depth = 0
        started = False
        for line in lines[start_line - 1 :]:
            block.append(line.rstrip())
            depth += line.count("{") - line.count("}")
            if "{" in line:
                started = True
            if started and depth <= 0:
                break
        return block

    # -------------------------------------------------------------------------
    # Normalisation & similarity
    # -------------------------------------------------------------------------

    @staticmethod
    def _body_only(body: str) -> str:
        """Return the body lines after the function signature (first line)."""
        lines = body.split("\n")
        return "\n".join(lines[1:]) if len(lines) > 1 else body

    @staticmethod
    def _normalise(text: str) -> str:
        """Strip comments, collapse whitespace, lowercase."""
        # Remove single-line comments (# and //)
        text = re.sub(r"(#|//).*", "", text)
        # Remove block comments (/* ... */)
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
        # Remove string literals (rough approximation to avoid noise)
        text = re.sub(r'""".*?"""', '""', text, flags=re.DOTALL)
        text = re.sub(r"'''.*?'''", "''", text, flags=re.DOTALL)
        text = re.sub(r'"[^"\n]*"', '""', text)
        text = re.sub(r"'[^'\n]*'", "''", text)
        # Collapse whitespace and lowercase
        return re.sub(r"\s+", " ", text).strip().lower()

    @staticmethod
    def _tokenise(body: str) -> frozenset[str]:
        """Return a frozenset of tokens from the normalised body."""
        normalised = DuplicationDetector._normalise(body)
        tokens = re.findall(r"\w+", normalised)
        return frozenset(tokens)

    @staticmethod
    def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
        """Compute Jaccard similarity between two token sets."""
        if not a or not b:
            return 0.0
        intersection = len(a & b)
        union = len(a | b)
        return intersection / union if union > 0 else 0.0
