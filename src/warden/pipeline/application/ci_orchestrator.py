"""
CI-Aware Pipeline Orchestrator for Warden.

Extends the base orchestrator with CI/CD-specific features:
- Platform detection (GitHub Actions, GitLab CI, Azure Pipelines)
- CI-specific logging and annotations
- Exit code management for blocker issues
- Structured output for CI parsers
"""

import os
import sys
from enum import Enum
from typing import List, Optional, Dict, Any
from pathlib import Path

import structlog

from warden.pipeline.application.orchestrator import PipelineOrchestrator
from warden.pipeline.domain.models import PipelineResult, ValidationPipeline
from warden.issues.domain.enums import IssueSeverity


logger = structlog.get_logger(__name__)


class CIPlatform(Enum):
    """Supported CI/CD platforms."""

    GITHUB_ACTIONS = "github"
    GITLAB_CI = "gitlab"
    AZURE_PIPELINES = "azure"
    JENKINS = "jenkins"
    CIRCLECI = "circleci"
    TRAVIS = "travis"
    UNKNOWN = "unknown"


class CIPipelineOrchestrator(PipelineOrchestrator):
    """
    CI/CD-optimized pipeline orchestrator.

    Detects the CI platform and adapts behavior:
    - GitHub Actions: Generates workflow commands (::error, ::warning)
    - GitLab CI: Structured logging for GitLab CI parser
    - Azure Pipelines: Uses ##vso[] commands
    - Generic: Standard output with exit codes
    """

    def __init__(
        self,
        frames: List = None,
        config: Optional[Any] = None,
        progress_callback: Optional[callable] = None,
        fail_on_critical: bool = True,
        fail_on_high: bool = False,
    ):
        """
        Initialize CI-aware orchestrator.

        Args:
            frames: List of validation frames to execute
            config: Pipeline configuration
            progress_callback: Optional callback for progress updates
            fail_on_critical: Fail build if critical issues found (default: True)
            fail_on_high: Fail build if high severity issues found (default: False)
        """
        # Only initialize parent if frames are provided
        if frames is not None:
            super().__init__(frames, config, progress_callback)
        else:
            # For testing without frames, set minimal attributes
            self.frames = []
            self.config = config
            self.progress_callback = progress_callback

        self.ci_platform = self._detect_ci_platform()
        self.fail_on_critical = fail_on_critical
        self.fail_on_high = fail_on_high
        self.ci_mode = True

        logger.info(
            "ci_orchestrator_initialized",
            platform=self.ci_platform.value,
            fail_on_critical=fail_on_critical,
            fail_on_high=fail_on_high,
        )

    @staticmethod
    def _detect_ci_platform() -> CIPlatform:
        """
        Detect current CI/CD platform from environment variables.

        Returns:
            Detected CI platform enum
        """
        # GitHub Actions
        if os.getenv("GITHUB_ACTIONS") == "true":
            return CIPlatform.GITHUB_ACTIONS

        # GitLab CI
        if os.getenv("GITLAB_CI") == "true":
            return CIPlatform.GITLAB_CI

        # Azure Pipelines
        if os.getenv("TF_BUILD") == "True":
            return CIPlatform.AZURE_PIPELINES

        # Jenkins
        if os.getenv("JENKINS_HOME"):
            return CIPlatform.JENKINS

        # CircleCI
        if os.getenv("CIRCLECI") == "true":
            return CIPlatform.CIRCLECI

        # Travis CI
        if os.getenv("TRAVIS") == "true":
            return CIPlatform.TRAVIS

        return CIPlatform.UNKNOWN

    async def execute(
        self, code_files: List[Any]
    ) -> PipelineResult:
        """
        Execute pipeline with CI-specific enhancements.

        Args:
            code_files: List of code files to analyze

        Returns:
            Pipeline execution result

        Raises:
            SystemExit: If blocker issues found and fail_on_* is True
        """
        logger.info(
            "ci_pipeline_execution_started",
            platform=self.ci_platform.value,
            file_count=len(code_files),
        )

        # Execute base pipeline
        result = await super().execute(code_files)

        # Generate CI-specific outputs
        self._generate_ci_outputs(result)

        # Check for blocker issues and exit if necessary
        self._check_blocker_issues(result)

        logger.info(
            "ci_pipeline_execution_completed",
            platform=self.ci_platform.value,
            status=result.status.value,
            total_issues=len(result.all_issues),
        )

        return result

    def _generate_ci_outputs(self, result: PipelineResult) -> None:
        """
        Generate platform-specific CI outputs.

        Args:
            result: Pipeline execution result
        """
        if self.ci_platform == CIPlatform.GITHUB_ACTIONS:
            self._generate_github_annotations(result)
        elif self.ci_platform == CIPlatform.GITLAB_CI:
            self._generate_gitlab_outputs(result)
        elif self.ci_platform == CIPlatform.AZURE_PIPELINES:
            self._generate_azure_outputs(result)
        else:
            self._generate_generic_outputs(result)

    def _generate_github_annotations(self, result: PipelineResult) -> None:
        """
        Generate GitHub Actions workflow commands.

        Outputs ::error and ::warning annotations for inline code feedback.

        Args:
            result: Pipeline execution result
        """
        logger.debug("generating_github_annotations")

        for issue in result.all_issues:
            # Map severity to GitHub annotation level
            if issue.severity in [IssueSeverity.CRITICAL, IssueSeverity.HIGH]:
                level = "error"
            elif issue.severity == IssueSeverity.MEDIUM:
                level = "warning"
            else:
                level = "notice"

            # Generate annotation
            file_path = getattr(issue, "file_path", "unknown")
            line = getattr(issue, "line", 1)
            message = getattr(issue, "message", "Issue detected")

            annotation = f"::{level} file={file_path},line={line}::{message}"
            print(annotation, flush=True)

        # Summary
        critical_count = sum(
            1 for i in result.all_issues if i.severity == IssueSeverity.CRITICAL
        )
        high_count = sum(
            1 for i in result.all_issues if i.severity == IssueSeverity.HIGH
        )

        if critical_count > 0:
            print(
                f"::error::❌ BLOCKER: {critical_count} critical security issues found!",
                flush=True,
            )
        if high_count > 0:
            print(
                f"::warning::⚠️  {high_count} high severity issues found", flush=True
            )

    def _generate_gitlab_outputs(self, result: PipelineResult) -> None:
        """
        Generate GitLab CI-specific outputs.

        Args:
            result: Pipeline execution result
        """
        logger.debug("generating_gitlab_outputs")

        # GitLab uses structured logging
        for issue in result.all_issues:
            severity_map = {
                IssueSeverity.CRITICAL: "critical",
                IssueSeverity.HIGH: "major",
                IssueSeverity.MEDIUM: "minor",
                IssueSeverity.LOW: "info",
            }

            logger.info(
                "gitlab_issue",
                severity=severity_map.get(issue.severity, "info"),
                file=getattr(issue, "file_path", "unknown"),
                line=getattr(issue, "line", 1),
                message=getattr(issue, "message", "Issue detected"),
            )

    def _generate_azure_outputs(self, result: PipelineResult) -> None:
        """
        Generate Azure Pipelines-specific outputs.

        Uses ##vso[] logging commands.

        Args:
            result: Pipeline execution result
        """
        logger.debug("generating_azure_outputs")

        for issue in result.all_issues:
            # Map severity to Azure task result
            if issue.severity in [IssueSeverity.CRITICAL, IssueSeverity.HIGH]:
                issue_type = "error"
            elif issue.severity == IssueSeverity.MEDIUM:
                issue_type = "warning"
            else:
                continue  # Skip low severity for Azure

            file_path = getattr(issue, "file_path", "unknown")
            line = getattr(issue, "line", 1)
            message = getattr(issue, "message", "Issue detected")

            # Azure Pipelines logging command
            azure_cmd = f"##vso[task.logissue type={issue_type};sourcepath={file_path};linenumber={line}]{message}"
            print(azure_cmd, flush=True)

        # Set pipeline variables
        critical_count = sum(
            1 for i in result.all_issues if i.severity == IssueSeverity.CRITICAL
        )
        print(
            f"##vso[task.setvariable variable=wardenCriticalIssues]{critical_count}",
            flush=True,
        )

    def _generate_generic_outputs(self, result: PipelineResult) -> None:
        """
        Generate generic CI outputs (for unknown platforms).

        Args:
            result: Pipeline execution result
        """
        logger.debug("generating_generic_outputs")

        # Simple structured output
        critical_count = sum(
            1 for i in result.all_issues if i.severity == IssueSeverity.CRITICAL
        )
        high_count = sum(
            1 for i in result.all_issues if i.severity == IssueSeverity.HIGH
        )

        if critical_count > 0:
            print(f"❌ CRITICAL ISSUES: {critical_count}", flush=True)
        if high_count > 0:
            print(f"⚠️  HIGH SEVERITY ISSUES: {high_count}", flush=True)

    def _check_blocker_issues(self, result: PipelineResult) -> None:
        """
        Check for blocker issues and exit if necessary.

        Args:
            result: Pipeline execution result

        Raises:
            SystemExit: If blocker issues found
        """
        critical_count = sum(
            1 for i in result.all_issues if i.severity == IssueSeverity.CRITICAL
        )
        high_count = sum(
            1 for i in result.all_issues if i.severity == IssueSeverity.HIGH
        )

        # Fail on critical issues
        if self.fail_on_critical and critical_count > 0:
            logger.error(
                "ci_build_failed_critical",
                critical_count=critical_count,
                platform=self.ci_platform.value,
            )
            sys.exit(1)

        # Fail on high severity issues (if enabled)
        if self.fail_on_high and high_count > 0:
            logger.error(
                "ci_build_failed_high",
                high_count=high_count,
                platform=self.ci_platform.value,
            )
            sys.exit(1)

        logger.info("ci_blocker_check_passed")

    def get_platform_info(self) -> Dict[str, Any]:
        """
        Get information about the current CI platform.

        Returns:
            Dictionary with platform details
        """
        return {
            "platform": self.ci_platform.value,
            "platform_name": self.ci_platform.name,
            "is_ci": self.ci_platform != CIPlatform.UNKNOWN,
            "environment": {
                "ci": os.getenv("CI", "false"),
                "build_id": self._get_build_id(),
                "branch": self._get_branch_name(),
                "commit": self._get_commit_sha(),
            },
        }

    def _get_build_id(self) -> Optional[str]:
        """Get build ID from CI environment."""
        if self.ci_platform == CIPlatform.GITHUB_ACTIONS:
            return os.getenv("GITHUB_RUN_ID")
        elif self.ci_platform == CIPlatform.GITLAB_CI:
            return os.getenv("CI_PIPELINE_ID")
        elif self.ci_platform == CIPlatform.AZURE_PIPELINES:
            return os.getenv("BUILD_BUILDID")
        return None

    def _get_branch_name(self) -> Optional[str]:
        """Get branch name from CI environment."""
        if self.ci_platform == CIPlatform.GITHUB_ACTIONS:
            return os.getenv("GITHUB_REF_NAME")
        elif self.ci_platform == CIPlatform.GITLAB_CI:
            return os.getenv("CI_COMMIT_REF_NAME")
        elif self.ci_platform == CIPlatform.AZURE_PIPELINES:
            return os.getenv("BUILD_SOURCEBRANCHNAME")
        return None

    def _get_commit_sha(self) -> Optional[str]:
        """Get commit SHA from CI environment."""
        if self.ci_platform == CIPlatform.GITHUB_ACTIONS:
            return os.getenv("GITHUB_SHA")
        elif self.ci_platform == CIPlatform.GITLAB_CI:
            return os.getenv("CI_COMMIT_SHA")
        elif self.ci_platform == CIPlatform.AZURE_PIPELINES:
            return os.getenv("BUILD_SOURCEVERSION")
        return None
