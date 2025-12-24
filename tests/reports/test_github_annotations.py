"""
Tests for GitHub Actions Annotations generator.

Tests workflow command generation, annotation formatting, and output utilities.
"""

import os
from pathlib import Path
from unittest.mock import Mock, patch, mock_open
from io import StringIO
import pytest

from warden.reports.github_annotations import GitHubAnnotations
from warden.issues.domain.models import WardenIssue
from warden.issues.domain.enums import IssueSeverity
from warden.pipeline.domain.models import PipelineResult, FrameExecution


class TestIssueAnnotationGeneration:
    """Test individual issue annotation generation."""

    def test_critical_issue_annotation(self):
        """Test error annotation for critical issues."""
        issue = Mock(spec=WardenIssue)
        issue.severity = IssueSeverity.CRITICAL
        issue.file_path = "src/security.py"
        issue.line = 42
        issue.message = "SQL injection vulnerability detected"
        issue.rule_id = "SEC-001"

        annotation = GitHubAnnotations.generate_issue_annotation(issue)

        assert annotation.startswith("::error")
        assert "file=src/security.py" in annotation
        assert "line=42" in annotation
        assert "[SEC-001]" in annotation
        assert "SQL injection" in annotation
        assert "🔴 CRITICAL" in annotation

    def test_high_severity_annotation(self):
        """Test error annotation for high severity issues."""
        issue = Mock(spec=WardenIssue)
        issue.severity = IssueSeverity.HIGH
        issue.file_path = "api.py"
        issue.line = 100
        issue.message = "Missing authentication check"

        annotation = GitHubAnnotations.generate_issue_annotation(issue)

        assert annotation.startswith("::error")
        assert "🟠 HIGH" in annotation

    def test_medium_severity_annotation(self):
        """Test warning annotation for medium severity."""
        issue = Mock(spec=WardenIssue)
        issue.severity = IssueSeverity.MEDIUM
        issue.file_path = "utils.py"
        issue.line = 50
        issue.message = "Missing input validation"

        annotation = GitHubAnnotations.generate_issue_annotation(issue)

        assert annotation.startswith("::warning")
        assert "🟡 MEDIUM" in annotation

    def test_low_severity_annotation(self):
        """Test notice annotation for low severity."""
        issue = Mock(spec=WardenIssue)
        issue.severity = IssueSeverity.LOW
        issue.file_path = "docs.py"
        issue.line = 10
        issue.message = "Missing docstring"

        annotation = GitHubAnnotations.generate_issue_annotation(issue)

        assert annotation.startswith("::notice")
        assert "🔵 LOW" in annotation


class TestAnnotationWithLocation:
    """Test annotation with file location information."""

    def test_annotation_with_file_and_line(self):
        """Test annotation with file path and line number."""
        issue = Mock(spec=WardenIssue)
        issue.severity = IssueSeverity.CRITICAL
        issue.file_path = "test.py"
        issue.line = 42
        issue.message = "Security issue"

        annotation = GitHubAnnotations.generate_issue_annotation(issue)

        assert "file=test.py" in annotation
        assert "line=42" in annotation

    def test_annotation_with_line_range(self):
        """Test annotation with line range."""
        issue = Mock(spec=WardenIssue)
        issue.severity = IssueSeverity.MEDIUM
        issue.file_path = "test.py"
        issue.line = 10
        issue.end_line = 15
        issue.message = "Multi-line issue"

        annotation = GitHubAnnotations.generate_issue_annotation(issue)

        assert "line=10" in annotation
        assert "endLine=15" in annotation

    def test_annotation_with_column(self):
        """Test annotation with column information."""
        issue = Mock(spec=WardenIssue)
        issue.severity = IssueSeverity.HIGH
        issue.file_path = "test.py"
        issue.line = 20
        issue.column = 5
        issue.end_column = 15
        issue.message = "Column-specific issue"

        annotation = GitHubAnnotations.generate_issue_annotation(issue)

        assert "col=5" in annotation
        assert "endColumn=15" in annotation

    def test_annotation_without_location(self):
        """Test annotation without file location."""
        issue = Mock(spec=WardenIssue)
        issue.severity = IssueSeverity.MEDIUM
        issue.message = "General warning"
        # No file_path, line, etc.

        annotation = GitHubAnnotations.generate_issue_annotation(issue)

        assert annotation.startswith("::warning")
        assert "file=" not in annotation
        assert "line=" not in annotation


