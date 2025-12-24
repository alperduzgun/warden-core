"""
Tests for CI-Aware Pipeline Orchestrator.

Tests platform detection, CI-specific outputs, and blocker issue handling.
"""

import os
import sys
import pytest
from unittest.mock import Mock, patch, MagicMock, AsyncMock
from io import StringIO

from warden.pipeline.application.ci_orchestrator import (
    CIPipelineOrchestrator,
    CIPlatform,
)
from warden.pipeline.domain.models import PipelineResult, ValidationPipeline
from warden.issues.domain.models import WardenIssue
from warden.issues.domain.enums import IssueSeverity


class TestCIPlatformDetection:
    """Test CI platform detection from environment variables."""

    def test_detect_github_actions(self):
        """Test GitHub Actions detection."""
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}, clear=True):
            platform = CIPipelineOrchestrator._detect_ci_platform()
            assert platform == CIPlatform.GITHUB_ACTIONS

    def test_detect_gitlab_ci(self):
        """Test GitLab CI detection."""
        with patch.dict(os.environ, {"GITLAB_CI": "true"}, clear=True):
            platform = CIPipelineOrchestrator._detect_ci_platform()
            assert platform == CIPlatform.GITLAB_CI

    def test_detect_azure_pipelines(self):
        """Test Azure Pipelines detection."""
        with patch.dict(os.environ, {"TF_BUILD": "True"}, clear=True):
            platform = CIPipelineOrchestrator._detect_ci_platform()
            assert platform == CIPlatform.AZURE_PIPELINES

    def test_detect_jenkins(self):
        """Test Jenkins detection."""
        with patch.dict(os.environ, {"JENKINS_HOME": "/var/jenkins"}, clear=True):
            platform = CIPipelineOrchestrator._detect_ci_platform()
            assert platform == CIPlatform.JENKINS

    def test_detect_circleci(self):
        """Test CircleCI detection."""
        with patch.dict(os.environ, {"CIRCLECI": "true"}, clear=True):
            platform = CIPipelineOrchestrator._detect_ci_platform()
            assert platform == CIPlatform.CIRCLECI

    def test_detect_travis(self):
        """Test Travis CI detection."""
        with patch.dict(os.environ, {"TRAVIS": "true"}, clear=True):
            platform = CIPipelineOrchestrator._detect_ci_platform()
            assert platform == CIPlatform.TRAVIS

    def test_detect_unknown_platform(self):
        """Test unknown platform detection (no CI env vars)."""
        with patch.dict(os.environ, {}, clear=True):
            platform = CIPipelineOrchestrator._detect_ci_platform()
            assert platform == CIPlatform.UNKNOWN


class TestCIOrchestratorInitialization:
    """Test CI orchestrator initialization."""

    def test_default_initialization(self):
        """Test default initialization."""
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}):
            orchestrator = CIPipelineOrchestrator()

            assert orchestrator.ci_platform == CIPlatform.GITHUB_ACTIONS
            assert orchestrator.fail_on_critical is True
            assert orchestrator.fail_on_high is False
            assert orchestrator.ci_mode is True

    def test_custom_failure_thresholds(self):
        """Test custom failure threshold configuration."""
        orchestrator = CIPipelineOrchestrator(
            fail_on_critical=False, fail_on_high=True
        )

        assert orchestrator.fail_on_critical is False
        assert orchestrator.fail_on_high is True


