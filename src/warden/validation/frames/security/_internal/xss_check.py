"""
XSS (Cross-Site Scripting) Detection Check.

Detects potential XSS vulnerabilities:
- Unescaped user input in HTML
- innerHTML usage
- Direct DOM manipulation with user data

v2: Context-aware matching with FP exclusion registry and pattern confidence.
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

_CONTEXT_WINDOW = 5  # XSS patterns are local; smaller window sufficient

# Base confidence by pattern — reflects empirical FP rate.
_PATTERN_CONFIDENCE: dict[str, float] = {
    "innerHTML":              0.85,
    "outerHTML":              0.85,
    "document.write":         0.80,
    "eval":                   0.65,  # eval() has many safe uses (JSON.parse polyfill, etc.)
    "dangerouslySetInnerHTML": 0.88,
    "safe_filter":            0.78,
    "mark_safe":              0.80,
    "template_literal_html":  0.75,
}

# Sanitizer evidence in context — lowers confidence for innerHTML/outerHTML
_SANITIZER_PATTERNS: list[re.Pattern] = [
    re.compile(r'\bDOMPurify\b', re.IGNORECASE),
    re.compile(r'\bsanitize\b', re.IGNORECASE),
    re.compile(r'\bescape\b', re.IGNORECASE),
    re.compile(r'\bencodeHTML\b', re.IGNORECASE),
    re.compile(r'\bescapeHtml\b', re.IGNORECASE),
    re.compile(r'\bxss\b', re.IGNORECASE),  # xss library
    re.compile(r'\bmark_safe\s*\(\s*format_html', re.IGNORECASE),  # Django safe via format_html
]


def _has_sanitizer_evidence(lines: list[str]) -> bool:
    combined = "\n".join(lines)
    return any(p.search(combined) for p in _SANITIZER_PATTERNS)


class XSSCheck(ValidationCheck):
    """
    Detects XSS (Cross-Site Scripting) vulnerabilities.

    Patterns detected:
    - innerHTML = user_input
    - document.write(user_input)
    - Direct HTML concatenation with user data
    - Unescaped template rendering

    v2 improvements:
    - ±5 line context window per match
    - FP exclusion registry (hard + soft)
    - pattern_confidence set per finding

    Severity: HIGH (can lead to session hijacking)
    """

    id = "xss"
    name = "XSS Detection"
    description = "Detects Cross-Site Scripting vulnerabilities"
    severity = CheckSeverity.HIGH
    version = "2.0.0"
    author = "Warden Security Team"
    enabled_by_default = True

    # (regex, description, confidence_key)
    DANGEROUS_PATTERNS = [
        (r"\.innerHTML\s*=", "innerHTML assignment (potential XSS)", "innerHTML"),
        (r"\.outerHTML\s*=", "outerHTML assignment (potential XSS)", "outerHTML"),
        (r"document\.write\(", "document.write() usage (potential XSS)", "document.write"),
        (r"eval\(", "eval() usage (code injection risk)", "eval"),
        (r"dangerouslySetInnerHTML", "dangerouslySetInnerHTML in React (XSS risk)", "dangerouslySetInnerHTML"),
        # Python/Django
        (r"\|safe\b", "Django template |safe filter (bypasses escaping)", "safe_filter"),
        (r"mark_safe\(", "Django mark_safe() (bypasses escaping)", "mark_safe"),
        # JavaScript template literals with user input
        (r"<[^>]*>\$\{", "Template literal in HTML (potential XSS)", "template_literal_html"),
    ]

    def __init__(self, config: Any | None = None) -> None:
        super().__init__(config)
        self._compiled_patterns = [
            (re.compile(pattern_str, re.IGNORECASE), description, confidence_key)
            for pattern_str, description, confidence_key in self.DANGEROUS_PATTERNS
        ]
        self._fp_registry = get_fp_exclusion_registry()

    async def execute_async(self, code_file: CodeFile, context=None) -> CheckResult:
        """Execute XSS detection with context-aware FP filtering."""
        findings: list[CheckFinding] = []
        lines = code_file.content.split("\n")
        total_lines = len(lines)

        for compiled_pattern, description, confidence_key in self._compiled_patterns:
            for line_num, line in enumerate(lines, start=1):
                if not compiled_pattern.search(line):
                    continue

                # ── Context window ─────────────────────────────────────────
                ctx_start = max(0, line_num - 1 - _CONTEXT_WINDOW)
                ctx_end = min(total_lines, line_num + _CONTEXT_WINDOW)
                context_before = lines[ctx_start : line_num - 1]
                context_after = lines[line_num : ctx_end]
                all_context = context_before + context_after

                # ── FP Exclusion Registry ──────────────────────────────────
                exclusion = self._fp_registry.check(
                    check_id=self.id,
                    matched_line=line,
                    context_lines=all_context,
                    file_path=str(code_file.path),
                )

                if exclusion.is_excluded:
                    logger.debug(
                        "xss_fp_excluded",
                        line=line_num,
                        reason=exclusion.reason,
                        file=code_file.path,
                    )
                    continue

                # ── Suppression check ──────────────────────────────────────
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

                # ── Pattern confidence ─────────────────────────────────────
                base_confidence = _PATTERN_CONFIDENCE.get(confidence_key, 0.78)
                if exclusion.confidence_adjustment is not None:
                    confidence = exclusion.confidence_adjustment
                elif _has_sanitizer_evidence(all_context):
                    confidence = base_confidence * 0.6  # Sanitizer nearby → lower
                else:
                    confidence = base_confidence

                # ── Multi-line snippet ─────────────────────────────────────
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
                        message=f"Potential XSS vulnerability: {description}",
                        location=f"{code_file.path}:{line_num}",
                        code_snippet=code_snippet,
                        suggestion=(
                            "Sanitize and escape user input:\n"
                            "✅ GOOD: element.textContent = userInput (safe)\n"
                            "✅ GOOD: Use DOMPurify or similar sanitization library\n"
                            "❌ BAD: element.innerHTML = userInput (XSS risk)"
                        ),
                        documentation_url="https://owasp.org/www-community/attacks/xss/",
                        pattern_confidence=confidence,
                    )
                )

        return CheckResult(
            check_id=self.id,
            check_name=self.name,
            passed=len(findings) == 0,
            findings=findings,
            metadata={"context_window_lines": _CONTEXT_WINDOW},
        )
