"""
SQL Injection Detection Check.

Detects potential SQL injection vulnerabilities:
- String concatenation in SQL queries
- f-strings in SQL queries
- Lack of parameterized queries

v2: Context-aware matching with FP exclusion registry and pattern confidence.
    Reads ±7 lines of surrounding context to reduce false positives before
    findings reach the LLM verification stage.
"""

import re
from typing import Any

from warden.shared.infrastructure.logging import get_logger
from warden.validation.domain.check import (
    CheckFinding,
    CheckResult,
    CheckSeverity,
    ValidationCheck,
)
from warden.validation.domain.fp_exclusions import get_fp_exclusion_registry
from warden.validation.domain.frame import CodeFile

logger = get_logger(__name__)

# Number of lines to read before/after a match for context analysis.
_CONTEXT_WINDOW = 7

# Base confidence values by pattern type.
# Reflects empirical FP rate for each pattern class in production codebases.
_PATTERN_CONFIDENCE: dict[str, float] = {
    "concat":        0.85,  # "SELECT..." + user_var   — fairly reliable
    "fstring":       0.87,  # f"SELECT...{var}"        — high precision
    "format_method": 0.80,  # "SELECT...".format(var)  — moderate
    "percent_fmt":   0.75,  # "SELECT..." % var        — noisy (DB driver %s params)
    "js_template":   0.80,  # `SELECT...${var}`        — moderate
    "go_sprintf":    0.80,  # fmt.Sprintf("SELECT...", — moderate
    "java_format":   0.80,  # String.format("SELECT... — moderate
}


