"""
FP (False Positive) Exclusion Registry.

Provides hard exclusion lists and context-based confidence adjustment
for pattern-based security checks. Applied at check execution time —
before findings reach the LLM verification stage.

Three layers:
  1. Hard exclude — comment lines, library-safe patterns (finding dropped)
  2. Soft exclude — parameterization evidence, safe variable names
                    (confidence lowered; finding routed to LLM for review)
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)


# ─── Result ──────────────────────────────────────────────────────────────────


@dataclass
class ExclusionResult:
    """Outcome of a single FP exclusion check."""

    is_excluded: bool
    reason: str = ""
    # When is_excluded=False, optional confidence override (None → use check default).
    confidence_adjustment: float | None = None


# ─── Comment / Docstring Detection ───────────────────────────────────────────

_COMMENT_PATTERNS: list[re.Pattern] = [
    re.compile(r"^\s*#"),       # Python line comment
    re.compile(r"^\s*//"),      # JS / Go / Java line comment
    re.compile(r"^\s*/\*"),     # Block comment start  (/* ... )
    re.compile(r"^\s*\*\s"),    # Block comment continuation ( * ... )
    re.compile(r'^\s*"""'),     # Python triple-quote docstring opening
    re.compile(r"^\s*'''"),     # Python triple-quote docstring (single-quote)
    re.compile(r'^\s*""".*"""\s*$'),  # Inline triple-quote (one-liner)
]


def _is_comment_line(line: str) -> bool:
    """Return True when the line is a comment or docstring marker."""
    return any(p.match(line) for p in _COMMENT_PATTERNS)


# ─── Parameterization Evidence ────────────────────────────────────────────────
# Surrounding context showing the SQL string is parameterized.

_PARAMETERIZATION_PATTERNS: list[re.Pattern] = [
    # .execute(query, (params,)) or .execute("...", [params])
    re.compile(r'\.execute\s*\(\s*\w+,\s*[\(\[]', re.IGNORECASE),
    re.compile(r'\.execute\s*\(\s*["\'][^"\']*["\'],\s*[\(\[]', re.IGNORECASE),
    # asyncpg: pool.execute(sql, *params) / pool.fetch(sql, *params)
    re.compile(r'\._pool\.(execute|fetch|fetchrow|fetchval|executemany)\s*\(\s*\w+,\s*\*', re.IGNORECASE),
    re.compile(r'\.(execute|fetch|fetchrow|fetchval)\s*\(\s*\w+,\s*\*\w+', re.IGNORECASE),
    # cursor.execute("... %s", ...) — psycopg2 style
    re.compile(r'cursor\.execute\s*\(["\'][^"\']*%s', re.IGNORECASE),
    # cursor.execute("... ?", ...) — SQLite style
    re.compile(r'cursor\.execute\s*\(["\'][^"\']*\?', re.IGNORECASE),
    # PostgreSQL $1, $2 positional params (asyncpg style)
    re.compile(r'\$[1-9]\b'),
    # Java PreparedStatement
    re.compile(r'\bPreparedStatement\b'),
    # SQLAlchemy bindparams / text() parameterization
    re.compile(r'\bbindparams\b|\bbind_params\b', re.IGNORECASE),
    # params= keyword argument
    re.compile(r'\bparams\s*=\s*[\(\[{]'),
    # SQLAlchemy text() with named params
    re.compile(r'text\s*\(["\'][^"\']*:[a-z_]+', re.IGNORECASE),
    # params list building (conditions array pattern)
    re.compile(r'\bparams\.append\s*\(', re.IGNORECASE),
    re.compile(r'\bparams\.extend\s*\(', re.IGNORECASE),
]


def _has_parameterization_evidence(lines: list[str]) -> bool:
    """Return True if any surrounding line shows parameterized query usage."""
    combined = "\n".join(lines)
    return any(p.search(combined) for p in _PARAMETERIZATION_PATTERNS)


