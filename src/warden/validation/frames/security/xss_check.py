"""
XSS (Cross-Site Scripting) Detection Check.

Detects potential XSS vulnerabilities:
- Unescaped user input in HTML
- innerHTML usage
- Direct DOM manipulation with user data
"""

import re
from typing import List, Dict, Any

from warden.validation.domain.check import (
    ValidationCheck,
    CheckResult,
    CheckFinding,
    CheckSeverity,
)
from warden.validation.domain.frame import CodeFile


class XSSCheck(ValidationCheck):
    """
    Detects XSS (Cross-Site Scripting) vulnerabilities.

    Patterns detected:
    - innerHTML = user_input
    - document.write(user_input)
    - Direct HTML concatenation with user data
    - Unescaped template rendering

    Severity: HIGH (can lead to session hijacking)
    """

    id = "xss"
    name = "XSS Detection"
    description = "Detects Cross-Site Scripting vulnerabilities"
    severity = CheckSeverity.HIGH
    version = "1.0.0"
    author = "Warden Security Team"
    enabled_by_default = True

    DANGEROUS_PATTERNS = [
        (r"\.innerHTML\s*=", "innerHTML assignment (potential XSS)"),
        (r"\.outerHTML\s*=", "outerHTML assignment (potential XSS)"),
        (r"document\.write\(", "document.write() usage (potential XSS)"),
        (r"eval\(", "eval() usage (code injection risk)"),
        (r"dangerouslySetInnerHTML", "dangerouslySetInnerHTML in React (XSS risk)"),
        # Python/Django
        (r"\|safe\b", "Django template |safe filter (bypasses escaping)"),
        (r"mark_safe\(", "Django mark_safe() (bypasses escaping)"),
        # JavaScript template literals with user input
        (r"<[^>]*>\$\{", "Template literal in HTML (potential XSS)"),
    ]

    async def execute(self, code_file: CodeFile) -> CheckResult:
        """Execute XSS detection."""
        findings: List[CheckFinding] = []

        for pattern_str, description in self.DANGEROUS_PATTERNS:
            pattern = re.compile(pattern_str, re.IGNORECASE)

            for line_num, line in enumerate(code_file.content.split("\n"), start=1):
                if pattern.search(line):
                    findings.append(
                        CheckFinding(
                            check_id=self.id,
                            check_name=self.name,
                            severity=self.severity,
                            message=f"Potential XSS vulnerability: {description}",
                            location=f"{code_file.path}:{line_num}",
                            code_snippet=line.strip(),
                            suggestion=(
                                "Sanitize and escape user input:\n"
                                "✅ GOOD: element.textContent = userInput (safe)\n"
                                "✅ GOOD: Use DOMPurify or similar sanitization library\n"
                                "❌ BAD: element.innerHTML = userInput (XSS risk)"
                            ),
                            documentation_url="https://owasp.org/www-community/attacks/xss/",
                        )
                    )

        return CheckResult(
            check_id=self.id,
            check_name=self.name,
            passed=len(findings) == 0,
            findings=findings,
        )
