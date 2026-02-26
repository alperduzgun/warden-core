"""
HTTP Security Misconfiguration Detection Check.

Detects HTTP security misconfigurations:
- Permissive CORS configurations (Express, Django, FastAPI)
- Cookies without Secure, HttpOnly, SameSite flags
- Missing helmet() middleware in Express applications
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
from warden.validation.domain.frame import CodeFile

logger = get_logger(__name__)


class HTTPSecurityCheck(ValidationCheck):
    """
    Detects HTTP security misconfigurations.

    Patterns detected:
    - cors({ origin: '*' }) in Express
    - app.use(cors()) without configuration
    - Django CORS_ALLOW_ALL_ORIGINS = True
    - FastAPI allow_origins=["*"]
    - Cookies without Secure, HttpOnly, SameSite flags
    - Missing helmet() middleware in Express

    Severity: HIGH (can lead to cross-origin attacks and data theft)
    """

    id = "http-security"
    name = "HTTP Security Misconfiguration Detection"
    description = "Detects CORS, cookie, and security header misconfigurations"
    severity = CheckSeverity.HIGH
    version = "1.0.0"
    author = "Warden Security Team"
    enabled_by_default = True

    # CORS misconfiguration patterns
    CORS_PATTERNS = [
        # Express: cors({ origin: '*' }) or cors({origin: "*"})
        (
            r"""cors\(\s*\{[^}]*origin\s*:\s*['"][*]['"]""",
            "CORS configured with wildcard origin (allows any domain)",
        ),
        # Express: app.use(cors()) with no arguments
        (
            r"""\.use\(\s*cors\(\s*\)\s*\)""",
            "CORS middleware used without configuration (allows all origins by default)",
        ),
        # Django: CORS_ALLOW_ALL_ORIGINS = True
        (
            r"""CORS_ALLOW_ALL_ORIGINS\s*=\s*True""",
            "Django CORS allows all origins",
        ),
        # Django legacy: CORS_ORIGIN_ALLOW_ALL = True
        (
            r"""CORS_ORIGIN_ALLOW_ALL\s*=\s*True""",
            "Django CORS allows all origins (legacy setting)",
        ),
        # FastAPI: allow_origins=["*"]
        (
            r"""allow_origins\s*=\s*\[\s*['"][*]['"]\s*\]""",
            "FastAPI CORS allows wildcard origin",
        ),
        # Flask-CORS: CORS(app, resources={r"/*": {"origins": "*"}})
        (
            r"""origins['"]\s*:\s*['"][*]['"]""",
            "Flask CORS configured with wildcard origin",
        ),
        # Generic Access-Control-Allow-Origin: *
        (
            r"""Access-Control-Allow-Origin['"].*['"]\*['"]""",
            "Access-Control-Allow-Origin header set to wildcard",
        ),
    ]

    # Insecure cookie patterns
    COOKIE_PATTERNS = [
        # Express: res.cookie() without secure flag
        (
            r"""\.cookie\s*\([^)]*\)""",
            "cookie_check",  # Special handler - needs deeper inspection
        ),
        # Python: set_cookie without secure/httponly
        (
            r"""set_cookie\s*\([^)]*\)""",
            "set_cookie_check",  # Special handler
        ),
        # Django: SESSION_COOKIE_SECURE = False
        (
            r"""SESSION_COOKIE_SECURE\s*=\s*False""",
            "Django session cookie not marked as Secure",
        ),
        # Django: CSRF_COOKIE_SECURE = False
        (
            r"""CSRF_COOKIE_SECURE\s*=\s*False""",
            "Django CSRF cookie not marked as Secure",
        ),
        # Django: SESSION_COOKIE_HTTPONLY = False
        (
            r"""SESSION_COOKIE_HTTPONLY\s*=\s*False""",
            "Django session cookie not marked as HttpOnly",
        ),
        # Django: CSRF_COOKIE_HTTPONLY = False
        (
            r"""CSRF_COOKIE_HTTPONLY\s*=\s*False""",
            "Django CSRF cookie not marked as HttpOnly",
        ),
        # Django: SESSION_COOKIE_SAMESITE set to None or False
        (
            r"""SESSION_COOKIE_SAMESITE\s*=\s*(?:None|False|'None')""",
            "Django session cookie SameSite not set or disabled",
        ),
    ]

    # Missing security headers patterns
    HEADER_PATTERNS = [
        # Express app without helmet
        (
            r"""require\s*\(\s*['"]express['"]\s*\)""",
            "express_helmet_check",  # Special handler - checks file for helmet usage
        ),
        # Express import without helmet
        (
            r"""import\s+.*\s+from\s+['"]express['"]""",
            "express_helmet_check_esm",  # Special handler
        ),
    ]

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialize HTTP security check."""
        super().__init__(config)

        # Pre-compile CORS patterns
        self._compiled_cors_patterns = [
            (re.compile(pattern_str, re.IGNORECASE), description)
            for pattern_str, description in self.CORS_PATTERNS
        ]

        # Pre-compile cookie patterns (non-special ones)
        self._compiled_cookie_patterns = [
            (re.compile(pattern_str), description)
            for pattern_str, description in self.COOKIE_PATTERNS
            if description not in ("cookie_check", "set_cookie_check")
        ]

        # Pre-compile special cookie patterns
        self._cookie_call_pattern = re.compile(r"""\.cookie\s*\(""")
        self._set_cookie_call_pattern = re.compile(r"""set_cookie\s*\(""")

        # Pre-compile header patterns
        self._express_require_pattern = re.compile(
            r"""require\s*\(\s*['"]express['"]\s*\)"""
        )
        self._express_import_pattern = re.compile(
            r"""import\s+.*\s+from\s+['"]express['"]"""
        )
        self._helmet_pattern = re.compile(r"""helmet\s*\(""")

    async def execute_async(self, code_file: CodeFile) -> CheckResult:
        """Execute HTTP security misconfiguration detection."""
        findings: list[CheckFinding] = []

        # Run all sub-checks
        findings.extend(self._check_cors(code_file))
        findings.extend(self._check_cookies(code_file))
        findings.extend(self._check_missing_headers(code_file))

        return CheckResult(
            check_id=self.id,
            check_name=self.name,
            passed=len(findings) == 0,
            findings=findings,
            metadata={
                "cors_patterns_checked": len(self.CORS_PATTERNS),
                "cookie_patterns_checked": len(self.COOKIE_PATTERNS),
            },
        )

    def _check_cors(self, code_file: CodeFile) -> list[CheckFinding]:
        """Check for CORS misconfigurations."""
        findings: list[CheckFinding] = []

        for line_num, line in enumerate(code_file.content.split("\n"), start=1):
            stripped = line.strip()

            # Skip comments
            if stripped.startswith("#") or stripped.startswith("//"):
                continue

            for compiled_pattern, description in self._compiled_cors_patterns:
                if compiled_pattern.search(line):
                    # Check suppression
                    suppression_matcher = self._get_suppression_matcher(code_file.path)
                    if suppression_matcher and suppression_matcher.is_suppressed(
                        line=line_num,
                        rule=self.id,
                        file_path=str(code_file.path),
                        code=code_file.content,
                    ):
                        continue

                    findings.append(
                        CheckFinding(
                            check_id=self.id,
                            check_name=self.name,
                            severity=CheckSeverity.HIGH,
                            message=f"CORS misconfiguration: {description}",
                            location=f"{code_file.path}:{line_num}",
                            code_snippet=stripped,
                            suggestion=(
                                "Restrict CORS to specific trusted origins:\n"
                                "Express: cors({ origin: ['https://myapp.com'] })\n"
                                "Django: CORS_ALLOWED_ORIGINS = ['https://myapp.com']\n"
                                "FastAPI: allow_origins=['https://myapp.com']"
                            ),
                            documentation_url="https://owasp.org/www-community/attacks/CORS_OriginHeaderScrutiny",
                        )
                    )

        return findings

    def _check_cookies(self, code_file: CodeFile) -> list[CheckFinding]:
        """Check for insecure cookie configurations."""
        findings: list[CheckFinding] = []
        lines = code_file.content.split("\n")

        for line_num, line in enumerate(lines, start=1):
            stripped = line.strip()

            # Skip comments
            if stripped.startswith("#") or stripped.startswith("//"):
                continue

            # Check Django-style cookie settings
            for compiled_pattern, description in self._compiled_cookie_patterns:
                if compiled_pattern.search(line):
                    suppression_matcher = self._get_suppression_matcher(code_file.path)
                    if suppression_matcher and suppression_matcher.is_suppressed(
                        line=line_num,
                        rule=self.id,
                        file_path=str(code_file.path),
                        code=code_file.content,
                    ):
                        continue

                    findings.append(
                        CheckFinding(
                            check_id=self.id,
                            check_name=self.name,
                            severity=CheckSeverity.MEDIUM,
                            message=f"Insecure cookie configuration: {description}",
                            location=f"{code_file.path}:{line_num}",
                            code_snippet=stripped,
                            suggestion=(
                                "Set secure cookie flags:\n"
                                "Django: SESSION_COOKIE_SECURE = True, SESSION_COOKIE_HTTPONLY = True\n"
                                "Express: res.cookie('name', 'val', { secure: true, httpOnly: true, sameSite: 'strict' })\n"
                                "Flask: response.set_cookie('name', 'val', secure=True, httponly=True, samesite='Strict')"
                            ),
                            documentation_url="https://owasp.org/www-community/controls/SecureCookieAttribute",
                        )
                    )

            # Check Express .cookie() calls for missing flags
            if self._cookie_call_pattern.search(line):
                cookie_context = self._get_multiline_context(lines, line_num - 1, max_lines=5)
                missing_flags = self._check_express_cookie_flags(cookie_context)
                if missing_flags:
                    suppression_matcher = self._get_suppression_matcher(code_file.path)
                    if suppression_matcher and suppression_matcher.is_suppressed(
                        line=line_num,
                        rule=self.id,
                        file_path=str(code_file.path),
                        code=code_file.content,
                    ):
                        continue

                    findings.append(
                        CheckFinding(
                            check_id=self.id,
                            check_name=self.name,
                            severity=CheckSeverity.MEDIUM,
                            message=f"Cookie missing security flags: {', '.join(missing_flags)}",
                            location=f"{code_file.path}:{line_num}",
                            code_snippet=stripped,
                            suggestion=(
                                "Add security flags to cookies:\n"
                                "res.cookie('name', 'value', {\n"
                                "  secure: true,\n"
                                "  httpOnly: true,\n"
                                "  sameSite: 'strict'\n"
                                "})"
                            ),
                            documentation_url="https://owasp.org/www-community/controls/SecureCookieAttribute",
                        )
                    )

            # Check Python set_cookie() calls for missing flags
            if self._set_cookie_call_pattern.search(line):
                cookie_context = self._get_multiline_context(lines, line_num - 1, max_lines=5)
                missing_flags = self._check_python_cookie_flags(cookie_context)
                if missing_flags:
                    suppression_matcher = self._get_suppression_matcher(code_file.path)
                    if suppression_matcher and suppression_matcher.is_suppressed(
                        line=line_num,
                        rule=self.id,
                        file_path=str(code_file.path),
                        code=code_file.content,
                    ):
                        continue

                    findings.append(
                        CheckFinding(
                            check_id=self.id,
                            check_name=self.name,
                            severity=CheckSeverity.MEDIUM,
                            message=f"Cookie missing security flags: {', '.join(missing_flags)}",
                            location=f"{code_file.path}:{line_num}",
                            code_snippet=stripped,
                            suggestion=(
                                "Add security flags to cookies:\n"
                                "response.set_cookie('name', 'value', secure=True, httponly=True, samesite='Strict')"
                            ),
                            documentation_url="https://owasp.org/www-community/controls/SecureCookieAttribute",
                        )
                    )

        return findings

    def _check_missing_headers(self, code_file: CodeFile) -> list[CheckFinding]:
        """Check for missing security headers (helmet in Express)."""
        findings: list[CheckFinding] = []
        content = code_file.content

        # Only check JavaScript/TypeScript files
        if code_file.language not in ("javascript", "typescript"):
            return findings

        # Check if this is an Express application
        is_express = bool(
            self._express_require_pattern.search(content)
            or self._express_import_pattern.search(content)
        )

        if not is_express:
            return findings

        # Check if helmet is used
        has_helmet = bool(self._helmet_pattern.search(content))

        if not has_helmet:
            # Find the express import/require line for location
            for line_num, line in enumerate(content.split("\n"), start=1):
                if self._express_require_pattern.search(line) or self._express_import_pattern.search(line):
                    suppression_matcher = self._get_suppression_matcher(code_file.path)
                    if suppression_matcher and suppression_matcher.is_suppressed(
                        line=line_num,
                        rule=self.id,
                        file_path=str(code_file.path),
                        code=code_file.content,
                    ):
                        continue

                    findings.append(
                        CheckFinding(
                            check_id=self.id,
                            check_name=self.name,
                            severity=CheckSeverity.MEDIUM,
                            message="Express application without helmet() middleware (missing security headers)",
                            location=f"{code_file.path}:{line_num}",
                            code_snippet=line.strip(),
                            suggestion=(
                                "Add helmet middleware for security headers:\n"
                                "const helmet = require('helmet');\n"
                                "app.use(helmet());\n\n"
                                "Helmet sets headers like X-Content-Type-Options, "
                                "X-Frame-Options, Strict-Transport-Security, etc."
                            ),
                            documentation_url="https://helmetjs.github.io/",
                        )
                    )
                    break  # Only report once

        return findings

    def _get_multiline_context(
        self, lines: list[str], start_idx: int, max_lines: int = 5
    ) -> str:
        """Get multiline context starting from a line index."""
        end_idx = min(start_idx + max_lines, len(lines))
        return "\n".join(lines[start_idx:end_idx])

    def _check_express_cookie_flags(self, context: str) -> list[str]:
        """Check if Express cookie call has required security flags."""
        missing = []

        # If the cookie call has an options object, check for flags
        # Simple case: no options object at all (just name and value)
        if "{" not in context:
            return ["secure", "httpOnly", "sameSite"]

        lower_context = context.lower()
        if "secure" not in lower_context:
            missing.append("secure")
        if "httponly" not in lower_context:
            missing.append("httpOnly")
        if "samesite" not in lower_context:
            missing.append("sameSite")

        return missing

    def _check_python_cookie_flags(self, context: str) -> list[str]:
        """Check if Python set_cookie call has required security flags."""
        missing = []
        lower_context = context.lower()

        if "secure" not in lower_context:
            missing.append("secure")
        if "httponly" not in lower_context:
            missing.append("httponly")
        if "samesite" not in lower_context:
            missing.append("samesite")

        return missing