# ─── Safe Variable Names ──────────────────────────────────────────────────────
# Variables that hold whitelisted SQL fragments — not raw user input.

_SAFE_VARIABLE_PATTERNS: list[re.Pattern] = [
    re.compile(r'\b_SORT_CLAUSES\b'),
    re.compile(r'\b_ORDER_BY_MAP\b'),
    re.compile(r'\bALLOWED_(COLUMNS?|FIELDS?|TABLES?)\b', re.IGNORECASE),
    re.compile(r'\bSORT_(FIELDS?|COLUMNS?|MAP|OPTIONS?)\b', re.IGNORECASE),
    re.compile(r'\bORDER_(FIELDS?|COLUMNS?|MAP|OPTIONS?)\b', re.IGNORECASE),
    re.compile(r'\b(QUERY|SQL)_(TEMPLATE|MAP|MAPPING)\b', re.IGNORECASE),
    re.compile(r'\bCOLUMN_MAP\b', re.IGNORECASE),
    re.compile(r'\bFIELD_MAP\b', re.IGNORECASE),
    re.compile(r'\bSAFE_(COLUMNS?|FIELDS?|TABLES?)\b', re.IGNORECASE),
]


def _has_safe_variable_name(lines: list[str]) -> bool:
    """Return True if any line references a known-safe whitelist variable."""
    combined = "\n".join(lines)
    return any(p.search(combined) for p in _SAFE_VARIABLE_PATTERNS)


# ─── Library-Specific Safe Patterns ──────────────────────────────────────────
# These calls look dangerous to regex engines but are intrinsically safe.

_LIBRARY_SAFE_PATTERNS: dict[str, list[re.Pattern]] = {
    "sql-injection": [
        # Redis: eval() executes Lua scripts, not SQL
        re.compile(r'\bredis[\w_]*\.eval\s*\(', re.IGNORECASE),
        re.compile(r'\bredis[\w_]*\.execute_command\s*\(', re.IGNORECASE),
        re.compile(r'\bpipe[\w_]*\.execute\s*\(', re.IGNORECASE),  # Redis pipeline
        # Pattern definitions inside security check files
        re.compile(r'\bDANGEROUS_PATTERNS\s*[=:\[]'),
        re.compile(r'\bSQL_KEYWORDS\s*[=:\[]'),
        re.compile(r'\bSECURITY_PATTERNS\s*[=:\[]', re.IGNORECASE),
        # pytest parametrize (test decorator, not SQL)
        re.compile(r'@pytest\.mark\.parametrize', re.IGNORECASE),
    ],
    "xss": [
        # mark_safe() on a string literal is intentional escaping, not user input
        re.compile(r'\bmark_safe\s*\(\s*["\']', re.IGNORECASE),
        # Pattern definitions inside security check files
        re.compile(r'\bDANGEROUS_PATTERNS\s*[=:\[]'),
        # Redis eval() executes Lua scripts server-side, not browser-side — not XSS
        re.compile(r'\bredis[\w_]*\.eval\s*\(', re.IGNORECASE),
        re.compile(r'\bself\._client\.eval\s*\(', re.IGNORECASE),
        re.compile(r'\._client\.eval\s*\(', re.IGNORECASE),
    ],
    "path-traversal": [
        # Pattern definitions
        re.compile(r'\bDANGEROUS_PATTERNS\s*[=:\[]'),
    ],
    "command-injection": [
        # subprocess.run() with list form is safe (no shell=True)
        re.compile(r'subprocess\.(run|call|check_output)\s*\(\s*\[', re.IGNORECASE),
        re.compile(r'\bDANGEROUS_PATTERNS\s*[=:\[]'),
    ],
    # ── Resilience frame static checks ──────────────────────────────────────
    "timeout": [
        # Pattern/constant definitions inside warden check files — not real network calls
        re.compile(r'\bRISKY_PATTERNS\s*[=:\[]'),
        # requests.Session or httpx.Client configured once with timeout (caller passes it)
        re.compile(r'\bself\._session\b|\bself\._client\b', re.IGNORECASE),
        # Test fixtures: mock HTTP calls in test files never need real timeouts
        re.compile(r'\bMagicMock\b|\bpatch\b.*requests|\bresponses\.add\b', re.IGNORECASE),
    ],
    "circuit-breaker": [
        # Pattern definitions inside check files
        re.compile(r'\bGOOD_PATTERNS\s*[=:\[]|\bRISKY_PATTERNS\s*[=:\[]'),
        # Circuit breaker implementation files themselves
        re.compile(r'\bclass.*CircuitBreaker\b', re.IGNORECASE),
    ],
    "error-handling": [
        # Pattern definitions inside check files
        re.compile(r'\bRISKY_PATTERNS\s*[=:\[]|\bNETWORK_PATTERNS\s*[=:\[]'),
        # Re-raise patterns — bare except that immediately re-raises is fine
        re.compile(r'\bexcept\b.*:\s*\n\s*raise\b', re.IGNORECASE),
        # Test-only: catching in test assertions
        re.compile(r'\bpytest\.raises\b|\bassertRaises\b', re.IGNORECASE),
    ],
}


