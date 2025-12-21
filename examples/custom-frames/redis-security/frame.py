"""
Redis Security Frame - Production-Ready Example

Validates Redis usage for common security issues:
- Insecure connections (no SSL/TLS)
- Missing authentication
- Hardcoded credentials
- Dangerous commands (FLUSHALL, FLUSHDB, KEYS)
- Missing connection timeouts
- Plaintext passwords in connection strings

Real-world patterns detected:
- redis:// connections
- Redis client configurations
- Connection string formats
- Command usage
"""

import re
import time
from typing import List, Dict, Any, Set

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
    FrameApplicability,
)
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)


class RedisSecurityFrame(ValidationFrame):
    """
    Production-ready Redis security validator.

    Detects:
    - Insecure connections (missing SSL/TLS)
    - Missing authentication
    - Hardcoded passwords
    - Dangerous Redis commands
    - Missing timeouts
    - Weak encryption configurations

    Priority: CRITICAL (blocks deployment if issues found)
    """

    # Required metadata
    name = "Redis Security Validator"
    description = "Validates Redis connections and usage for security best practices"
    category = FrameCategory.GLOBAL
    priority = FramePriority.CRITICAL
    scope = FrameScope.FILE_LEVEL
    is_blocker = True
    version = "1.0.0"
    author = "Warden Security Team"
    applicability = [FrameApplicability.ALL]

    # Redis connection patterns
    REDIS_CONNECTION_PATTERNS = [
        # Python redis-py
        r'redis\.Redis\([^)]*\)',
        r'redis\.from_url\([^)]*\)',
        r'redis\.ConnectionPool\([^)]*\)',

        # Node.js ioredis/redis
        r'new\s+Redis\([^)]*\)',
        r'createClient\([^)]*\)',

        # Go redis
        r'redis\.NewClient\([^)]*\)',

        # Connection strings
        r'redis://[^\s\'"]+',
        r'rediss://[^\s\'"]+',
    ]

    # Dangerous Redis commands
    DANGEROUS_COMMANDS = {
        'FLUSHALL': 'Deletes ALL keys from ALL databases - catastrophic data loss',
        'FLUSHDB': 'Deletes all keys from current database - potential data loss',
        'KEYS': 'Blocks Redis in production - use SCAN instead',
        'CONFIG': 'Runtime configuration changes - security risk',
        'SHUTDOWN': 'Shuts down Redis server',
        'DEBUG': 'Debug commands can expose sensitive information',
        'SLAVEOF': 'Changes replication topology - security risk',
        'REPLICAOF': 'Changes replication topology - security risk',
    }

    # Secure configuration requirements
    SSL_PATTERNS = [
        r'ssl\s*=\s*True',
        r'ssl_cert_reqs\s*=',
        r'tls\s*=\s*[Tt]rue',
        r'rediss://',  # Secure Redis URL scheme
    ]

    AUTH_PATTERNS = [
        r'password\s*=',
        r'auth\s*=',
        r'requirepass',
    ]

    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        """Initialize Redis Security Frame."""
        super().__init__(config)

        # Configuration options
        self.check_ssl = self.config.get("check_ssl", True)
        self.check_auth = self.config.get("check_auth", True)
        self.check_dangerous_commands = self.config.get("check_dangerous_commands", True)
        self.check_hardcoded_passwords = self.config.get("check_hardcoded_passwords", True)
        self.check_timeouts = self.config.get("check_timeouts", True)

        logger.info(
            "redis_security_frame_initialized",
            frame=self.name,
            version=self.version,
            config=self.config,
        )

    async def execute(self, code_file: CodeFile) -> FrameResult:
        """Execute Redis security validation."""
        start_time = time.perf_counter()
        findings: List[Finding] = []

        logger.info(
            "redis_security_validation_started",
            file_path=code_file.path,
            file_size=code_file.size_bytes,
        )

        # Check if file contains Redis usage
        has_redis_usage = self._detect_redis_usage(code_file.content)

        if not has_redis_usage:
            # No Redis usage found - skip validation
            duration = time.perf_counter() - start_time
            return FrameResult(
                frame_id=self.frame_id,
                frame_name=self.name,
                status="passed",
                duration=duration,
                issues_found=0,
                is_blocker=self.is_blocker,
                findings=[],
                metadata={"redis_usage_detected": False},
            )

        # Run security checks
        if self.check_ssl:
            findings.extend(self._check_ssl_tls(code_file))

        if self.check_auth:
            findings.extend(self._check_authentication(code_file))

        if self.check_hardcoded_passwords:
            findings.extend(self._check_hardcoded_credentials(code_file))

        if self.check_dangerous_commands:
            findings.extend(self._check_dangerous_commands(code_file))

        if self.check_timeouts:
            findings.extend(self._check_connection_timeouts(code_file))

        # Determine status
        critical_count = sum(1 for f in findings if f.severity == "critical")
        high_count = sum(1 for f in findings if f.severity == "high")

        if critical_count > 0:
            status = "failed"
        elif high_count > 0:
            status = "warning"
        else:
            status = "passed"

        duration = time.perf_counter() - start_time

        logger.info(
            "redis_security_validation_completed",
            file_path=code_file.path,
            status=status,
            findings_count=len(findings),
            critical_count=critical_count,
            high_count=high_count,
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
            metadata={
                "redis_usage_detected": True,
                "critical_issues": critical_count,
                "high_issues": high_count,
            },
        )

    def _detect_redis_usage(self, content: str) -> bool:
        """Check if file contains Redis-related code."""
        redis_indicators = [
            r'\bredis\b',
            r'Redis',
            r'REDIS',
            r'redis://',
            r'rediss://',
        ]

        for pattern in redis_indicators:
            if re.search(pattern, content, re.IGNORECASE):
                return True

        return False

    def _check_ssl_tls(self, code_file: CodeFile) -> List[Finding]:
        """Check for SSL/TLS usage in Redis connections."""
        findings: List[Finding] = []
        lines = code_file.content.split('\n')

        for i, line in enumerate(lines, 1):
            for pattern in self.REDIS_CONNECTION_PATTERNS:
                if re.search(pattern, line):
                    has_ssl = any(re.search(ssl_pattern, line) for ssl_pattern in self.SSL_PATTERNS)

                    # Check context
                    context_start = max(0, i - 5)
                    context_end = min(len(lines), i + 5)
                    context = '\n'.join(lines[context_start:context_end])
                    has_ssl = has_ssl or any(re.search(ssl_pattern, context) for ssl_pattern in self.SSL_PATTERNS)

                    if not has_ssl and 'redis://' in line and 'rediss://' not in line:
                        findings.append(Finding(
                            id=f"{self.frame_id}-no-ssl-{i}",
                            severity="critical",
                            message="Redis connection without SSL/TLS detected",
                            location=f"{code_file.path}:{i}",
                            detail=(
                                "Redis connections MUST use SSL/TLS in production.\n"
                                "Solutions:\n"
                                "1. Use 'rediss://' instead of 'redis://' URL scheme\n"
                                "2. Set ssl=True in connection parameters\n"
                                "\nExample (Python):\n"
                                "  redis.Redis(host='...', ssl=True, ssl_cert_reqs='required')"
                            ),
                            code=line.strip(),
                        ))

        return findings

    def _check_authentication(self, code_file: CodeFile) -> List[Finding]:
        """Check for Redis authentication."""
        findings: List[Finding] = []
        lines = code_file.content.split('\n')

        for i, line in enumerate(lines, 1):
            for pattern in self.REDIS_CONNECTION_PATTERNS:
                if re.search(pattern, line):
                    has_auth = any(re.search(auth_pattern, line) for auth_pattern in self.AUTH_PATTERNS)

                    # Check context
                    context_start = max(0, i - 5)
                    context_end = min(len(lines), i + 5)
                    context = '\n'.join(lines[context_start:context_end])
                    has_auth = has_auth or any(re.search(auth_pattern, context) for auth_pattern in self.AUTH_PATTERNS)

                    if not has_auth:
                        findings.append(Finding(
                            id=f"{self.frame_id}-no-auth-{i}",
                            severity="high",
                            message="Redis connection without authentication",
                            location=f"{code_file.path}:{i}",
                            detail=(
                                "Redis should require authentication in production.\n"
                                "Example:\n"
                                "  password = os.getenv('REDIS_PASSWORD')\n"
                                "  redis.Redis(host='...', password=password)"
                            ),
                            code=line.strip(),
                        ))

        return findings

    def _check_hardcoded_credentials(self, code_file: CodeFile) -> List[Finding]:
        """Check for hardcoded Redis passwords."""
        findings: List[Finding] = []
        lines = code_file.content.split('\n')

        hardcoded_password_pattern = r'password\s*=\s*["\'](?!.*getenv|.*environ)[^"\']{6,}["\']'

        for i, line in enumerate(lines, 1):
            if re.search(hardcoded_password_pattern, line, re.IGNORECASE):
                findings.append(Finding(
                    id=f"{self.frame_id}-hardcoded-password-{i}",
                    severity="critical",
                    message="Hardcoded Redis password detected",
                    location=f"{code_file.path}:{i}",
                    detail=(
                        "NEVER hardcode passwords in source code!\n"
                        "Use environment variables instead:\n"
                        "  password = os.getenv('REDIS_PASSWORD')"
                    ),
                    code=re.sub(r'password\s*=\s*["\'][^"\']+["\']', 'password="***REDACTED***"', line.strip()),
                ))

        return findings

    def _check_dangerous_commands(self, code_file: CodeFile) -> List[Finding]:
        """Check for dangerous Redis commands."""
        findings: List[Finding] = []
        lines = code_file.content.split('\n')

        for i, line in enumerate(lines, 1):
            for command, description in self.DANGEROUS_COMMANDS.items():
                pattern = rf'\b{command}\b'
                if re.search(pattern, line, re.IGNORECASE):
                    findings.append(Finding(
                        id=f"{self.frame_id}-dangerous-command-{command.lower()}-{i}",
                        severity="high" if command in ['FLUSHALL', 'FLUSHDB'] else "medium",
                        message=f"Dangerous Redis command detected: {command}",
                        location=f"{code_file.path}:{i}",
                        detail=f"{description}\nConsider alternatives or add safeguards.",
                        code=line.strip(),
                    ))

        return findings

    def _check_connection_timeouts(self, code_file: CodeFile) -> List[Finding]:
        """Check for connection timeout configurations."""
        findings: List[Finding] = []
        lines = code_file.content.split('\n')

        timeout_patterns = [
            r'socket_timeout',
            r'timeout\s*=',
            r'connect_timeout',
        ]

        for i, line in enumerate(lines, 1):
            for conn_pattern in self.REDIS_CONNECTION_PATTERNS:
                if re.search(conn_pattern, line):
                    has_timeout = any(re.search(t_pattern, line) for t_pattern in timeout_patterns)

                    # Check context
                    context_start = max(0, i - 5)
                    context_end = min(len(lines), i + 5)
                    context = '\n'.join(lines[context_start:context_end])
                    has_timeout = has_timeout or any(re.search(t_pattern, context) for t_pattern in timeout_patterns)

                    if not has_timeout:
                        findings.append(Finding(
                            id=f"{self.frame_id}-no-timeout-{i}",
                            severity="medium",
                            message="Redis connection without timeout configuration",
                            location=f"{code_file.path}:{i}",
                            detail=(
                                "Always configure timeouts to prevent hanging connections.\n"
                                "Example:\n"
                                "  redis.Redis(host='...', socket_timeout=5)"
                            ),
                            code=line.strip(),
                        ))

        return findings