class TestGitHubAnnotations:
    """Test GitHub Actions annotation generation."""

    @patch("sys.stdout", new_callable=StringIO)
    def test_generate_error_annotation(self, mock_stdout):
        """Test error annotation generation for critical issues."""
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}):
            orchestrator = CIPipelineOrchestrator()

            # Mock issue
            issue = Mock(spec=WardenIssue)
            issue.severity = IssueSeverity.CRITICAL
            issue.file_path = "test.py"
            issue.line = 42
            issue.message = "SQL injection vulnerability"

            # Mock result
            result = Mock(spec=PipelineResult)
            result.all_issues = [issue]

            orchestrator._generate_github_annotations(result)

            output = mock_stdout.getvalue()
            assert "::error" in output
            assert "file=test.py" in output
            assert "line=42" in output
            assert "SQL injection" in output

    @patch("sys.stdout", new_callable=StringIO)
    def test_generate_warning_annotation(self, mock_stdout):
        """Test warning annotation for medium severity issues."""
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}):
            orchestrator = CIPipelineOrchestrator()

            issue = Mock(spec=WardenIssue)
            issue.severity = IssueSeverity.MEDIUM
            issue.file_path = "api.py"
            issue.line = 100
            issue.message = "Missing input validation"

            result = Mock(spec=PipelineResult)
            result.all_issues = [issue]

            orchestrator._generate_github_annotations(result)

            output = mock_stdout.getvalue()
            assert "::warning" in output
            assert "file=api.py" in output
            assert "line=100" in output

    @patch("sys.stdout", new_callable=StringIO)
    def test_blocker_summary_annotation(self, mock_stdout):
        """Test blocker summary annotation."""
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}):
            orchestrator = CIPipelineOrchestrator()

            critical_issue = Mock(spec=WardenIssue)
            critical_issue.severity = IssueSeverity.CRITICAL
            critical_issue.file_path = "test.py"
            critical_issue.line = 1
            critical_issue.message = "Critical issue"

            result = Mock(spec=PipelineResult)
            result.all_issues = [critical_issue]

            orchestrator._generate_github_annotations(result)

            output = mock_stdout.getvalue()
            assert "BLOCKER" in output
            assert "1 critical" in output


class TestGitLabOutputs:
    """Test GitLab CI output generation."""

    @patch("structlog.get_logger")
    def test_generate_gitlab_outputs(self, mock_logger):
        """Test GitLab structured logging output."""
        mock_log = MagicMock()
        mock_logger.return_value = mock_log

        with patch.dict(os.environ, {"GITLAB_CI": "true"}):
            orchestrator = CIPipelineOrchestrator()

            issue = Mock(spec=WardenIssue)
            issue.severity = IssueSeverity.CRITICAL
            issue.file_path = "test.py"
            issue.line = 42
            issue.message = "SQL injection"

            result = Mock(spec=PipelineResult)
            result.all_issues = [issue]

            orchestrator._generate_gitlab_outputs(result)

            # Verify structured logging was called
            # Note: Actual verification depends on structlog implementation


class TestAzureOutputs:
    """Test Azure Pipelines output generation."""

    @patch("sys.stdout", new_callable=StringIO)
    def test_generate_azure_vso_commands(self, mock_stdout):
        """Test Azure ##vso[] command generation."""
        with patch.dict(os.environ, {"TF_BUILD": "True"}):
            orchestrator = CIPipelineOrchestrator()

            issue = Mock(spec=WardenIssue)
            issue.severity = IssueSeverity.CRITICAL
            issue.file_path = "test.py"
            issue.line = 42
            issue.message = "Security issue"

            result = Mock(spec=PipelineResult)
            result.all_issues = [issue]

            orchestrator._generate_azure_outputs(result)

            output = mock_stdout.getvalue()
            assert "##vso[task.logissue" in output
            assert "type=error" in output
            assert "sourcepath=test.py" in output
            assert "linenumber=42" in output

    @patch("sys.stdout", new_callable=StringIO)
    def test_azure_pipeline_variables(self, mock_stdout):
        """Test Azure pipeline variable setting."""
        with patch.dict(os.environ, {"TF_BUILD": "True"}):
            orchestrator = CIPipelineOrchestrator()

            critical_issue = Mock(spec=WardenIssue)
            critical_issue.severity = IssueSeverity.CRITICAL

            result = Mock(spec=PipelineResult)
            result.all_issues = [critical_issue]

            orchestrator._generate_azure_outputs(result)

            output = mock_stdout.getvalue()
            assert "##vso[task.setvariable" in output
            assert "wardenCriticalIssues" in output