class SQLInjectionCheck(ValidationCheck):
    """
    Detects SQL injection vulnerabilities.

    Patterns detected:
    - String concatenation: "SELECT * FROM users WHERE id = " + user_id
    - f-string interpolation: f"SELECT * FROM users WHERE id = {user_id}"
    - format() method: "SELECT * FROM users WHERE id = {}".format(user_id)
    - % formatting: "SELECT * FROM users WHERE id = %s" % user_id

    v2 improvements:
    - ±7 line context window for each match
    - FP exclusion registry (hard + soft exclusions)
    - pattern_confidence field set on each CheckFinding
    - Low-confidence findings routed to LLM verification

    Severity: CRITICAL (can lead to data breach)
    """

    id = "sql-injection"
    name = "SQL Injection Detection"
    description = "Detects SQL injection vulnerabilities in database queries"
    severity = CheckSeverity.CRITICAL
    version = "2.0.0"
    author = "Warden Security Team"
    enabled_by_default = True

    # SQL keywords (for detecting SQL queries)
    SQL_KEYWORDS = [
        "SELECT",
        "INSERT",
        "UPDATE",
        "DELETE",
        "DROP",
        "CREATE",
        "ALTER",
        "EXEC",
        "EXECUTE",
    ]

    # Dangerous patterns — tuple of (regex_pattern, description, confidence_key)
    DANGEROUS_PATTERNS = [
        # String concatenation
        (
            r'["\'](?:SELECT|INSERT|UPDATE|DELETE|DROP|CREATE|ALTER).*?["\'][\s]*\+',
            "String concatenation in SQL query",
            "concat",
        ),
        # f-string interpolation
        (
            r'f["\'](?:SELECT|INSERT|UPDATE|DELETE|DROP|CREATE|ALTER).*?\{.*?\}',
            "f-string interpolation in SQL query",
            "fstring",
        ),
        # .format() method
        (
            r'["\'](?:SELECT|INSERT|UPDATE|DELETE|DROP|CREATE|ALTER).*?["\']\.format\(',
            "String format() in SQL query",
            "format_method",
        ),
        # % formatting
        (
            r'["\'](?:SELECT|INSERT|UPDATE|DELETE|DROP|CREATE|ALTER).*?["\'][\s]*%',
            "% formatting in SQL query",
            "percent_fmt",
        ),
        # JavaScript/TypeScript template literals in SQL
        (
            r'`(?:SELECT|INSERT|UPDATE|DELETE|DROP|CREATE|ALTER)[^`]*\$\{',
            "JavaScript template literal interpolation in SQL query",
            "js_template",
        ),
        # Go: fmt.Sprintf with SQL keywords
        (
            r'fmt\.Sprintf\s*\(\s*["`](?:SELECT|INSERT|UPDATE|DELETE|DROP|CREATE|ALTER)',
            "Go fmt.Sprintf with SQL query (use parameterized queries)",
            "go_sprintf",
        ),
        # Java: String.format with SQL keywords
        (
            r'String\.format\s*\(\s*["\'](?:SELECT|INSERT|UPDATE|DELETE|DROP|CREATE|ALTER)',
            "Java String.format with SQL query (use PreparedStatement)",
            "java_format",
        ),
    ]

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialize SQL injection check."""
        super().__init__(config)

        # Load custom patterns from config
        custom_patterns = self.config.get("custom_patterns", [])
        self.patterns = self.DANGEROUS_PATTERNS + [
            (pattern, "Custom SQL injection pattern", "concat")
            for pattern in custom_patterns
        ]

        # Pre-compile all patterns once for performance
        self._compiled_patterns = [
            (re.compile(pattern_str, re.IGNORECASE), description, confidence_key)
            for pattern_str, description, confidence_key in self.patterns
        ]

        self._fp_registry = get_fp_exclusion_registry()

    async def execute_async(self, code_file: CodeFile, context=None) -> CheckResult:
        """
        Execute SQL injection detection with context-aware FP filtering.

        For each regex match:
          1. Extract ±7 lines of surrounding context
          2. Run FP exclusion registry (hard + soft exclusions)
          3. Assign pattern_confidence based on pattern type and exclusion result
          4. Include multi-line context in code_snippet for LLM verification
        """
        findings: list[CheckFinding] = []
        lines = code_file.content.split("\n")
        total_lines = len(lines)

        for compiled_pattern, description, confidence_key in self._compiled_patterns:
            for line_num, line in enumerate(lines, start=1):
                match = compiled_pattern.search(line)
                if not match:
                    continue

                # ── Context window ────────────────────────────────────────
                ctx_start = max(0, line_num - 1 - _CONTEXT_WINDOW)
                ctx_end = min(total_lines, line_num + _CONTEXT_WINDOW)
                context_before = lines[ctx_start : line_num - 1]
                context_after = lines[line_num : ctx_end]
                all_context = context_before + context_after

                # ── FP Exclusion Registry ─────────────────────────────────
                exclusion = self._fp_registry.check(
                    check_id=self.id,
                    matched_line=line,
                    context_lines=all_context,
                    file_path=str(code_file.path),
                )

                if exclusion.is_excluded:
                    logger.debug(
                        "sql_injection_fp_excluded",
                        line=line_num,
                        reason=exclusion.reason,
                        file=code_file.path,
                    )
                    continue

                # ── Suppression check ─────────────────────────────────────
                suppression_matcher = self._get_suppression_matcher(code_file.path)
                if suppression_matcher and suppression_matcher.is_suppressed(
                    line=line_num,
                    rule=self.id,
                    file_path=str(code_file.path),
                    code=code_file.content,
                ):
                    logger.debug(
                        "finding_suppressed_inline",
                        line=line_num,
                        rule=self.id,
                        file=code_file.path,
                    )
                    continue

                # ── Pattern confidence ────────────────────────────────────
                base_confidence = _PATTERN_CONFIDENCE.get(confidence_key, 0.80)
                confidence = (
                    exclusion.confidence_adjustment
                    if exclusion.confidence_adjustment is not None
                    else base_confidence
                )

                # ── Build multi-line code snippet ─────────────────────────
                # Include context lines so LLM verification has full picture.
                snippet_lines: list[str] = []
                for i, ctx_line in enumerate(lines[ctx_start:ctx_end], start=ctx_start + 1):
                    marker = ">>>" if i == line_num else "   "
                    snippet_lines.append(f"{marker} {i:4d}: {ctx_line}")
                code_snippet = "\n".join(snippet_lines)

                findings.append(
                    CheckFinding(
                        check_id=self.id,
                        check_name=self.name,
                        severity=self.severity,
                        message=f"Potential SQL injection: {description}",
                        location=f"{code_file.path}:{line_num}",
                        code_snippet=code_snippet,
                        suggestion=(
                            "Use parameterized queries instead:\n"
                            "✅ GOOD: cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))\n"
                            "✅ GOOD: cursor.execute('SELECT * FROM users WHERE id = :id', {'id': user_id})\n"
                            "❌ BAD: f'SELECT * FROM users WHERE id = {user_id}'"
                        ),
                        documentation_url="https://owasp.org/www-community/attacks/SQL_Injection",
                        pattern_confidence=confidence,
                    )
                )

        return CheckResult(
            check_id=self.id,
            check_name=self.name,
            passed=len(findings) == 0,
            findings=findings,
            metadata={
                "patterns_checked": len(self.patterns),
                "sql_keywords": self.SQL_KEYWORDS,
                "context_window_lines": _CONTEXT_WINDOW,
            },
        )