class TestBatchAnnotationGeneration:
    """Test batch annotation generation."""

    def test_generate_all_annotations(self):
        """Test generating annotations for multiple issues."""
        issues = [
            Mock(
                spec=WardenIssue,
                severity=IssueSeverity.CRITICAL,
                file_path="file1.py",
                line=1,
                message="Critical issue",
            ),
            Mock(
                spec=WardenIssue,
                severity=IssueSeverity.MEDIUM,
                file_path="file2.py",
                line=2,
                message="Medium issue",
            ),
        ]

        annotations = GitHubAnnotations.generate_all_annotations(issues)

        assert len(annotations) == 2
        assert "::error" in annotations[0]
        assert "::warning" in annotations[1]

    def test_generate_empty_annotations(self):
        """Test generating annotations for empty issue list."""
        annotations = GitHubAnnotations.generate_all_annotations([])

        assert len(annotations) == 0


class TestSummaryAnnotations:
    """Test summary annotation generation."""

    def test_summary_with_critical_issues(self):
        """Test summary annotation with critical issues."""
        result = Mock(spec=PipelineResult)
        result.all_issues = [
            Mock(severity=IssueSeverity.CRITICAL),
            Mock(severity=IssueSeverity.CRITICAL),
            Mock(severity=IssueSeverity.HIGH),
        ]

        annotations = GitHubAnnotations.generate_summary_annotation(result)

        assert len(annotations) > 0
        assert any("BLOCKER" in a for a in annotations)
        assert any("2 critical" in a for a in annotations)

    def test_summary_with_high_issues(self):
        """Test summary annotation with high severity issues."""
        result = Mock(spec=PipelineResult)
        result.all_issues = [
            Mock(severity=IssueSeverity.HIGH),
            Mock(severity=IssueSeverity.HIGH),
            Mock(severity=IssueSeverity.HIGH),
        ]

        annotations = GitHubAnnotations.generate_summary_annotation(result)

        assert any("3 high severity" in a for a in annotations)

    def test_summary_with_no_issues(self):
        """Test summary annotation with no issues."""
        result = Mock(spec=PipelineResult)
        result.all_issues = []

        annotations = GitHubAnnotations.generate_summary_annotation(result)

        assert any("No issues found" in a for a in annotations)
        assert any("::notice" in a for a in annotations)

    def test_summary_with_mixed_severity(self):
        """Test summary with mixed severity levels."""
        result = Mock(spec=PipelineResult)
        result.all_issues = [
            Mock(severity=IssueSeverity.CRITICAL),
            Mock(severity=IssueSeverity.HIGH),
            Mock(severity=IssueSeverity.MEDIUM),
            Mock(severity=IssueSeverity.LOW),
        ]

        annotations = GitHubAnnotations.generate_summary_annotation(result)

        summary_text = " ".join(annotations)
        assert "Critical: 1" in summary_text or "1" in summary_text
        assert "Total: 4" in summary_text or "4 issues" in summary_text


