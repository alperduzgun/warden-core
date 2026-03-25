"""
Open Redirect Detection Check (CWE-601).

Detects unvalidated redirect destinations where user-controlled
input is passed directly to a redirect function without an allowlist.
"""

import re

from warden.shared.infrastructure.logging import get_logger
from warden.validation.domain.check import (
    CheckFinding,
    CheckResult,
    CheckSeverity,
    ValidationCheck,
)
from warden.validation.domain.frame import CodeFile

logger = get_logger(__name__)

# Regex fragments for user-controlled sources
_USER_SOURCES = (
    r"request\.(args|form|json|values|get_json|data|params|query)\b"
    r"|req\.(query|body|params)\b"
    r"|params\[|query\[|request\.GET\b|request\.POST\b"
    r"|getParameter\(|@RequestParam|@PathVariable"
    r"|c\.Query\(|c\.Param\(|r\.URL\.Query\(\)"
)

# Redirect sink patterns — these must appear on the SAME line as a user source
# OR the line contains a variable that smells like "next", "url", "redirect"
_REDIRECT_SINKS = [
    # Python / Flask
    (r"\bredirect\s*\(", "Flask/Python redirect()"),
    (r"\bflask\.redirect\s*\(", "flask.redirect()"),
    (r"\bHttpResponseRedirect\s*\(", "Django HttpResponseRedirect()"),
    # JavaScript / Express / Node
    (r"\bres\.redirect\s*\(", "Express res.redirect()"),
    (r"\bresponse\.redirect\s*\(", "response.redirect()"),
    # Go
    (r"\bhttp\.Redirect\s*\(", "Go http.Redirect()"),
    # Java Spring / Servlet
    (r"\bsendRedirect\s*\(", "HttpServletResponse.sendRedirect()"),
    (r"\bnew\s+RedirectView\s*\(", "Spring RedirectView"),
    (r"\"redirect:\s*\+", "Spring MVC redirect: concatenation"),
]

# Variable names that strongly suggest a user-controlled redirect target
_SUSPICIOUS_VAR_NAMES = re.compile(
    r"\b(next|redirect_url|redirect_uri|return_url|return_to|"
    r"callback_url|target_url|goto|redir|location|dest|destination)\b",
    re.IGNORECASE,
)

# Known safe validators — if any of these appear on the same or adjacent line,
# suppress the finding (reduce false positives).
_SAFE_VALIDATORS = re.compile(
    r"url_has_allowed_host_and_scheme|is_safe_url|validate_redirect|"
    r"allowedHosts\.includes|URL\.canParse|urllib\.parse\.urlparse|"
    r"validators\.url|is_trusted|whitelist|allowlist",
    re.IGNORECASE,
)


def _lines_around(lines: list[str], idx: int, window: int = 3) -> str:
    """Return a small window of lines around idx as a single string."""
    start = max(0, idx - window)
    end = min(len(lines), idx + window + 1)
    return "\n".join(lines[start:end])


class OpenRedirectCheck(ValidationCheck):
    """
    Detects open redirect vulnerabilities (CWE-601).

    Patterns detected:
    - redirect(request.args['next']) without allowlist validation
    - res.redirect(req.query.url) in Express without validation
    - HttpResponseRedirect using user-controlled parameters
    - Redirect with suspicious variable names (next, return_url, etc.)

    Severity: MEDIUM (can be used for phishing / credential theft)
    """

    id = "open-redirect"
    name = "Open Redirect Detection"
    description = "Detects unvalidated redirect destinations (CWE-601)"
    severity = CheckSeverity.MEDIUM
    version = "1.0.0"
    author = "Warden Security Team"
    enabled_by_default = True

    def __init__(self, config=None) -> None:
        super().__init__(config)
        self._source_re = re.compile(_USER_SOURCES)
        self._sink_patterns = [
            (re.compile(pat, re.IGNORECASE), label)
            for pat, label in _REDIRECT_SINKS
        ]

    async def execute_async(self, code_file: CodeFile) -> CheckResult:
        """Execute open redirect detection."""
        findings: list[CheckFinding] = []
        lines = code_file.content.split("\n")

        for idx, line in enumerate(lines):
            line_num = idx + 1

            # Must be a redirect sink
            sink_match = None
            for pattern, label in self._sink_patterns:
                if pattern.search(line):
                    sink_match = label
                    break
            if not sink_match:
                continue

            # Check for user-controlled source on this line OR suspicious var names
            context_window = _lines_around(lines, idx, window=4)
            has_user_source = bool(self._source_re.search(line))
            has_suspicious_var = bool(_SUSPICIOUS_VAR_NAMES.search(line))

            if not has_user_source and not has_suspicious_var:
                continue

            # Suppress if a validator is visible nearby
            if _SAFE_VALIDATORS.search(context_window):
                logger.debug(
                    "open_redirect_suppressed_by_validator",
                    file=str(code_file.path),
                    line=line_num,
                )
                continue

            # Check inline suppression
            suppression_matcher = self._get_suppression_matcher(code_file.path)
            if suppression_matcher and suppression_matcher.is_suppressed(
                line=line_num,
                rule=self.id,
                file_path=str(code_file.path),
                code=code_file.content,
            ):
                continue

            reason = (
                f"User-controlled input passed to {sink_match}"
                if has_user_source
                else f"Suspicious redirect variable in {sink_match}"
            )

            findings.append(
                CheckFinding(
                    check_id=self.id,
                    check_name=self.name,
                    severity=self.severity,
                    message=f"Open redirect risk: {reason}",
                    location=f"{code_file.path}:{line_num}",
                    code_snippet=line.strip(),
                    suggestion=(
                        "Validate redirect destination against an allowlist:\n"
                        "✅ GOOD: url_has_allowed_host_and_scheme(next_url, request)\n"
                        "✅ GOOD: if next_url in ALLOWED_REDIRECT_URLS: redirect(next_url)\n"
                        "❌ BAD:  redirect(request.args['next'])  # no validation"
                    ),
                    documentation_url="https://cwe.mitre.org/data/definitions/601.html",
                )
            )

        return CheckResult(
            check_id=self.id,
            check_name=self.name,
            passed=len(findings) == 0,
            findings=findings,
        )
