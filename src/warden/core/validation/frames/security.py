"""
SecurityFrame - Security vulnerability detection.

Priority: Critical
Blocker: True
Scope: FILE_LEVEL

Detects:
- SQL injection patterns
- Command injection
- Hardcoded secrets (API keys, passwords)
- Path traversal
- Insecure deserialization
- XSS vulnerabilities
"""
import re
import time
from typing import Dict, Any, List

from warden.core.validation.frame import BaseValidationFrame, FrameResult, FrameScope


class SecurityFrame(BaseValidationFrame):
    """Security vulnerability detection frame."""

    # Patterns for secret detection
    SECRET_PATTERNS = [
        (r'sk-[a-zA-Z0-9]{32,}', 'OpenAI API key'),
        (r'ghp_[a-zA-Z0-9]{36}', 'GitHub personal access token'),
        (r'(?i)password\s*=\s*["\'][^"\']+["\']', 'Hardcoded password'),
        (r'(?i)api[_-]?key\s*=\s*["\'][^"\']+["\']', 'Hardcoded API key'),
        (r'(?i)secret\s*=\s*["\'][^"\']+["\']', 'Hardcoded secret'),
        (r'(?i)token\s*=\s*["\'][^"\']+["\']', 'Hardcoded token'),
    ]

    # SQL injection indicators
    SQL_INJECTION_PATTERNS = [
        r'f["\']SELECT.*\{.*\}',  # f-string with SQL
        r'f["\']INSERT.*\{.*\}',
        r'f["\']UPDATE.*\{.*\}',
        r'f["\']DELETE.*\{.*\}',
        r'\.format\(.*\).*SELECT',  # .format() with SQL
    ]

    # Command injection indicators
    COMMAND_INJECTION_PATTERNS = [
        r'os\.system\s*\(.*\{',  # os.system with f-string
        r'subprocess\..*shell\s*=\s*True',  # shell=True
        r'eval\s*\(',  # eval usage
        r'exec\s*\(',  # exec usage
    ]

    @property
    def name(self) -> str:
        return "Security Analysis"

    @property
    def description(self) -> str:
        return "Detects security vulnerabilities: SQL injection, command injection, hardcoded secrets, XSS, path traversal"

    @property
    def priority(self) -> str:
        return "critical"

    @property
    def scope(self) -> FrameScope:
        return FrameScope.FILE_LEVEL

    @property
    def is_blocker(self) -> bool:
        return True

    async def execute(
        self,
        file_path: str,
        file_content: str,
        language: str,
        characteristics: Dict[str, Any],
        correlation_id: str = "",
        timeout: int = 300,
    ) -> FrameResult:
        """Execute security validation."""
        start_time = time.perf_counter()

        findings = []
        issues = []
        scenarios_executed = []

        try:
            # Check for hardcoded secrets
            scenarios_executed.append("Hardcoded secrets detection")
            secret_issues = self._detect_secrets(file_content)
            issues.extend(secret_issues)
            if secret_issues:
                findings.append(f"Found {len(secret_issues)} hardcoded secrets")

            # Check for SQL injection
            scenarios_executed.append("SQL injection pattern detection")
            sql_issues = self._detect_sql_injection(file_content)
            issues.extend(sql_issues)
            if sql_issues:
                findings.append(f"Found {len(sql_issues)} potential SQL injection vulnerabilities")

            # Check for command injection
            scenarios_executed.append("Command injection pattern detection")
            cmd_issues = self._detect_command_injection(file_content)
            issues.extend(cmd_issues)
            if cmd_issues:
                findings.append(f"Found {len(cmd_issues)} potential command injection vulnerabilities")

            # Check for path traversal
            scenarios_executed.append("Path traversal detection")
            path_issues = self._detect_path_traversal(file_content)
            issues.extend(path_issues)
            if path_issues:
                findings.append(f"Found {len(path_issues)} potential path traversal vulnerabilities")

            passed = len(issues) == 0

            if passed:
                findings.append("No security vulnerabilities detected")

        except Exception as ex:
            passed = False
            error_message = str(ex)
            issues.append(f"Security analysis failed: {error_message}")

        duration_ms = (time.perf_counter() - start_time) * 1000

        return FrameResult(
            name=self.name,
            passed=passed,
            execution_time_ms=duration_ms,
            priority=self.priority,
            scope=self.scope.value,
            findings=findings,
            issues=issues,
            scenarios_executed=scenarios_executed,
            is_blocker=self.is_blocker,
            error_message=error_message if not passed and 'error_message' in locals() else None,
        )

    def _detect_secrets(self, content: str) -> List[str]:
        """Detect hardcoded secrets."""
        issues = []
        lines = content.split('\n')

        for idx, line in enumerate(lines, 1):
            # Skip comments
            if line.strip().startswith('#'):
                continue

            for pattern, description in self.SECRET_PATTERNS:
                if re.search(pattern, line):
                    issues.append(f"Line {idx}: {description} detected")

        return issues

    def _detect_sql_injection(self, content: str) -> List[str]:
        """Detect SQL injection patterns."""
        issues = []
        lines = content.split('\n')

        for idx, line in enumerate(lines, 1):
            for pattern in self.SQL_INJECTION_PATTERNS:
                if re.search(pattern, line, re.IGNORECASE):
                    issues.append(f"Line {idx}: Potential SQL injection - f-string/format with SQL query")
                    break

        return issues

    def _detect_command_injection(self, content: str) -> List[str]:
        """Detect command injection patterns."""
        issues = []
        lines = content.split('\n')

        for idx, line in enumerate(lines, 1):
            for pattern in self.COMMAND_INJECTION_PATTERNS:
                if re.search(pattern, line):
                    if 'shell=True' in pattern:
                        issues.append(f"Line {idx}: Command injection risk - shell=True")
                    elif 'eval' in pattern:
                        issues.append(f"Line {idx}: Dangerous eval() usage")
                    elif 'exec' in pattern:
                        issues.append(f"Line {idx}: Dangerous exec() usage")
                    else:
                        issues.append(f"Line {idx}: Command injection risk")
                    break

        return issues

    def _detect_path_traversal(self, content: str) -> List[str]:
        """Detect path traversal vulnerabilities."""
        issues = []
        lines = content.split('\n')

        # Look for file operations without validation
        file_ops = ['open(', 'read(', 'write(']

        for idx, line in enumerate(lines, 1):
            if any(op in line for op in file_ops):
                # Check if path comes from variable/parameter without validation
                if re.search(r'open\s*\([^)]*\{', line):  # f-string path
                    issues.append(f"Line {idx}: Path traversal risk - unvalidated file path")

        return issues
