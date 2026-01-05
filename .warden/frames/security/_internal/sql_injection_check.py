"""
SQL Injection Detection Check.

Detects potential SQL injection vulnerabilities:
- String concatenation in SQL queries
- f-strings in SQL queries
- Lack of parameterized queries
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


class SQLInjectionCheck(ValidationCheck):
    """
    Detects SQL injection vulnerabilities.

    Patterns detected:
    - String concatenation: "SELECT * FROM users WHERE id = " + user_id
    - f-string interpolation: f"SELECT * FROM users WHERE id = {user_id}"
    - format() method: "SELECT * FROM users WHERE id = {}".format(user_id)
    - % formatting: "SELECT * FROM users WHERE id = %s" % user_id

    Severity: CRITICAL (can lead to data breach)
    """

    id = "sql-injection"
    name = "SQL Injection Detection"
    description = "Detects SQL injection vulnerabilities in database queries"
    severity = CheckSeverity.CRITICAL
    version = "1.0.0"
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

    # Dangerous patterns
    DANGEROUS_PATTERNS = [
        # String concatenation
        (
            r'["\'](?:SELECT|INSERT|UPDATE|DELETE|DROP|CREATE|ALTER).*?["\'][\s]*\+',
            "String concatenation in SQL query",
        ),
        # f-string interpolation
        (
            r'f["\'](?:SELECT|INSERT|UPDATE|DELETE|DROP|CREATE|ALTER).*?\{.*?\}',
            "f-string interpolation in SQL query",
        ),
        # .format() method
        (
            r'["\'](?:SELECT|INSERT|UPDATE|DELETE|DROP|CREATE|ALTER).*?["\']\.format\(',
            "String format() in SQL query",
        ),
        # % formatting
        (
            r'["\'](?:SELECT|INSERT|UPDATE|DELETE|DROP|CREATE|ALTER).*?["\'][\s]*%',
            "% formatting in SQL query",
        ),
    ]

    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        """Initialize SQL injection check."""
        super().__init__(config)

        # Load custom patterns from config
        custom_patterns = self.config.get("custom_patterns", [])
        self.patterns = self.DANGEROUS_PATTERNS + [
            (pattern, "Custom SQL injection pattern") for pattern in custom_patterns
        ]

    async def execute(self, code_file: CodeFile) -> CheckResult:
        """
        Execute SQL injection detection.

        Args:
            code_file: Code file to check

        Returns:
            CheckResult with findings
        """
        findings: List[CheckFinding] = []

        # Check each pattern
        for pattern_str, description in self.patterns:
            pattern = re.compile(pattern_str, re.IGNORECASE)

            for line_num, line in enumerate(code_file.content.split("\n"), start=1):
                match = pattern.search(line)
                if match:
                    findings.append(
                        CheckFinding(
                            check_id=self.id,
                            check_name=self.name,
                            severity=self.severity,
                            message=f"Potential SQL injection: {description}",
                            location=f"{code_file.path}:{line_num}",
                            code_snippet=line.strip(),
                            suggestion=(
                                "Use parameterized queries instead:\n"
                                "✅ GOOD: cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))\n"
                                "✅ GOOD: cursor.execute('SELECT * FROM users WHERE id = :id', {'id': user_id})\n"
                                "❌ BAD: f'SELECT * FROM users WHERE id = {user_id}'"
                            ),
                            documentation_url="https://owasp.org/www-community/attacks/SQL_Injection",
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
            },
        )
