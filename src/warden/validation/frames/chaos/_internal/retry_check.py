"""
Retry Mechanism Check.

Detects missing retry logic for network operations.
Validates exponential backoff implementation.
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


class RetryCheck(ValidationCheck):
    """
    Detects missing retry mechanisms for transient failures.

    Network calls can fail temporarily (timeouts, rate limits, etc.).
    Proper retry logic with exponential backoff improves resilience.

    Checks for:
    - HTTP calls without retry decorator/wrapper
    - Database operations without retry
    - Missing exponential backoff
    - Infinite retry loops (dangerous!)

    Severity: MEDIUM (improves reliability but not critical)
    """

    id = "retry"
    name = "Retry Mechanism Check"
    description = "Validates retry logic with exponential backoff for network operations"
    severity = CheckSeverity.MEDIUM
    version = "1.0.0"
    author = "Warden Chaos Team"
    enabled_by_default = True

    # Positive patterns (good retry implementations)
    GOOD_PATTERNS = [
        r"@retry",  # Retry decorator
        r"tenacity",  # Tenacity library
        r"backoff",  # Backoff library
        r"retrying",  # Retrying library
        r"exponential.*backoff",  # Exponential backoff
        r"time\.sleep.*\*.*2",  # Exponential sleep pattern
    ]

    # Dangerous patterns (infinite retries)
    DANGEROUS_PATTERNS = [
        (
            r"while\s+True:.*(?:requests|httpx|fetch)",
            "Infinite retry loop detected (while True with network call)",
        ),
        (
            r"for.*in.*range\(9999",
            "Excessive retry attempts (should have max retry limit)",
        ),
    ]

    async def execute(self, code_file: CodeFile) -> CheckResult:
        """Execute retry mechanism check."""
        findings: List[CheckFinding] = []

        # Check for dangerous infinite retry patterns
        for pattern_str, description in self.DANGEROUS_PATTERNS:
            pattern = re.compile(pattern_str, re.IGNORECASE | re.DOTALL)

            for line_num, line in enumerate(code_file.content.split("\n"), start=1):
                if pattern.search(line):
                    findings.append(
                        CheckFinding(
                            check_id=self.id,
                            check_name=self.name,
                            severity=CheckSeverity.HIGH,  # Dangerous!
                            message=f"Dangerous retry pattern: {description}",
                            location=f"{code_file.path}:{line_num}",
                            code_snippet=line.strip(),
                            suggestion=(
                                "Use controlled retry with max attempts and exponential backoff:\n"
                                "✅ GOOD: @retry(stop=stop_after_attempt(3), wait=wait_exponential())\n"
                                "✅ GOOD: for attempt in range(MAX_RETRIES): ...\n"
                                "❌ BAD: while True: ... (infinite retries)"
                            ),
                            documentation_url="https://github.com/jd/tenacity",
                        )
                    )

        # Check if file has network calls but no retry logic
        has_network_calls = self._has_network_calls(code_file.content)
        has_retry_logic = self._has_retry_logic(code_file.content)

        if has_network_calls and not has_retry_logic:
            findings.append(
                CheckFinding(
                    check_id=self.id,
                    check_name=self.name,
                    severity=CheckSeverity.MEDIUM,
                    message="Network calls detected without retry mechanism",
                    location=f"{code_file.path}:1",
                    code_snippet="(entire file)",
                    suggestion=(
                        "Add retry logic for transient failures:\n\n"
                        "Python (tenacity):\n"
                        "@retry(stop=stop_after_attempt(3),\n"
                        "       wait=wait_exponential(multiplier=1, min=2, max=10))\n"
                        "def call_api():\n"
                        "    return requests.get(url, timeout=30)\n\n"
                        "JavaScript (axios-retry):\n"
                        "axiosRetry(axios, { retries: 3, retryDelay: axiosRetry.exponentialDelay });"
                    ),
                    documentation_url="https://github.com/jd/tenacity",
                )
            )

        return CheckResult(
            check_id=self.id,
            check_name=self.name,
            passed=len(findings) == 0,
            findings=findings,
            metadata={
                "has_network_calls": has_network_calls,
                "has_retry_logic": has_retry_logic,
            },
        )

    def _has_network_calls(self, content: str) -> bool:
        """Check if code has network calls."""
        network_patterns = [
            r"requests\.",
            r"httpx\.",
            r"fetch\(",
            r"axios\.",
            r"http\.client",
            r"urllib\.request",
        ]
        return any(re.search(pattern, content, re.IGNORECASE) for pattern in network_patterns)

    def _has_retry_logic(self, content: str) -> bool:
        """Check if code has retry logic."""
        return any(re.search(pattern, content, re.IGNORECASE) for pattern in self.GOOD_PATTERNS)
