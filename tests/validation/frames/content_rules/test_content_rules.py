"""
Unit tests for content validation rules.

Tests all validation rules with various scenarios including:
- Success cases (validation passes)
- Failure cases (validation fails with penalty)
- Edge cases (empty strings, missing parameters)
- Fail-safe behavior (file read errors)
"""

from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

import pytest

from warden.core.validation.content_rules import (
    CodeSnippetMatchRule,
    EvidenceQuoteRule,
    TitleDescriptionQualityRule,
)
from warden.issues.domain.enums import IssueSeverity, IssueState
from warden.issues.domain.models import WardenIssue


def create_test_issue(
    issue_id: str = "W001",
    file_path: str = "test.py",
    message: str = "Test issue message",
    code_snippet: str = "print('test')",
    line_number: int | None = None,
) -> WardenIssue:
    """
    Create a test WardenIssue for testing.

    Args:
        issue_id: Issue ID
        file_path: File path (optionally with :line_number)
        message: Issue message
        code_snippet: Code snippet
        line_number: Optional line number to append to file_path

    Returns:
        WardenIssue instance
    """
    # Append line number to file_path if provided
    if line_number is not None:
        file_path = f"{file_path}:{line_number}"

    return WardenIssue(
        id=issue_id,
        type="Test Issue",
        severity=IssueSeverity.MEDIUM,
        file_path=file_path,
        message=message,
        code_snippet=code_snippet,
        code_hash="test_hash",
        state=IssueState.OPEN,
        first_detected=datetime.now(),
        last_updated=datetime.now(),
        reopen_count=0,
        state_history=[],
    )


class TestCodeSnippetMatchRule:
    """Test CodeSnippetMatchRule."""

    def test_rule_properties(self):
        """Test rule name and penalty."""
        rule = CodeSnippetMatchRule()
        assert rule.name == "CodeSnippetMatch"
        assert rule.confidence_penalty == -0.4

    def test_exact_match(self):
        """Test exact match between snippet and file content."""
        # Create temp file with content
        with NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("def hello():\n")
            f.write("    print('Hello, World!')\n")
            f.write("    return True\n")
            temp_path = f.name

        try:
            issue = create_test_issue(
                file_path=temp_path,
                line_number=2,
                code_snippet="    print('Hello, World!')",
            )

            rule = CodeSnippetMatchRule()
            result = rule.validate(issue)

            assert result is True
        finally:
            Path(temp_path).unlink()

    def test_partial_match(self):
        """Test partial match between snippet and file content."""
        # Create temp file with content
        with NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("def hello():\n")
            f.write("    result = process_data(input_value)  # Process input\n")
            f.write("    return result\n")
            temp_path = f.name

        try:
            # Snippet is substring of actual line
            issue = create_test_issue(
                file_path=temp_path,
                line_number=2,
                code_snippet="process_data(input_value)",
            )

            rule = CodeSnippetMatchRule()
            result = rule.validate(issue)

            assert result is True
        finally:
            Path(temp_path).unlink()

    def test_mismatch(self):
        """Test mismatch between snippet and file content."""
        # Create temp file with content
        with NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("def hello():\n")
            f.write("    print('Actual content')\n")
            f.write("    return True\n")
            temp_path = f.name

        try:
            issue = create_test_issue(
                file_path=temp_path,
                line_number=2,
                code_snippet="print('Different content')",
            )

            rule = CodeSnippetMatchRule()
            result = rule.validate(issue)

            assert result is False
        finally:
            Path(temp_path).unlink()

    def test_line_number_out_of_range(self):
        """Test line number beyond file length."""
        # Create temp file with 3 lines
        with NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("line 1\n")
            f.write("line 2\n")
            f.write("line 3\n")
            temp_path = f.name

        try:
            issue = create_test_issue(
                file_path=temp_path,
                line_number=10,  # Out of range
                code_snippet="line 10",
            )

            rule = CodeSnippetMatchRule()
            result = rule.validate(issue)

            assert result is False
        finally:
            Path(temp_path).unlink()

    def test_file_not_found_failsafe(self):
        """Test fail-safe behavior when file doesn't exist."""
        issue = create_test_issue(
            file_path="/nonexistent/path/file.py",
            line_number=1,
            code_snippet="print('test')",
        )

        rule = CodeSnippetMatchRule()
        result = rule.validate(issue)

        # Should pass (fail-safe)
        assert result is True

    def test_no_line_number_skipped(self):
        """Test validation skipped when no line number provided."""
        issue = create_test_issue(
            file_path="/some/path.py",  # No line number
            code_snippet="print('test')",
        )

        rule = CodeSnippetMatchRule()
        result = rule.validate(issue)

        assert result is True

    def test_empty_snippet(self):
        """Test validation fails for empty snippet."""
        # Create temp file
        with NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("print('test')\n")
            temp_path = f.name

        try:
            issue = create_test_issue(
                file_path=temp_path,
                line_number=1,
                code_snippet="",  # Empty snippet
            )

            rule = CodeSnippetMatchRule()
            result = rule.validate(issue)

            assert result is False
        finally:
            Path(temp_path).unlink()

    def test_whitespace_normalization(self):
        """Test that whitespace differences are normalized."""
        # Create temp file with extra whitespace
        with NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("    print('test')    \n")
            temp_path = f.name

        try:
            issue = create_test_issue(
                file_path=temp_path,
                line_number=1,
                code_snippet="print('test')",  # No leading/trailing whitespace
            )

            rule = CodeSnippetMatchRule()
            result = rule.validate(issue)

            assert result is True
        finally:
            Path(temp_path).unlink()


