"""
Security Frame - Critical security validation.

Built-in checks:
- SQL Injection detection
- XSS (Cross-Site Scripting) detection
- Secrets/credentials detection
- Hardcoded passwords detection

Priority: CRITICAL (blocker)
"""

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
    FrameApplicability,
)
from warden.validation.domain.check import CheckRegistry, CheckResult
from warden.validation.infrastructure.check_loader import CheckLoader
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)


class SecurityFrame(ValidationFrame):
    """
    Security validation frame - Critical security checks.

    This frame detects common security vulnerabilities:
    - SQL injection
    - XSS (Cross-Site Scripting)
    - Hardcoded secrets/credentials
    - Insecure patterns

    Priority: CRITICAL (blocks PR on failure)
    Applicability: All languages
    """

    # Required metadata
    name = "Security Analysis"
    description = "Detects SQL injection, XSS, secrets, and other security vulnerabilities"
    category = FrameCategory.GLOBAL
    priority = FramePriority.CRITICAL
    scope = FrameScope.FILE_LEVEL
    is_blocker = True  # Block PR if critical security issues found
    version = "1.0.0"
    author = "Warden Team"
    applicability = [FrameApplicability.ALL]  # Applies to all languages

    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        """
        Initialize SecurityFrame with checks.

        Args:
            config: Frame configuration
        """
        super().__init__(config)

        # Check registry
        self.checks = CheckRegistry()

        # Register built-in checks
        self._register_builtin_checks()

        # Discover and register community checks
        self._discover_community_checks()

    def _register_builtin_checks(self) -> None:
        """Register built-in security checks."""
        from warden.validation.frames.security._internal.sql_injection_check import SQLInjectionCheck
        from warden.validation.frames.security._internal.xss_check import XSSCheck
        from warden.validation.frames.security._internal.secrets_check import SecretsCheck
        from warden.validation.frames.security._internal.hardcoded_password_check import (
            HardcodedPasswordCheck,
        )

        # Register all built-in checks
        self.checks.register(SQLInjectionCheck(self.config.get("sql_injection", {})))
        self.checks.register(XSSCheck(self.config.get("xss", {})))
        self.checks.register(SecretsCheck(self.config.get("secrets", {})))
        self.checks.register(
            HardcodedPasswordCheck(self.config.get("hardcoded_password", {}))
        )

        logger.info(
            "builtin_checks_registered",
            frame=self.name,
            count=len(self.checks),
        )

    def _discover_community_checks(self) -> None:
        """Discover and register external checks."""
        loader = CheckLoader(frame_id=self.frame_id)
        external_checks = loader.discover_all()

        for check_class in external_checks:
            try:
                # Get check-specific config from frame config
                check_config = self.config.get("checks", {}).get(
                    check_class.id, {}  # type: ignore[attr-defined]
                )
                check_instance = check_class(config=check_config)
                self.checks.register(check_instance)

                logger.info(
                    "community_check_registered",
                    frame=self.name,
                    check=check_instance.name,
                )
            except Exception as e:
                logger.error(
                    "community_check_registration_failed",
                    frame=self.name,
                    check=check_class.__name__,
                    error=str(e),
                )

    async def execute(self, code_file: CodeFile) -> FrameResult:
        """
        Execute all security checks on code file.

        Args:
            code_file: Code file to validate

        Returns:
            FrameResult with aggregated findings from all checks
        """
        start_time = time.perf_counter()

        logger.info(
            "security_frame_started",
            file_path=code_file.path,
            language=code_file.language,
            enabled_checks=len(self.checks.get_enabled(self.config)),
        )

        # Get enabled checks
        enabled_checks = self.checks.get_enabled(self.config)

        # Execute all enabled checks
        check_results: List[CheckResult] = []
        for check in enabled_checks:
            try:
                logger.debug(
                    "check_executing",
                    frame=self.name,
                    check=check.name,
                    file_path=code_file.path,
                )

                result = await check.execute(code_file)
                check_results.append(result)

                logger.debug(
                    "check_completed",
                    frame=self.name,
                    check=check.name,
                    passed=result.passed,
                    findings_count=len(result.findings),
                )

            except Exception as e:
                logger.error(
                    "check_execution_failed",
                    frame=self.name,
                    check=check.name,
                    error=str(e),
                )
                # Continue with other checks even if one fails

        # Aggregate findings from all checks
        all_findings = self._aggregate_findings(check_results)

        # Determine frame status
        status = self._determine_status(all_findings)

        # Calculate duration
        duration = time.perf_counter() - start_time

        logger.info(
            "security_frame_completed",
            file_path=code_file.path,
            status=status,
            total_findings=len(all_findings),
            duration=f"{duration:.2f}s",
        )

        return FrameResult(
            frame_id=self.frame_id,
            frame_name=self.name,
            status=status,
            duration=duration,
            issues_found=len(all_findings),
            is_blocker=self.is_blocker and status == "failed",
            findings=all_findings,
            metadata={
                "checks_executed": len(check_results),
                "checks_passed": sum(1 for r in check_results if r.passed),
                "checks_failed": sum(1 for r in check_results if not r.passed),
                "check_results": [r.to_json() for r in check_results],
            },
        )

    def _aggregate_findings(self, check_results: List[CheckResult]) -> List[Finding]:
        """
        Aggregate findings from all check results.

        Args:
            check_results: Results from all executed checks

        Returns:
            List of Finding objects
        """
        findings: List[Finding] = []

        for check_result in check_results:
            for check_finding in check_result.findings:
                # Convert CheckFinding to Frame-level Finding
                finding = Finding(
                    id=f"{self.frame_id}-{check_finding.check_id}-{len(findings)}",
                    severity=check_finding.severity.value,
                    message=f"[{check_finding.check_name}] {check_finding.message}",
                    location=check_finding.location,
                    detail=check_finding.suggestion,
                    code=check_finding.code_snippet,
                )
                findings.append(finding)

        return findings

    def _determine_status(self, findings: List[Finding]) -> str:
        """
        Determine frame status based on findings.

        Args:
            findings: All findings from checks

        Returns:
            Status: 'passed', 'warning', or 'failed'
        """
        if not findings:
            return "passed"

        # Count critical and high severity findings
        critical_count = sum(1 for f in findings if f.severity == "critical")
        high_count = sum(1 for f in findings if f.severity == "high")

        if critical_count > 0:
            return "failed"  # Critical issues = blocker
        elif high_count > 0:
            return "warning"  # High severity = warning
        else:
            return "passed"  # Only medium/low = passed

    def register_check(self, check: "ValidationCheck") -> None:  # type: ignore[name-defined]
        """
        Programmatically register a custom check.

        Args:
            check: ValidationCheck instance to register

        Example:
            >>> from my_checks import MyCustomCheck
            >>> security_frame = SecurityFrame()
            >>> security_frame.register_check(MyCustomCheck())
        """
        self.checks.register(check)
        logger.info(
            "check_registered_programmatically",
            frame=self.name,
            check=check.name,
        )