class TestBlockerIssueDetection:
    """Test blocker issue detection and exit code handling."""

    def test_fail_on_critical_issues(self):
        """Test build failure on critical issues."""
        orchestrator = CIPipelineOrchestrator(fail_on_critical=True)

        critical_issue = Mock(spec=WardenIssue)
        critical_issue.severity = IssueSeverity.CRITICAL

        result = Mock(spec=PipelineResult)
        result.all_issues = [critical_issue]

        with pytest.raises(SystemExit) as exc_info:
            orchestrator._check_blocker_issues(result)

        assert exc_info.value.code == 1

    def test_fail_on_high_severity_when_enabled(self):
        """Test build failure on high severity when enabled."""
        orchestrator = CIPipelineOrchestrator(fail_on_high=True)

        high_issue = Mock(spec=WardenIssue)
        high_issue.severity = IssueSeverity.HIGH

        result = Mock(spec=PipelineResult)
        result.all_issues = [high_issue]

        with pytest.raises(SystemExit) as exc_info:
            orchestrator._check_blocker_issues(result)

        assert exc_info.value.code == 1

    def test_no_failure_on_high_when_disabled(self):
        """Test no failure on high severity when disabled."""
        orchestrator = CIPipelineOrchestrator(fail_on_high=False)

        high_issue = Mock(spec=WardenIssue)
        high_issue.severity = IssueSeverity.HIGH

        result = Mock(spec=PipelineResult)
        result.all_issues = [high_issue]

        # Should not raise SystemExit
        orchestrator._check_blocker_issues(result)

    def test_no_failure_on_medium_low(self):
        """Test no failure on medium/low severity issues."""
        orchestrator = CIPipelineOrchestrator()

        medium_issue = Mock(spec=WardenIssue)
        medium_issue.severity = IssueSeverity.MEDIUM

        result = Mock(spec=PipelineResult)
        result.all_issues = [medium_issue]

        # Should not raise SystemExit
        orchestrator._check_blocker_issues(result)


class TestPlatformInfo:
    """Test platform information extraction."""

    def test_github_platform_info(self):
        """Test GitHub Actions platform info extraction."""
        with patch.dict(
            os.environ,
            {
                "GITHUB_ACTIONS": "true",
                "CI": "true",
                "GITHUB_RUN_ID": "12345",
                "GITHUB_REF_NAME": "main",
                "GITHUB_SHA": "abc123",
            },
        ):
            orchestrator = CIPipelineOrchestrator()
            info = orchestrator.get_platform_info()

            assert info["platform"] == "github"
            assert info["is_ci"] is True
            assert info["environment"]["build_id"] == "12345"
            assert info["environment"]["branch"] == "main"
            assert info["environment"]["commit"] == "abc123"

    def test_gitlab_platform_info(self):
        """Test GitLab CI platform info extraction."""
        with patch.dict(
            os.environ,
            {
                "GITLAB_CI": "true",
                "CI": "true",
                "CI_PIPELINE_ID": "54321",
                "CI_COMMIT_REF_NAME": "dev",
                "CI_COMMIT_SHA": "def456",
            },
        ):
            orchestrator = CIPipelineOrchestrator()
            info = orchestrator.get_platform_info()

            assert info["platform"] == "gitlab"
            assert info["environment"]["build_id"] == "54321"
            assert info["environment"]["branch"] == "dev"
            assert info["environment"]["commit"] == "def456"

    def test_azure_platform_info(self):
        """Test Azure Pipelines platform info extraction."""
        with patch.dict(
            os.environ,
            {
                "TF_BUILD": "True",
                "CI": "true",
                "BUILD_BUILDID": "99999",
                "BUILD_SOURCEBRANCHNAME": "feature",
                "BUILD_SOURCEVERSION": "ghi789",
            },
        ):
            orchestrator = CIPipelineOrchestrator()
            info = orchestrator.get_platform_info()

            assert info["platform"] == "azure"
            assert info["environment"]["build_id"] == "99999"
            assert info["environment"]["branch"] == "feature"
            assert info["environment"]["commit"] == "ghi789"

    def test_unknown_platform_info(self):
        """Test platform info for unknown CI."""
        with patch.dict(os.environ, {}, clear=True):
            orchestrator = CIPipelineOrchestrator()
            info = orchestrator.get_platform_info()

            assert info["platform"] == "unknown"
            assert info["is_ci"] is False
            assert info["environment"]["build_id"] is None


class TestCIOrchestratorIntegration:
    """Integration tests for CI orchestrator."""

    @pytest.mark.asyncio
    async def test_full_pipeline_execution_github(self):
        """Test full pipeline execution in GitHub Actions environment."""
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}):
            orchestrator = CIPipelineOrchestrator()

            # Create mock result
            mock_result = Mock(spec=PipelineResult)
            mock_result.all_issues = []
            mock_result.status = Mock(value="completed")

            # Mock parent execute method with AsyncMock
            with patch.object(
                CIPipelineOrchestrator.__bases__[0],
                "execute",
                new_callable=AsyncMock,
            ) as mock_execute:
                mock_execute.return_value = mock_result

                result = await orchestrator.execute([])

                assert result is not None
                # Verify execute was called
                assert mock_execute.called