class TestGroupedAnnotations:
    """Test grouped annotation generation by validation frame."""

    def test_grouped_annotations(self):
        """Test grouping annotations by frame."""
        frame1 = Mock(spec=FrameExecution)
        frame1.frame_name = "Security Frame"
        frame1.status = "completed"
        frame1.issues = [
            Mock(
                severity=IssueSeverity.CRITICAL,
                file_path="test.py",
                line=1,
                message="Security issue",
            )
        ]

        frame2 = Mock(spec=FrameExecution)
        frame2.frame_name = "Fuzz Frame"
        frame2.status = "completed"
        frame2.issues = []

        annotations = GitHubAnnotations.generate_group_annotations([frame1, frame2])

        # Should have groups for both frames
        assert any("::group::" in a and "Security Frame" in a for a in annotations)
        assert any("::group::" in a and "Fuzz Frame" in a for a in annotations)
        assert any("::endgroup::" in a for a in annotations)

    def test_group_with_no_issues(self):
        """Test group annotation when frame has no issues."""
        frame = Mock(spec=FrameExecution)
        frame.frame_name = "Test Frame"
        frame.status = "completed"
        frame.issues = []

        annotations = GitHubAnnotations.generate_group_annotations([frame])

        assert any("::group::" in a for a in annotations)
        assert any("No issues found" in a for a in annotations)
        assert any("::endgroup::" in a for a in annotations)


class TestPrintAnnotations:
    """Test printing annotations to stdout."""

    @patch("sys.stdout", new_callable=StringIO)
    def test_print_issue_annotations(self, mock_stdout):
        """Test printing issue annotations."""
        issues = [
            Mock(
                spec=WardenIssue,
                severity=IssueSeverity.CRITICAL,
                file_path="test.py",
                line=1,
                message="Test issue",
            )
        ]

        GitHubAnnotations.print_annotations(issues=issues)

        output = mock_stdout.getvalue()
        assert "::error" in output
        assert "test.py" in output

    @patch("sys.stdout", new_callable=StringIO)
    def test_print_result_annotations(self, mock_stdout):
        """Test printing result annotations."""
        result = Mock(spec=PipelineResult)
        result.all_issues = [Mock(severity=IssueSeverity.CRITICAL)]

        GitHubAnnotations.print_annotations(result=result)

        output = mock_stdout.getvalue()
        assert "BLOCKER" in output or "critical" in output

    @patch("sys.stdout", new_callable=StringIO)
    def test_print_grouped_annotations(self, mock_stdout):
        """Test printing grouped annotations."""
        frame = Mock(spec=FrameExecution)
        frame.frame_name = "Test Frame"
        frame.status = "completed"
        frame.issues = []

        result = Mock(spec=PipelineResult)
        result.all_issues = []
        result.frame_executions = [frame]

        GitHubAnnotations.print_annotations(result=result, grouped=True)

        output = mock_stdout.getvalue()
        assert "::group::" in output
        assert "Test Frame" in output


class TestOutputHelpers:
    """Test GitHub Actions output helper functions."""

    @patch("sys.stdout", new_callable=StringIO)
    def test_set_output(self, mock_stdout):
        """Test set-output command."""
        GitHubAnnotations.set_output("test_var", "test_value")

        output = mock_stdout.getvalue()
        assert "::set-output name=test_var::test_value" in output

    @patch.dict(os.environ, {}, clear=True)
    @patch("builtins.open", new_callable=mock_open)
    @patch("pathlib.Path.exists", return_value=True)
    def test_set_environment_variable_modern(self, mock_exists, mock_file):
        """Test environment variable setting (modern syntax)."""
        with patch.dict(os.environ, {"GITHUB_ENV": "/tmp/github_env"}):
            GitHubAnnotations.set_environment_variable("TEST_VAR", "test_value")

            mock_file.assert_called_with("/tmp/github_env", "a")
            mock_file().write.assert_called_with("TEST_VAR=test_value\n")

    @patch("sys.stdout", new_callable=StringIO)
    @patch.dict(os.environ, {}, clear=True)
    def test_set_environment_variable_fallback(self, mock_stdout):
        """Test environment variable setting (fallback syntax)."""
        GitHubAnnotations.set_environment_variable("TEST_VAR", "test_value")

        output = mock_stdout.getvalue()
        assert "::set-env name=TEST_VAR::test_value" in output

    @patch("sys.stdout", new_callable=StringIO)
    def test_add_mask(self, mock_stdout):
        """Test adding mask for sensitive values."""
        GitHubAnnotations.add_mask("secret_token_12345")

        output = mock_stdout.getvalue()
        assert "::add-mask::secret_token_12345" in output

    @patch("sys.stdout", new_callable=StringIO)
    def test_stop_commands(self, mock_stdout):
        """Test stopping workflow commands."""
        GitHubAnnotations.stop_commands("pause_token")

        output = mock_stdout.getvalue()
        assert "::stop-commands::pause_token" in output

    @patch("sys.stdout", new_callable=StringIO)
    def test_resume_commands(self, mock_stdout):
        """Test resuming workflow commands."""
        GitHubAnnotations.resume_commands("pause_token")

        output = mock_stdout.getvalue()
        assert "::pause_token::" in output