class TestEvidenceQuoteRule:
    """Test EvidenceQuoteRule."""

    def test_rule_properties(self):
        """Test rule name and penalty."""
        rule = EvidenceQuoteRule()
        assert rule.name == "EvidenceQuoteMatch"
        assert rule.confidence_penalty == -0.3

    def test_single_quote_match(self):
        """Test match with single-quoted evidence in message."""
        issue = create_test_issue(
            message="The code 'user_id = None' is problematic",
            code_snippet="user_id = None  # Initialize",
        )

        rule = EvidenceQuoteRule()
        result = rule.validate(issue)

        assert result is True

    def test_double_quote_match(self):
        """Test match with double-quoted evidence in message."""
        issue = create_test_issue(
            message='The code "request.get(\'user_id\')" is unsafe',
            code_snippet="user_id = request.get('user_id')",
        )

        rule = EvidenceQuoteRule()
        result = rule.validate(issue)

        assert result is True

    def test_backtick_quote_match(self):
        """Test match with backtick-quoted evidence in message (markdown)."""
        issue = create_test_issue(
            message="The code `password = None` needs validation",
            code_snippet="password = None  # SECURITY ISSUE",
        )

        rule = EvidenceQuoteRule()
        result = rule.validate(issue)

        assert result is True

    def test_case_insensitive_match(self):
        """Test case-insensitive matching."""
        issue = create_test_issue(
            message="The code 'USER_ID' is not defined",
            code_snippet="user_id = request.get('user_id')",
        )

        rule = EvidenceQuoteRule()
        result = rule.validate(issue)

        assert result is True

    def test_no_match(self):
        """Test no match between evidence quote and code snippet."""
        issue = create_test_issue(
            message="The code 'password = None' is problematic",
            code_snippet="user_id = request.get('user_id')",
        )

        rule = EvidenceQuoteRule()
        result = rule.validate(issue)

        assert result is False

    def test_no_evidence_quote_skipped(self):
        """Test validation skipped when no evidence quote in message."""
        issue = create_test_issue(
            message="This is a general issue without quotes",
            code_snippet="user_id = request.get('user_id')",
        )

        rule = EvidenceQuoteRule()
        result = rule.validate(issue)

        # Should pass (no quotes to validate)
        assert result is True

    def test_empty_snippet_with_evidence(self):
        """Test validation fails when snippet is empty but message has quotes."""
        issue = create_test_issue(
            message="The code 'some evidence' is problematic",
            code_snippet="",  # Empty snippet
        )

        rule = EvidenceQuoteRule()
        result = rule.validate(issue)

        assert result is False

    def test_multiple_quotes_one_matches(self):
        """Test validation passes if at least one quote matches."""
        issue = create_test_issue(
            message="The code 'password' and 'user_id' need validation",
            code_snippet="user_id = None  # Initialize",
        )

        rule = EvidenceQuoteRule()
        result = rule.validate(issue)

        # Should pass (user_id matches)
        assert result is True


