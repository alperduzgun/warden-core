"""
Circuit Breaker Pattern Check.

Detects missing circuit breaker implementation for:
- External service calls
- Database connections
- Third-party APIs
"""

import re
from typing import List

from warden.validation.domain.check import (
    ValidationCheck,
    CheckResult,
    CheckFinding,
    CheckSeverity,
)
from warden.validation.domain.frame import CodeFile


class CircuitBreakerCheck(ValidationCheck):
    """
    Validates circuit breaker pattern implementation.

    Circuit breakers prevent cascading failures by:
    - Detecting repeated failures
    - Opening circuit (fast-fail)
    - Periodically testing recovery (half-open)
    - Closing circuit when healthy

    Severity: MEDIUM (important for production resilience)
    """

    id = "circuit-breaker"
    name = "Circuit Breaker Pattern Check"
    description = "Validates circuit breaker implementation for external dependencies"
    severity = CheckSeverity.MEDIUM
    version = "1.0.0"
    author = "Warden Chaos Team"
    enabled_by_default = True

    GOOD_PATTERNS = [
        r"CircuitBreaker",
        r"@circuit_breaker",
        r"pybreaker",
        r"aiobreaker",
        r"circuitbreaker",
    ]

    async def execute(self, code_file: CodeFile) -> CheckResult:
        """Execute circuit breaker check."""
        findings: List[CheckFinding] = []

        # Check if file has external calls but no circuit breaker
        has_external_calls = self._has_external_calls(code_file.content)
        has_circuit_breaker = self._has_circuit_breaker(code_file.content)

        if has_external_calls and not has_circuit_breaker:
            findings.append(
                CheckFinding(
                    check_id=self.id,
                    check_name=self.name,
                    severity=self.severity,
                    message="External service calls without circuit breaker pattern",
                    location=f"{code_file.path}:1",
                    code_snippet="(entire file)",
                    suggestion=(
                        "Implement circuit breaker to prevent cascading failures:\n\n"
                        "Python (pybreaker):\n"
                        "breaker = CircuitBreaker(fail_max=5, timeout_duration=60)\n\n"
                        "@breaker\n"
                        "def call_external_service():\n"
                        "    return requests.get(url, timeout=30)\n\n"
                        "Benefits:\n"
                        "- Prevents cascading failures\n"
                        "- Fast-fail when service is down\n"
                        "- Automatic recovery detection"
                    ),
                    documentation_url="https://github.com/danielfm/pybreaker",
                )
            )

        return CheckResult(
            check_id=self.id,
            check_name=self.name,
            passed=len(findings) == 0,
            findings=findings,
            metadata={
                "has_external_calls": has_external_calls,
                "has_circuit_breaker": has_circuit_breaker,
            },
        )

    def _has_external_calls(self, content: str) -> bool:
        """Check if code calls external services."""
        patterns = [
            r"requests\.",
            r"httpx\.",
            r"http://",
            r"https://",
            r"api\.",
        ]
        return any(re.search(pattern, content, re.IGNORECASE) for pattern in patterns)

    def _has_circuit_breaker(self, content: str) -> bool:
        """Check if code has circuit breaker implementation."""
        return any(re.search(pattern, content, re.IGNORECASE) for pattern in self.GOOD_PATTERNS)