class TestAnnotationFormatting:
    """Test annotation formatting edge cases."""

    def test_annotation_with_special_characters(self):
        """Test annotation with special characters in message."""
        issue = Mock(spec=WardenIssue)
        issue.severity = IssueSeverity.MEDIUM
        issue.file_path = "test.py"
        issue.line = 1
        issue.message = "Error: \"quoted\" value with 'apostrophe'"

        annotation = GitHubAnnotations.generate_issue_annotation(issue)

        assert "::warning" in annotation
        assert "quoted" in annotation

    def test_annotation_with_newlines(self):
        """Test annotation with newlines in message."""
        issue = Mock(spec=WardenIssue)
        issue.severity = IssueSeverity.LOW
        issue.file_path = "test.py"
        issue.line = 1
        issue.message = "Multi\nline\nmessage"

        annotation = GitHubAnnotations.generate_issue_annotation(issue)

        assert "::notice" in annotation
        # Newlines should be preserved or escaped

    def test_annotation_with_unicode(self):
        """Test annotation with unicode characters."""
        issue = Mock(spec=WardenIssue)
        issue.severity = IssueSeverity.MEDIUM
        issue.file_path = "test.py"
        issue.line = 1
        issue.message = "Unicode issue: 你好 🚀"

        annotation = GitHubAnnotations.generate_issue_annotation(issue)

        assert "::warning" in annotation
        assert "Unicode issue" in annotation


class TestAnnotationWithoutAttributes:
    """Test annotations when optional attributes are missing."""

    def test_issue_without_rule_id(self):
        """Test annotation when rule_id is missing."""
        issue = Mock(spec=WardenIssue)
        issue.severity = IssueSeverity.CRITICAL
        issue.file_path = "test.py"
        issue.line = 1
        issue.message = "Issue without rule ID"
        # No rule_id attribute

        annotation = GitHubAnnotations.generate_issue_annotation(issue)

        assert "::error" in annotation
        assert "[" not in annotation  # No rule ID prefix

    def test_issue_without_line_number(self):
        """Test annotation when line number is missing."""
        issue = Mock(spec=WardenIssue)
        issue.severity = IssueSeverity.HIGH
        issue.file_path = "test.py"
        issue.message = "Issue without line"
        # No line attribute

        annotation = GitHubAnnotations.generate_issue_annotation(issue)

        assert "::error" in annotation
        assert "file=test.py" in annotation
        assert "line=" not in annotation

    def test_issue_minimal_attributes(self):
        """Test annotation with only severity and message."""
        issue = Mock(spec=WardenIssue)
        issue.severity = IssueSeverity.MEDIUM
        issue.message = "Minimal issue"
        # No file, line, rule_id

        annotation = GitHubAnnotations.generate_issue_annotation(issue)

        assert "::warning" in annotation
        assert "Minimal issue" in annotation
        assert "file=" not in annotation