class TestTitleDescriptionQualityRule:
    """Test TitleDescriptionQualityRule."""

    def test_rule_properties(self):
        """Test rule name and penalty."""
        rule = TitleDescriptionQualityRule()
        assert rule.name == "TitleDescriptionQuality"
        assert rule.confidence_penalty == -0.2

    def test_valid_message(self):
        """Test valid message passes validation."""
        issue = create_test_issue(
            message="Missing null check in user authentication function",
        )

        rule = TitleDescriptionQualityRule()
        result = rule.validate(issue)

        assert result is True

    def test_empty_message(self):
        """Test empty message fails validation."""
        issue = create_test_issue(message="")

        rule = TitleDescriptionQualityRule()
        result = rule.validate(issue)

        assert result is False

    def test_message_too_short(self):
        """Test message shorter than 10 characters fails."""
        issue = create_test_issue(message="Short")  # Only 5 characters

        rule = TitleDescriptionQualityRule()
        result = rule.validate(issue)

        assert result is False

    def test_message_with_todo_placeholder(self):
        """Test message with TODO placeholder fails."""
        issue = create_test_issue(message="TODO: Fix this security issue")

        rule = TitleDescriptionQualityRule()
        result = rule.validate(issue)

        assert result is False

    def test_message_with_fixme_placeholder(self):
        """Test message with FIXME placeholder fails."""
        issue = create_test_issue(message="FIXME: Security vulnerability in auth")

        rule = TitleDescriptionQualityRule()
        result = rule.validate(issue)

        assert result is False

    def test_message_with_issue_placeholder(self):
        """Test message with ISSUE placeholder fails."""
        issue = create_test_issue(message="ISSUE: Authentication problem detected")

        rule = TitleDescriptionQualityRule()
        result = rule.validate(issue)

        assert result is False

    def test_message_with_hack_placeholder(self):
        """Test message with HACK placeholder fails."""
        issue = create_test_issue(message="HACK: Temporary workaround for bug")

        rule = TitleDescriptionQualityRule()
        result = rule.validate(issue)

        assert result is False

    def test_minimum_valid_length(self):
        """Test minimum valid length (exactly 10 characters)."""
        issue = create_test_issue(message="1234567890")  # Exactly 10 characters

        rule = TitleDescriptionQualityRule()
        result = rule.validate(issue)

        assert result is True

    def test_case_insensitive_placeholder_detection(self):
        """Test placeholder detection is case-insensitive."""
        # Lowercase
        issue1 = create_test_issue(message="todo: fix this issue later on")
        rule = TitleDescriptionQualityRule()
        assert rule.validate(issue1) is False

        # Mixed case
        issue2 = create_test_issue(message="ToDo: fix this issue later on")
        assert rule.validate(issue2) is False

        # Uppercase
        issue3 = create_test_issue(message="TODO: FIX THIS ISSUE LATER")
        assert rule.validate(issue3) is False

    def test_custom_min_length(self):
        """Test custom minimum message length."""
        rule = TitleDescriptionQualityRule(min_message_length=20)

        # Less than 20 characters
        issue1 = create_test_issue(message="Short message")
        assert rule.validate(issue1) is False

        # Exactly 20 characters
        issue2 = create_test_issue(message="12345678901234567890")
        assert rule.validate(issue2) is True

        # More than 20 characters
        issue3 = create_test_issue(message="This is a longer message with more than 20 chars")
        assert rule.validate(issue3) is True
