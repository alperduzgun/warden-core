"""
Environment Security Validator - Production-ready custom frame.

This frame detects:
- Hardcoded credentials (API keys, tokens, secrets)
- Missing environment variable validation
- Insecure default values
- Environment variable best practices violations

Author: Warden Security Team
Version: 1.0.0
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
)
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)


class EnvironmentSecurityFrame(ValidationFrame):
    """
    Environment Security Validator.

    Validates:
    1. No hardcoded credentials
    2. Environment variables are validated before use
    3. No insecure default values
    4. Best practices for environment configuration

    Priority: CRITICAL (blocks deployment on issues)
    """

    # Required metadata
    name = "Environment Security Validator"
    description = "Detects environment variable security issues and best practices violations"
    category = FrameCategory.GLOBAL
    priority = FramePriority.CRITICAL
    scope = FrameScope.FILE_LEVEL
    is_blocker = True
    version = "1.0.0"
    author = "Warden Security Team"

    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        """Initialize with auto-generated config from frame.yaml."""
        super().__init__(config)

        # Load config (auto-generated from frame.yaml!)
        self.check_hardcoded = self.config.get("check_hardcoded_credentials", True)
        self.check_validation = self.config.get("check_missing_env_validation", True)
        self.check_defaults = self.config.get("check_insecure_defaults", True)
        self.sensitive_patterns = self.config.get("sensitive_patterns", [
            "API_KEY", "SECRET", "TOKEN", "PASSWORD", "PRIVATE_KEY"
        ])
        self.allowed_defaults = self.config.get("allowed_default_values", [
            "localhost", "127.0.0.1", "development"
        ])
        self.severity = self.config.get("severity_level", "critical")

        logger.info(
            "env_security_frame_initialized",
            frame=self.name,
            version=self.version,
            config=self.config,
            check_hardcoded=self.check_hardcoded,
            check_validation=self.check_validation,
        )

    async def execute(self, code_file: CodeFile) -> FrameResult:
        """Execute environment security validation."""
        start_time = time.perf_counter()
        findings: List[Finding] = []

        logger.info(
            "env_security_validation_started",
            file_path=code_file.path,
            language=code_file.language,
        )

        lines = code_file.content.split('\n')

        # Check 1: Hardcoded credentials
        if self.check_hardcoded:
            findings.extend(self._check_hardcoded_credentials(lines, code_file.path))

        # Check 2: Missing validation
        if self.check_validation:
            findings.extend(self._check_missing_validation(lines, code_file.path))

        # Check 3: Insecure defaults
        if self.check_defaults:
            findings.extend(self._check_insecure_defaults(lines, code_file.path))

        # Determine status
        status = "failed" if findings else "passed"
        duration = time.perf_counter() - start_time

        logger.info(
            "env_security_validation_completed",
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

    def _check_hardcoded_credentials(self, lines: List[str], file_path: str) -> List[Finding]:
        """Detect hardcoded API keys, tokens, and secrets."""
        findings = []

        # Patterns for hardcoded credentials
        patterns = [
            (r'(api[_-]?key|apikey)\s*=\s*["\']([a-zA-Z0-9_\-]{20,})["\']', 'API Key'),
            (r'(secret|secret[_-]?key)\s*=\s*["\']([a-zA-Z0-9_\-]{20,})["\']', 'Secret'),
            (r'(token|access[_-]?token)\s*=\s*["\']([a-zA-Z0-9_\-]{20,})["\']', 'Access Token'),
            (r'(password|passwd)\s*=\s*["\'](.{8,})["\']', 'Password'),
            (r'(private[_-]?key|privatekey)\s*=\s*["\'](.+)["\']', 'Private Key'),
            (r'(aws[_-]?access[_-]?key|AWS_ACCESS_KEY_ID)\s*=\s*["\']([A-Z0-9]{20})["\']', 'AWS Access Key'),
        ]

        for i, line in enumerate(lines, 1):
            # Skip comments
            if line.strip().startswith('#') or line.strip().startswith('//'):
                continue

            for pattern, cred_type in patterns:
                match = re.search(pattern, line, re.IGNORECASE)
                if match:
                    findings.append(Finding(
                        id=f"{self.frame_id}-hardcoded-{i}",
                        severity=self.severity,
                        message=f"Hardcoded {cred_type} detected",
                        location=f"{file_path}:{i}",
                        detail=(
                            f"Found hardcoded {cred_type} in source code\n"
                            "\n"
                            "⚠️  SECURITY RISK:\n"
                            "- Credentials in source code can be exposed in version control\n"
                            "- Anyone with repo access can see the credentials\n"
                            "- Credentials cannot be rotated without code changes\n"
                            "\n"
                            "✅ Fix:\n"
                            "  # Use environment variables\n"
                            "  import os\n"
                            f"  {cred_type.lower().replace(' ', '_')} = os.getenv('{cred_type.upper().replace(' ', '_')}')\n"
                            "  if not {0}:\n"
                            f"      raise ValueError('{cred_type} not configured')\n"
                        ),
                        code=line.strip(),
                    ))

        return findings

    def _check_missing_validation(self, lines: List[str], file_path: str) -> List[Finding]:
        """Check if environment variables are validated before use."""
        findings = []

        # Find lines using os.getenv or process.env
        env_usage_pattern = r'(os\.getenv|process\.env\[|ENV\[)["\']([A-Z_]+)["\']'

        used_vars: Set[str] = set()
        validated_vars: Set[str] = set()

        for i, line in enumerate(lines, 1):
            # Find environment variable usage
            matches = re.findall(env_usage_pattern, line)
            for _, var_name in matches:
                used_vars.add((var_name, i))

            # Find validation (if not ... raise)
            if re.search(r'if\s+not\s+\w+.*raise|assert\s+\w+', line):
                # Try to extract validated variable from previous lines
                if i > 1:
                    prev_line = lines[i - 2] if i > 1 else ""
                    var_match = re.search(r'(\w+)\s*=\s*os\.getenv', prev_line)
                    if var_match:
                        validated_vars.add(var_match.group(1))

        # Check for unvalidated variables
        for var_name, line_num in used_vars:
            # Skip if it has a default value (considered safe)
            line = lines[line_num - 1]
            if re.search(rf'os\.getenv\(["\']={var_name}["\'],\s*.+\)', line):
                continue

            # Check if variable name suggests it's sensitive
            is_sensitive = any(pattern in var_name for pattern in self.sensitive_patterns)

            if is_sensitive:
                findings.append(Finding(
                    id=f"{self.frame_id}-no-validation-{line_num}",
                    severity="high",
                    message=f"Sensitive environment variable '{var_name}' not validated",
                    location=f"{file_path}:{line_num}",
                    detail=(
                        f"Environment variable '{var_name}' appears to be sensitive but lacks validation\n"
                        "\n"
                        "⚠️  POTENTIAL ISSUE:\n"
                        "- Missing or empty env vars can cause runtime errors\n"
                        "- Silent failures in production are hard to debug\n"
                        "- Security configs should fail fast if not set\n"
                        "\n"
                        "✅ Fix:\n"
                        f"  {var_name.lower()} = os.getenv('{var_name}')\n"
                        f"  if not {var_name.lower()}:\n"
                        f"      raise ValueError('{var_name} environment variable is required')\n"
                    ),
                    code=line.strip(),
                ))

        return findings

    def _check_insecure_defaults(self, lines: List[str], file_path: str) -> List[Finding]:
        """Detect insecure default values for environment variables."""
        findings = []

        # Pattern: os.getenv('VAR', 'default_value')
        default_pattern = r'os\.getenv\(["\']([A-Z_]+)["\']\s*,\s*["\']([^"\']+)["\']\)'

        for i, line in enumerate(lines, 1):
            matches = re.findall(default_pattern, line)

            for var_name, default_value in matches:
                # Check if variable is sensitive
                is_sensitive = any(pattern in var_name for pattern in self.sensitive_patterns)

                # Check if default is insecure
                is_safe_default = default_value in self.allowed_defaults

                if is_sensitive and not is_safe_default:
                    findings.append(Finding(
                        id=f"{self.frame_id}-insecure-default-{i}",
                        severity="high",
                        message=f"Insecure default value for sensitive variable '{var_name}'",
                        location=f"{file_path}:{i}",
                        detail=(
                            f"Sensitive variable '{var_name}' has a default value: '{default_value}'\n"
                            "\n"
                            "⚠️  SECURITY RISK:\n"
                            "- Sensitive configs should not have defaults\n"
                            "- Defaults can leak into production accidentally\n"
                            "- Forces explicit configuration in all environments\n"
                            "\n"
                            "✅ Fix:\n"
                            f"  {var_name.lower()} = os.getenv('{var_name}')\n"
                            f"  if not {var_name.lower()}:\n"
                            f"      raise ValueError('{var_name} must be explicitly set')\n"
                        ),
                        code=line.strip(),
                    ))

        return findings
