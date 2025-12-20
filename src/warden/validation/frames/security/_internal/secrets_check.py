"""
Secrets Detection Check.

Detects hardcoded secrets and credentials:
- API keys
- Access tokens
- Private keys
- Database credentials
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


class SecretsCheck(ValidationCheck):
    """
    Detects hardcoded secrets and credentials.

    Patterns detected:
    - API keys (AWS, OpenAI, GitHub, etc.)
    - Access tokens
    - Private keys (RSA, SSH)
    - Connection strings with passwords
    - JWT tokens

    Severity: CRITICAL (credential exposure)
    """

    id = "secrets"
    name = "Secrets Detection"
    description = "Detects hardcoded secrets, API keys, and credentials"
    severity = CheckSeverity.CRITICAL
    version = "1.0.0"
    author = "Warden Security Team"
    enabled_by_default = True

    # Common secret patterns
    SECRET_PATTERNS = [
        # AWS
        (r"AKIA[0-9A-Z]{16}", "AWS Access Key ID"),
        (r"aws_secret_access_key\s*=\s*['\"][^'\"]+['\"]", "AWS Secret Access Key"),
        # OpenAI
        (r"sk-[a-zA-Z0-9]{40,}", "OpenAI API Key"),
        # GitHub
        (r"ghp_[a-zA-Z0-9]{36}", "GitHub Personal Access Token"),
        (r"gho_[a-zA-Z0-9]{36}", "GitHub OAuth Token"),
        # Generic API keys
        (r"api[_-]?key\s*=\s*['\"][a-zA-Z0-9]{20,}['\"]", "Generic API Key"),
        (r"apikey\s*=\s*['\"][a-zA-Z0-9]{20,}['\"]", "Generic API Key"),
        # Private keys
        (r"-----BEGIN (?:RSA |DSA )?PRIVATE KEY-----", "Private Key"),
        (r"-----BEGIN OPENSSH PRIVATE KEY-----", "SSH Private Key"),
        # JWT tokens
        (r"eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}", "JWT Token"),
        # Database credentials
        (
            r"(?:mysql|postgres|mongodb)://[^:]+:[^@]+@",
            "Database connection string with password",
        ),
        # Slack tokens
        (r"xox[baprs]-[a-zA-Z0-9-]{10,}", "Slack Token"),
        # Stripe keys
        (r"sk_live_[a-zA-Z0-9]{24,}", "Stripe Secret Key"),
        (r"rk_live_[a-zA-Z0-9]{24,}", "Stripe Restricted Key"),
    ]

    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        """Initialize secrets check."""
        super().__init__(config)

        # Load custom patterns from config
        custom_patterns = self.config.get("custom_patterns", [])
        self.patterns = self.SECRET_PATTERNS + [
            (pattern, "Custom secret pattern") for pattern in custom_patterns
        ]

        # Exclusions (environment variable usage is OK)
        self.allowed_patterns = self.config.get(
            "allowed_patterns",
            [
                r"os\.getenv\(",
                r"os\.environ\[",
                r"process\.env\.",
                r"System\.getenv\(",
                r"Environment\.GetEnvironmentVariable\(",
            ],
        )

    async def execute(self, code_file: CodeFile) -> CheckResult:
        """Execute secrets detection."""
        findings: List[CheckFinding] = []

        for line_num, line in enumerate(code_file.content.split("\n"), start=1):
            # Skip if line uses environment variables (safe)
            if any(re.search(allowed, line) for allowed in self.allowed_patterns):
                continue

            # Check for secret patterns
            for pattern_str, secret_type in self.patterns:
                pattern = re.compile(pattern_str, re.IGNORECASE)
                match = pattern.search(line)

                if match:
                    # Mask the secret in the message
                    masked_secret = self._mask_secret(match.group(0))

                    findings.append(
                        CheckFinding(
                            check_id=self.id,
                            check_name=self.name,
                            severity=self.severity,
                            message=f"Hardcoded secret detected: {secret_type}",
                            location=f"{code_file.path}:{line_num}",
                            code_snippet=self._mask_line(line.strip()),
                            suggestion=(
                                f"Move {secret_type} to environment variables:\n"
                                "✅ GOOD: api_key = os.getenv('API_KEY')\n"
                                "✅ GOOD: Use secret management (AWS Secrets Manager, Azure Key Vault)\n"
                                f"❌ BAD: api_key = '{masked_secret}' (hardcoded)"
                            ),
                            documentation_url="https://owasp.org/www-community/vulnerabilities/Use_of_hard-coded_password",
                        )
                    )

        return CheckResult(
            check_id=self.id,
            check_name=self.name,
            passed=len(findings) == 0,
            findings=findings,
            metadata={
                "patterns_checked": len(self.patterns),
            },
        )

    def _mask_secret(self, secret: str) -> str:
        """Mask secret for display (show first/last chars only)."""
        if len(secret) <= 8:
            return "***"
        return f"{secret[:4]}...{secret[-4:]}"

    def _mask_line(self, line: str) -> str:
        """Mask secrets in entire line."""
        for pattern_str, _ in self.patterns:
            pattern = re.compile(pattern_str, re.IGNORECASE)
            line = pattern.sub("***REDACTED***", line)
        return line
