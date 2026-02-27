"""
CSRF (Cross-Site Request Forgery) Protection Detection Check.

Detects missing or disabled CSRF protection:
- Django @csrf_exempt on POST routes
- Missing CsrfViewMiddleware in Django
- Flask without flask-wtf CSRFProtect
- Express without csurf or equivalent CSRF middleware
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


class CSRFCheck(ValidationCheck):
    """
    Detects missing or disabled CSRF protection.

    Patterns detected:
    - Django @csrf_exempt decorator on views handling POST
    - Missing django.middleware.csrf.CsrfViewMiddleware in MIDDLEWARE
    - Flask applications without flask-wtf CSRFProtect
    - Express applications without csurf or equivalent CSRF middleware

    Severity: HIGH (can lead to unauthorized state-changing requests)
    """

    id = "csrf"
    name = "CSRF Protection Detection"
    description = "Detects missing or disabled CSRF protection"
    severity = CheckSeverity.HIGH
    version = "1.0.0"
    author = "Warden Security Team"
    enabled_by_default = True

    # Django CSRF patterns
    DJANGO_PATTERNS = [
        # @csrf_exempt decorator
        (
            r"""@csrf_exempt""",
            "Django @csrf_exempt disables CSRF protection on this view",
        ),
    ]

    # Django settings patterns (file-level checks)
    DJANGO_SETTINGS_PATTERNS = [
        # MIDDLEWARE without CsrfViewMiddleware
        (
            r"""MIDDLEWARE\s*=\s*\[""",
            "django_middleware_check",  # Special handler
        ),
    ]

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialize CSRF check."""
        super().__init__(config)

        # Pre-compile Django patterns
        self._compiled_django_patterns = [
            (re.compile(pattern_str), description) for pattern_str, description in self.DJANGO_PATTERNS
        ]

        # Pre-compile detection helpers
        self._csrf_exempt_pattern = re.compile(r"""@csrf_exempt""")
        self._csrf_exempt_import_pattern = re.compile(
            r"""from\s+django\.views\.decorators\.csrf\s+import\s+csrf_exempt"""
        )
        self._middleware_pattern = re.compile(r"""MIDDLEWARE\s*=\s*\[""")
        self._csrf_middleware_pattern = re.compile(r"""django\.middleware\.csrf\.CsrfViewMiddleware""")

        # Flask patterns
        self._flask_app_pattern = re.compile(r"""Flask\s*\(\s*__name__\s*\)""")
        self._flask_csrf_pattern = re.compile(r"""CSRFProtect\s*\(""")
        self._flask_wtf_import_pattern = re.compile(r"""from\s+flask_wtf\.csrf\s+import\s+CSRFProtect""")

        # Express patterns
        self._express_require_pattern = re.compile(r"""require\s*\(\s*['"]express['"]\s*\)""")
        self._express_import_pattern = re.compile(r"""import\s+.*\s+from\s+['"]express['"]""")
        self._csurf_pattern = re.compile(r"""csurf""")
        self._csrf_middleware_js_pattern = re.compile(r"""csrf|csrfProtection|csrfToken|_csrf""")

    async def execute_async(self, code_file: CodeFile) -> CheckResult:
        """Execute CSRF protection detection."""
        findings: list[CheckFinding] = []

        # Run language-appropriate checks
        if code_file.language == "python":
            findings.extend(self._check_django_csrf(code_file))
            findings.extend(self._check_django_middleware(code_file))
            findings.extend(self._check_flask_csrf(code_file))
        elif code_file.language in ("javascript", "typescript"):
            findings.extend(self._check_express_csrf(code_file))

        return CheckResult(
            check_id=self.id,
            check_name=self.name,
            passed=len(findings) == 0,
            findings=findings,
            metadata={
                "language": code_file.language,
            },
        )

    def _check_django_csrf(self, code_file: CodeFile) -> list[CheckFinding]:
        """Check for Django @csrf_exempt usage."""
        findings: list[CheckFinding] = []
        content = code_file.content

        # Only check if csrf_exempt is imported or used
        if not self._csrf_exempt_pattern.search(content):
            return findings

        lines = content.split("\n")

        for line_num, line in enumerate(lines, start=1):
            stripped = line.strip()

            # Skip comments
            if stripped.startswith("#"):
                continue

            # Detect @csrf_exempt decorator
            if self._csrf_exempt_pattern.search(stripped):
                # Look ahead to find the function name for better context
                func_name = self._find_next_function(lines, line_num - 1)

                suppression_matcher = self._get_suppression_matcher(code_file.path)
                if suppression_matcher and suppression_matcher.is_suppressed(
                    line=line_num,
                    rule=self.id,
                    file_path=str(code_file.path),
                    code=content,
                ):
                    continue

                message = "Django @csrf_exempt disables CSRF protection"
                if func_name:
                    message += f" on view '{func_name}'"

                findings.append(
                    CheckFinding(
                        check_id=self.id,
                        check_name=self.name,
                        severity=CheckSeverity.HIGH,
                        message=message,
                        location=f"{code_file.path}:{line_num}",
                        code_snippet=stripped,
                        suggestion=(
                            "Remove @csrf_exempt and handle CSRF properly:\n"
                            "- For API endpoints: Use Django REST Framework with token authentication\n"
                            "- For AJAX: Include CSRF token in request headers\n"
                            "- For forms: Use {% csrf_token %} template tag"
                        ),
                        documentation_url="https://docs.djangoproject.com/en/stable/ref/csrf/",
                    )
                )

        return findings

    def _check_django_middleware(self, code_file: CodeFile) -> list[CheckFinding]:
        """Check for missing CsrfViewMiddleware in Django settings."""
        findings: list[CheckFinding] = []
        content = code_file.content

        # Only check files that look like Django settings
        if not self._middleware_pattern.search(content):
            return findings

        # Check if CsrfViewMiddleware is present
        if self._csrf_middleware_pattern.search(content):
            return findings

        # Find the MIDDLEWARE line for location
        for line_num, line in enumerate(content.split("\n"), start=1):
            if self._middleware_pattern.search(line):
                suppression_matcher = self._get_suppression_matcher(code_file.path)
                if suppression_matcher and suppression_matcher.is_suppressed(
                    line=line_num,
                    rule=self.id,
                    file_path=str(code_file.path),
                    code=content,
                ):
                    continue

                findings.append(
                    CheckFinding(
                        check_id=self.id,
                        check_name=self.name,
                        severity=CheckSeverity.CRITICAL,
                        message="Django MIDDLEWARE is missing CsrfViewMiddleware (CSRF protection disabled)",
                        location=f"{code_file.path}:{line_num}",
                        code_snippet=line.strip(),
                        suggestion=(
                            "Add CsrfViewMiddleware to MIDDLEWARE:\n"
                            "MIDDLEWARE = [\n"
                            "    ...\n"
                            "    'django.middleware.csrf.CsrfViewMiddleware',\n"
                            "    ...\n"
                            "]"
                        ),
                        documentation_url="https://docs.djangoproject.com/en/stable/ref/csrf/",
                    )
                )
                break  # Only report once

        return findings

    def _check_flask_csrf(self, code_file: CodeFile) -> list[CheckFinding]:
        """Check for missing CSRF protection in Flask applications."""
        findings: list[CheckFinding] = []
        content = code_file.content

        # Only check Flask applications
        if not self._flask_app_pattern.search(content):
            return findings

        # Check if CSRFProtect is used
        has_csrf = bool(self._flask_csrf_pattern.search(content) or self._flask_wtf_import_pattern.search(content))

        if not has_csrf:
            # Find the Flask app instantiation for location
            for line_num, line in enumerate(content.split("\n"), start=1):
                if self._flask_app_pattern.search(line):
                    suppression_matcher = self._get_suppression_matcher(code_file.path)
                    if suppression_matcher and suppression_matcher.is_suppressed(
                        line=line_num,
                        rule=self.id,
                        file_path=str(code_file.path),
                        code=content,
                    ):
                        continue

                    findings.append(
                        CheckFinding(
                            check_id=self.id,
                            check_name=self.name,
                            severity=CheckSeverity.HIGH,
                            message="Flask application without CSRF protection (flask-wtf CSRFProtect not found)",
                            location=f"{code_file.path}:{line_num}",
                            code_snippet=line.strip(),
                            suggestion=(
                                "Add CSRF protection with flask-wtf:\n"
                                "from flask_wtf.csrf import CSRFProtect\n"
                                "csrf = CSRFProtect(app)\n\n"
                                "For API-only apps, consider token-based authentication instead."
                            ),
                            documentation_url="https://flask-wtf.readthedocs.io/en/stable/csrf.html",
                        )
                    )
                    break  # Only report once

        return findings

    def _check_express_csrf(self, code_file: CodeFile) -> list[CheckFinding]:
        """Check for missing CSRF protection in Express applications."""
        findings: list[CheckFinding] = []
        content = code_file.content

        # Only check Express applications
        is_express = bool(self._express_require_pattern.search(content) or self._express_import_pattern.search(content))

        if not is_express:
            return findings

        # Check if csurf or any CSRF middleware is used
        has_csrf = bool(self._csurf_pattern.search(content) or self._csrf_middleware_js_pattern.search(content))

        if not has_csrf:
            # Check if app handles POST/PUT/DELETE (state-changing operations)
            has_state_changing = bool(re.search(r"""\.(post|put|delete|patch)\s*\(""", content))

            if has_state_changing:
                # Find the express import for location
                for line_num, line in enumerate(content.split("\n"), start=1):
                    if self._express_require_pattern.search(line) or self._express_import_pattern.search(line):
                        suppression_matcher = self._get_suppression_matcher(code_file.path)
                        if suppression_matcher and suppression_matcher.is_suppressed(
                            line=line_num,
                            rule=self.id,
                            file_path=str(code_file.path),
                            code=content,
                        ):
                            continue

                        findings.append(
                            CheckFinding(
                                check_id=self.id,
                                check_name=self.name,
                                severity=CheckSeverity.HIGH,
                                message="Express application with state-changing routes but no CSRF protection",
                                location=f"{code_file.path}:{line_num}",
                                code_snippet=line.strip(),
                                suggestion=(
                                    "Add CSRF protection middleware:\n"
                                    "const csrf = require('csurf');\n"
                                    "app.use(csrf({ cookie: true }));\n\n"
                                    "Or use a modern alternative like csrf-csrf or lusca.\n"
                                    "For API-only apps, consider token-based authentication."
                                ),
                                documentation_url="https://owasp.org/www-community/attacks/csrf",
                            )
                        )
                        break  # Only report once

        return findings

    def _find_next_function(self, lines: list[str], start_idx: int) -> str | None:
        """Find the next function definition after a decorator."""
        for i in range(start_idx + 1, min(start_idx + 5, len(lines))):
            line = lines[i].strip()
            match = re.match(r"""(?:def|async\s+def)\s+(\w+)\s*\(""", line)
            if match:
                return match.group(1)
        return None