# ─── Main Registry ────────────────────────────────────────────────────────────


class FPExclusionRegistry:
    """
    Central False Positive Exclusion Registry.

    Call ``check()`` during pattern-match execution (before creating a finding)
    to decide whether the match is a known FP and what confidence to assign.
    """

    def check(
        self,
        check_id: str,
        matched_line: str,
        context_lines: list[str],
        file_path: str = "",
    ) -> ExclusionResult:
        """
        Evaluate a pattern match against all FP exclusion rules.

        Args:
            check_id:      Check identifier, e.g. ``"sql-injection"``
            matched_line:  The exact source line that triggered the pattern
            context_lines: Surrounding lines (typically ±7 from the match)
            file_path:     Source file path (reserved for future path-based rules)

        Returns:
            ExclusionResult:
              - ``is_excluded=True``  → skip this finding entirely
              - ``is_excluded=False`` → proceed; ``confidence_adjustment`` may
                lower the default confidence for soft FPs
        """
        # Layer 1: comment / docstring lines → hard exclude
        if _is_comment_line(matched_line):
            logger.debug("fp_excluded_comment", check=check_id, line=matched_line[:80])
            return ExclusionResult(is_excluded=True, reason="comment_line")

        # Layer 2: library-specific known-safe patterns → hard exclude
        safe_lib = _LIBRARY_SAFE_PATTERNS.get(check_id, [])
        all_lines = context_lines + [matched_line]
        for pattern in safe_lib:
            if any(pattern.search(line) for line in all_lines):
                logger.debug(
                    "fp_excluded_library_safe",
                    check=check_id,
                    pattern=pattern.pattern[:60],
                )
                return ExclusionResult(is_excluded=True, reason="library_safe_pattern")

        # Layer 3: parameterization evidence → soft (lower confidence)
        if check_id == "sql-injection" and _has_parameterization_evidence(context_lines):
            logger.debug("fp_confidence_reduced_parameterization", check=check_id)
            return ExclusionResult(
                is_excluded=False,
                reason="parameterization_in_context",
                confidence_adjustment=0.45,
            )

        # Layer 4: safe variable names → soft (lower confidence)
        if check_id == "sql-injection" and _has_safe_variable_name(all_lines):
            logger.debug("fp_confidence_reduced_safe_variable", check=check_id)
            return ExclusionResult(
                is_excluded=False,
                reason="safe_variable_name",
                confidence_adjustment=0.40,
            )

        return ExclusionResult(is_excluded=False)


# Module-level singleton — shared across all check instances.
_registry: FPExclusionRegistry = FPExclusionRegistry()


def get_fp_exclusion_registry() -> FPExclusionRegistry:
    """Return the global FP exclusion registry."""
    return _registry
