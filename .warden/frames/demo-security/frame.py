"""
Demo Security Frame - Shows auto-config generation in action.

This frame demonstrates:
- Config auto-generation from frame.yaml
- Config merge strategy (defaults + user overrides)
- Full validation workflow
"""

import re
import time
from typing import List, Dict, Any

from warden.validation.domain.frame import (
    ValidationFrame,
    FrameResult,
    Finding,
    CodeFile,
)
from warden.validation.domain.enums import (
    FrameCategory,
    FramePriority,
    FrameScope,
)
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)


class DemoSecurityFrame(ValidationFrame):
    """
    Demo Security Validator - Auto-Config Example.

    Detects:
    - Hardcoded passwords
    - SQL injection patterns

    Config is auto-generated from frame.yaml!
    """

    # Required metadata
    name = "Demo Security Validator"
    description = "Demo frame showing config auto-generation"
    category = FrameCategory.GLOBAL
    priority = FramePriority.HIGH
    scope = FrameScope.FILE_LEVEL
    is_blocker = False
    version = "1.0.0"
    author = "Warden Team"

    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        """Initialize the frame with auto-generated config."""
        super().__init__(config)

        # Config auto-generated from frame.yaml!
        self.check_passwords = self.config.get("check_hardcoded_passwords", True)
        self.check_sql = self.config.get("check_sql_injection", True)
        self.password_patterns = self.config.get("password_patterns", ["password", "passwd", "pwd"])
        self.severity_level = self.config.get("severity_level", "high")

        logger.info(
            "demo_frame_initialized",
            frame=self.name,
            version=self.version,
            config=self.config,
            check_passwords=self.check_passwords,
            check_sql=self.check_sql,
        )

    async def execute(self, code_file: CodeFile) -> FrameResult:
        """Execute demo validation."""
        start_time = time.perf_counter()
        findings: List[Finding] = []

        logger.info(
            "demo_validation_started",
            file_path=code_file.path,
            file_size=code_file.size_bytes,
        )

        lines = code_file.content.split('\n')

        # Check 1: Hardcoded passwords (if enabled)
        if self.check_passwords:
            findings.extend(self._check_hardcoded_passwords(lines, code_file.path))

        # Check 2: SQL injection (if enabled)
        if self.check_sql:
            findings.extend(self._check_sql_injection(lines, code_file.path))

        # Determine status
        status = "failed" if findings else "passed"
        duration = time.perf_counter() - start_time

        logger.info(
            "demo_validation_completed",
            file_path=code_file.path,
            status=status,
            findings_count=len(findings),
            duration=f"{duration:.2f}s",
        )

        return FrameResult(
            frame_id=self.frame_id,
            frame_name=self.name,
            status=status,
            duration=duration,
            issues_found=len(findings),
            is_blocker=self.is_blocker and status == "failed",
            findings=findings,
        )

    def _check_hardcoded_passwords(self, lines: List[str], file_path: str) -> List[Finding]:
        """Check for hardcoded password patterns."""
        findings = []

        for i, line in enumerate(lines, 1):
            # Check for password patterns
            for pattern in self.password_patterns:
                if re.search(rf'{pattern}\s*=\s*["\']', line, re.IGNORECASE):
                    findings.append(Finding(
                        id=f"{self.frame_id}-password-{i}",
                        severity=self.severity_level,
                        message=f"Potential hardcoded password detected",
                        location=f"{file_path}:{i}",
                        detail=(
                            f"Found password pattern: '{pattern}'\n"
                            "\n"
                            "Why this is a problem:\n"
                            "- Hardcoded credentials are a security risk\n"
                            "- Credentials should be in environment variables\n"
                            "\n"
                            "Fix:\n"
                            "  password = os.getenv('PASSWORD')\n"
                        ),
                        code=line.strip(),
                    ))

        return findings

    def _check_sql_injection(self, lines: List[str], file_path: str) -> List[Finding]:
        """Check for SQL injection patterns."""
        findings = []

        sql_pattern = re.compile(r'(SELECT|INSERT|UPDATE|DELETE).*f["\']|\.format\(', re.IGNORECASE)

        for i, line in enumerate(lines, 1):
            if sql_pattern.search(line):
                findings.append(Finding(
                    id=f"{self.frame_id}-sql-{i}",
                    severity=self.severity_level,
                    message="Potential SQL injection vulnerability",
                    location=f"{file_path}:{i}",
                    detail=(
                        "SQL query uses string formatting or f-strings\n"
                        "\n"
                        "Why this is a problem:\n"
                        "- String interpolation can lead to SQL injection\n"
                        "- User input can manipulate the query\n"
                        "\n"
                        "Fix:\n"
                        "  query = 'SELECT * FROM users WHERE id = ?'\n"
                        "  cursor.execute(query, (user_id,))\n"
                    ),
                    code=line.strip(),
                ))

        return findings
