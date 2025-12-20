"""
Hardcoded Password Detection Check.

Detects hardcoded passwords in code:
- Variable assignments with "password" in name
- Configuration files with passwords
- Authentication code with hardcoded credentials
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


class HardcodedPasswordCheck(ValidationCheck):
    """
    Detects hardcoded passwords in code.

    Patterns detected:
    - password = "secret"
    - PASSWORD = "admin123"
    - pwd = "12345"
    - auth_token = "hardcoded_token"

    Severity: CRITICAL (credential exposure)
    """

    id = "hardcoded-password"
    name = "Hardcoded Password Detection"
    description = "Detects hardcoded passwords and authentication credentials"
    severity = CheckSeverity.CRITICAL
    version = "1.0.0"
    author = "Warden Security Team"
    enabled_by_default = True

    # Password-related variable names
    PASSWORD_KEYWORDS = [
        "password",
        "passwd",
        "pwd",
        "pass",
        "secret",
        "auth",
        "credential",
        "token",
        "key",
    ]

    # Weak/common passwords (for detection)
    COMMON_PASSWORDS = [
        "password",
        "admin",
        "root",
        "123456",
        "12345678",
        "qwerty",
        "abc123",
        "letmein",
        "monkey",
        "admin123",
    ]

    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        """Initialize hardcoded password check."""
        super().__init__(config)

        # Load custom keywords
        custom_keywords = self.config.get("custom_keywords", [])
        self.keywords = self.PASSWORD_KEYWORDS + custom_keywords

        # Build patterns
        self.patterns = self._build_patterns()

    def _build_patterns(self) -> List[tuple[str, str]]:
        """Build regex patterns for password detection."""
        patterns = []

        for keyword in self.keywords:
            # Pattern: keyword = "value" (with various quotes)
            patterns.append(
                (
                    rf'\b{keyword}\s*=\s*["\'][^"\'{{}}]+["\']',
                    f"Hardcoded {keyword} detected",
                )
            )

            # Pattern: keyword: "value" (YAML/JSON style)
            patterns.append(
                (
                    rf'\b{keyword}\s*:\s*["\'][^"\'{{}}]+["\']',
                    f"Hardcoded {keyword} in config",
                )
            )

        return patterns

    async def execute(self, code_file: CodeFile) -> CheckResult:
        """Execute hardcoded password detection."""
        findings: List[CheckFinding] = []

        for line_num, line in enumerate(code_file.content.split("\n"), start=1):
            # Skip if using environment variables (safe)
            if self._is_safe_pattern(line):
                continue

            # Check each pattern
            for pattern_str, description in self.patterns:
                pattern = re.compile(pattern_str, re.IGNORECASE)
                match = pattern.search(line)

                if match and self._is_likely_password(match.group(0)):
                    findings.append(
                        CheckFinding(
                            check_id=self.id,
                            check_name=self.name,
                            severity=self.severity,
                            message=description,
                            location=f"{code_file.path}:{line_num}",
                            code_snippet=self._mask_password(line.strip()),
                            suggestion=(
                                "Use environment variables or secret management:\n"
                                "✅ GOOD: password = os.getenv('DB_PASSWORD')\n"
                                "✅ GOOD: Use Azure Key Vault, AWS Secrets Manager\n"
                                "❌ BAD: password = 'hardcoded_secret'"
                            ),
                            documentation_url="https://cwe.mitre.org/data/definitions/798.html",
                        )
                    )
                    break  # Only report once per line

        # Check for common weak passwords
        findings.extend(self._check_weak_passwords(code_file))

        return CheckResult(
            check_id=self.id,
            check_name=self.name,
            passed=len(findings) == 0,
            findings=findings,
        )

    def _is_safe_pattern(self, line: str) -> bool:
        """Check if line uses safe patterns (env vars, etc.)."""
        safe_patterns = [
            r"os\.getenv\(",
            r"os\.environ\[",
            r"process\.env\.",
            r"System\.getenv\(",
            r"Environment\.GetEnvironmentVariable\(",
            r"input\(",  # User input (not hardcoded)
            r"getpass\(",  # Password prompt
        ]

        return any(re.search(pattern, line) for pattern in safe_patterns)

    def _is_likely_password(self, matched_text: str) -> bool:
        """
        Heuristic to determine if matched text is likely a password.

        Excludes:
        - Empty strings
        - Placeholder values (e.g., "your_password_here")
        - Short values (< 3 chars)
        """
        # Extract the value part
        value_match = re.search(r'["\']([^"\']+)["\']', matched_text)
        if not value_match:
            return False

        value = value_match.group(1).lower()

        # Exclude placeholders
        placeholders = [
            "your_password",
            "password_here",
            "enter_password",
            "change_me",
            "placeholder",
            "example",
            "todo",
            "xxx",
        ]

        if any(placeholder in value for placeholder in placeholders):
            return False

        # Exclude empty or very short values
        if len(value) < 3:
            return False

        # Exclude template variables
        if "{{" in value or "}}" in value or "${" in value:
            return False

        return True

    def _check_weak_passwords(self, code_file: CodeFile) -> List[CheckFinding]:
        """Check for common weak passwords."""
        findings: List[CheckFinding] = []

        for line_num, line in enumerate(code_file.content.split("\n"), start=1):
            for weak_password in self.COMMON_PASSWORDS:
                # Look for quoted weak passwords
                pattern = rf'["\']({weak_password})["\']'
                match = re.search(pattern, line, re.IGNORECASE)

                if match:
                    findings.append(
                        CheckFinding(
                            check_id=self.id,
                            check_name=self.name,
                            severity=CheckSeverity.HIGH,  # High, not critical
                            message=f"Common weak password detected: '{weak_password}'",
                            location=f"{code_file.path}:{line_num}",
                            code_snippet=self._mask_password(line.strip()),
                            suggestion=(
                                "Never use common passwords. Use strong, unique passwords:\n"
                                "✅ GOOD: Generated password from password manager\n"
                                "✅ GOOD: Environment variable with secure value\n"
                                f"❌ BAD: password = '{weak_password}' (easily guessed)"
                            ),
                            documentation_url="https://owasp.org/www-community/vulnerabilities/Use_of_hard-coded_password",
                        )
                    )
                    break

        return findings

    def _mask_password(self, line: str) -> str:
        """Mask passwords in line for display."""
        # Mask quoted strings that look like passwords
        return re.sub(r'(["\'])([^"\']{3,})(["\'])', r'\1***REDACTED***\3', line)
