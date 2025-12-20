"""
Chaos Engineering Frame - Resilience validation.

Built-in checks:
- Network failure handling
- Timeout configuration
- Retry mechanism with backoff
- Circuit breaker patterns
- Graceful degradation
- Error recovery

Priority: HIGH
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


class ChaosFrame(ValidationFrame):
    """
    Chaos Engineering validation frame - Resilience checks.

    This frame validates code resilience against failures:
    - Network failures (timeouts, connection errors)
    - Retry mechanisms (with exponential backoff)
    - Circuit breakers (prevent cascading failures)
    - Graceful degradation (fallback behaviors)
    - Resource exhaustion handling

    Priority: HIGH (important for production resilience)
    Applicability: Code with external dependencies (APIs, databases, queues)
    """

    # Required metadata
    name = "Chaos Engineering"
    description = "Validates resilience against network failures, timeouts, and cascading failures"
    category = FrameCategory.GLOBAL
    priority = FramePriority.HIGH
    scope = FrameScope.FILE_LEVEL
    is_blocker = False  # Warning only, not blocking
    version = "1.0.0"
    author = "Warden Team"
    applicability = [FrameApplicability.ALL]

    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        """
        Initialize ChaosFrame with checks.

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
        """Register built-in chaos engineering checks."""
        from warden.validation.frames.chaos._internal.timeout_check import TimeoutCheck
        from warden.validation.frames.chaos._internal.retry_check import RetryCheck
        from warden.validation.frames.chaos._internal.circuit_breaker_check import CircuitBreakerCheck
        from warden.validation.frames.chaos._internal.error_handling_check import ErrorHandlingCheck

        # Register all built-in checks
        self.checks.register(TimeoutCheck(self.config.get("timeout", {})))
        self.checks.register(RetryCheck(self.config.get("retry", {})))
        self.checks.register(CircuitBreakerCheck(self.config.get("circuit_breaker", {})))
        self.checks.register(ErrorHandlingCheck(self.config.get("error_handling", {})))

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
        Execute all chaos engineering checks on code file.

        Args:
            code_file: Code file to validate

        Returns:
            FrameResult with aggregated findings from all checks
        """
        start_time = time.perf_counter()

        logger.info(
            "chaos_frame_started",
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

        # Aggregate findings from all checks
        all_findings = self._aggregate_findings(check_results)

        # Determine frame status
        status = self._determine_status(all_findings)

        # Calculate duration
        duration = time.perf_counter() - start_time

        logger.info(
            "chaos_frame_completed",
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
            is_blocker=self.is_blocker,
            findings=all_findings,
            metadata={
                "checks_executed": len(check_results),
                "checks_passed": sum(1 for r in check_results if r.passed),
                "checks_failed": sum(1 for r in check_results if not r.passed),
                "check_results": [r.to_json() for r in check_results],
            },
        )

    def _aggregate_findings(self, check_results: List[CheckResult]) -> List[Finding]:
        """Aggregate findings from all check results."""
        findings: List[Finding] = []

        for check_result in check_results:
            for check_finding in check_result.findings:
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
        """Determine frame status based on findings."""
        if not findings:
            return "passed"

        high_count = sum(1 for f in findings if f.severity == "high")
        medium_count = sum(1 for f in findings if f.severity == "medium")

        if high_count > 0:
            return "warning"  # High severity = warning (not blocker)
        elif medium_count > 0:
            return "warning"
        else:
            return "passed"

    def register_check(self, check: "ValidationCheck") -> None:  # type: ignore[name-defined]
        """Programmatically register a custom check."""
        self.checks.register(check)
        logger.info(
            "check_registered_programmatically",
            frame=self.name,
            check=check.name,
        )
