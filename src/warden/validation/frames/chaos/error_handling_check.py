"""
Error Handling Check.

Detects inadequate error handling for:
- Network operations without try/except
- Missing error logging
- Bare except clauses
- Missing graceful degradation
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


class ErrorHandlingCheck(ValidationCheck):
    """
    Detects missing or inadequate error handling.

    Network operations can fail in various ways (timeouts, connection errors,
    rate limits, etc.). Proper error handling with logging and graceful
    degradation prevents cascading failures.

    Checks for:
    - Network calls without try/except blocks
    - Bare except clauses (catching everything)
    - Missing error logging
    - Missing fallback/degradation patterns

    Severity: HIGH (can cause production incidents)
    """

    id = "error-handling"
    name = "Error Handling Check"
    description = "Validates proper error handling for network operations and external dependencies"
    severity = CheckSeverity.HIGH
    version = "1.0.0"
    author = "Warden Chaos Team"
    enabled_by_default = True

    # Patterns for risky error handling
    RISKY_PATTERNS = [
        # Bare except (catches everything, including KeyboardInterrupt!)
        (
            r"except\s*:",
            "Bare except clause catches all exceptions (dangerous!)",
            "except SpecificException as e:",
        ),
        # Generic Exception catch without logging
        (
            r"except\s+Exception(?!\s+as\s+\w+\s*:.*(?:log|logger|print))",
            "Catching Exception without logging the error",
            "except Exception as e:\n    logger.error(f'Error: {e}')",
        ),
        # pass in except block (silent failure)
        (
            r"except.*:\s*pass",
            "Silent exception handling (pass in except block)",
            "except Exception as e:\n    logger.error(f'Error: {e}')\n    return fallback_value",
        ),
    ]

    # Network operation patterns that need error handling
    NETWORK_PATTERNS = [
        r"requests\.",
        r"httpx\.",
        r"aiohttp\.",
        r"fetch\(",
        r"axios\.",
        r"http\.client",
        r"urllib\.request",
        r"socket\.",
    ]

    async def execute(self, code_file: CodeFile) -> CheckResult:
        """Execute error handling check."""
        findings: List[CheckFinding] = []

        # Check for risky error handling patterns
        for pattern_str, description, suggestion in self.RISKY_PATTERNS:
            pattern = re.compile(pattern_str, re.IGNORECASE | re.DOTALL)

            for line_num, line in enumerate(code_file.content.split("\n"), start=1):
                # Skip comments
                if line.strip().startswith("#") or line.strip().startswith("//"):
                    continue

                match = pattern.search(line)
                if match:
                    findings.append(
                        CheckFinding(
                            check_id=self.id,
                            check_name=self.name,
                            severity=self.severity,
                            message=f"Risky error handling: {description}",
                            location=f"{code_file.path}:{line_num}",
                            code_snippet=line.strip(),
                            suggestion=(
                                f"Use specific exception handling with logging:\n"
                                f"✅ GOOD: {suggestion}\n"
                                f"❌ BAD: {match.group(0)}\n\n"
                                "Best practices:\n"
                                "- Catch specific exceptions (not Exception or bare except)\n"
                                "- Always log errors with context\n"
                                "- Provide fallback values or graceful degradation\n"
                                "- Never use 'pass' in except blocks"
                            ),
                            documentation_url="https://docs.python.org/3/tutorial/errors.html",
                        )
                    )

        # Check if file has network calls without try/except
        has_network_calls = self._has_network_calls(code_file.content)
        has_error_handling = self._has_error_handling(code_file.content)

        if has_network_calls and not has_error_handling:
            findings.append(
                CheckFinding(
                    check_id=self.id,
                    check_name=self.name,
                    severity=CheckSeverity.HIGH,
                    message="Network operations without try/except error handling",
                    location=f"{code_file.path}:1",
                    code_snippet="(entire file)",
                    suggestion=(
                        "Wrap network operations in try/except blocks:\n\n"
                        "Python:\n"
                        "try:\n"
                        "    response = requests.get(url, timeout=30)\n"
                        "    response.raise_for_status()\n"
                        "    return response.json()\n"
                        "except requests.Timeout:\n"
                        "    logger.error('Request timeout', url=url)\n"
                        "    return fallback_data\n"
                        "except requests.ConnectionError as e:\n"
                        "    logger.error('Connection failed', url=url, error=str(e))\n"
                        "    return fallback_data\n"
                        "except requests.HTTPError as e:\n"
                        "    logger.error('HTTP error', status=e.response.status_code)\n"
                        "    raise\n\n"
                        "JavaScript:\n"
                        "try {\n"
                        "    const response = await fetch(url, { signal: AbortSignal.timeout(30000) });\n"
                        "    if (!response.ok) throw new Error(`HTTP ${response.status}`);\n"
                        "    return await response.json();\n"
                        "} catch (error) {\n"
                        "    logger.error('Fetch failed', { url, error: error.message });\n"
                        "    return fallbackData;\n"
                        "}"
                    ),
                    documentation_url="https://requests.readthedocs.io/en/latest/user/quickstart/#errors-and-exceptions",
                )
            )

        return CheckResult(
            check_id=self.id,
            check_name=self.name,
            passed=len(findings) == 0,
            findings=findings,
            metadata={
                "has_network_calls": has_network_calls,
                "has_error_handling": has_error_handling,
                "risky_patterns_checked": len(self.RISKY_PATTERNS),
            },
        )

    def _has_network_calls(self, content: str) -> bool:
        """Check if code has network operations."""
        return any(re.search(pattern, content, re.IGNORECASE) for pattern in self.NETWORK_PATTERNS)

    def _has_error_handling(self, content: str) -> bool:
        """Check if code has try/except blocks."""
        return bool(re.search(r"\btry\s*:", content, re.IGNORECASE))
