"""
Content validation rules for false positive detection.

This module provides validation rules that verify the quality and accuracy
of issue findings by validating code snippets, evidence quotes, and metadata.

Rules:
    - CodeSnippetMatchRule: Validates code snippet matches file content
    - EvidenceQuoteRule: Validates evidence quote exists in code snippet
    - TitleDescriptionQualityRule: Validates title/description quality

Each rule implements the ValidationRule protocol from issue_validator.py
and integrates with the IssueValidator orchestrator.

Integration:
    These rules extend the base validation system with content-specific checks.
    They can be registered with IssueValidator using add_rule().

    Example:
        >>> from warden.core.validation import IssueValidator
        >>> from warden.core.validation.content_rules import CodeSnippetMatchRule
        >>>
        >>> validator = IssueValidator()
        >>> validator.add_rule(CodeSnippetMatchRule())
        >>> result = validator.validate(issue)

Reporter-only: These rules only report issues, never modify code.
Fail-safe: File read errors result in passing validation (avoid false rejections).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

from warden.core.validation.issue_validator import BaseValidationRule
from warden.issues.domain.models import WardenIssue

logger = logging.getLogger(__name__)


# ============================================================================
# CODE SNIPPET MATCH RULE
# ============================================================================


class CodeSnippetMatchRule(BaseValidationRule):
    """
    Validates that code snippet matches actual file content at line number.

    This rule reads the file, extracts the line at the specified line_number,
    and compares it with the code_snippet using fuzzy matching (strip whitespace).

    If file reading fails, the validation passes (fail-safe approach).

    Penalty: -0.4 (high penalty for mismatch)

    Example:
        >>> rule = CodeSnippetMatchRule()
        >>> issue = WardenIssue(
        ...     code_snippet="print('hello')",
        ...     file_path="/path/to/file.py:10"
        ... )
        >>> rule.validate(issue)
        True  # If line 10 matches the snippet
    """

    def __init__(self) -> None:
        """Initialize code snippet match rule."""
        super().__init__(
            name="CodeSnippetMatch",
            confidence_penalty=-0.4,  # High penalty for mismatch
        )

    def validate(self, issue: WardenIssue) -> bool:
        """
        Validate code snippet matches file content.

        Args:
            issue: Issue with code_snippet and file_path

        Returns:
            True if snippet matches file content, False otherwise
        """
        # Extract line number from file_path (e.g., "file.py:45")
        line_number = self._extract_line_number(issue.file_path)
        if line_number is None:
            logger.debug(
                f"Issue {issue.id}: No line number in file_path, skipping snippet validation"
            )
            return True  # Cannot validate without line number

        # Extract file path without line number
        file_path = self._extract_file_path(issue.file_path)

        # Normalize code snippet (strip whitespace)
        normalized_snippet = issue.code_snippet.strip()

        if not normalized_snippet:
            logger.warning(f"Issue {issue.id}: Code snippet is empty")
            return False

        # Try to read file (fail-safe: pass if read fails)
        try:
            file_path_obj = Path(file_path)
            if not file_path_obj.exists():
                logger.debug(
                    f"Issue {issue.id}: File not found: {file_path} (fail-safe pass)"
                )
                return True  # Fail-safe: cannot verify, assume valid

            # Read file content
            with file_path_obj.open("r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()

            # Validate line number is in range (1-indexed)
            if line_number < 1 or line_number > len(lines):
                logger.warning(
                    f"Issue {issue.id}: Line number {line_number} out of range (1-{len(lines)})"
                )
                return False

            # Get the line at line_number (convert to 0-indexed)
            actual_line = lines[line_number - 1].strip()

            # Fuzzy match: strip whitespace and compare
            if normalized_snippet == actual_line:
                return True

            # Check if snippet is substring of line (partial match)
            if normalized_snippet in actual_line or actual_line in normalized_snippet:
                return True

            # No match
            logger.debug(
                f"Issue {issue.id}: Code snippet mismatch. "
                f"Expected: '{actual_line}', Got: '{normalized_snippet}'"
            )
            return False

        except Exception as e:
            # Fail-safe: pass validation if file read fails
            logger.debug(
                f"Issue {issue.id}: File read error (fail-safe pass): {e}",
                exc_info=True,
            )
            return True

    def _extract_line_number(self, file_path: str) -> Optional[int]:
        """
        Extract line number from file_path (e.g., "file.py:45").

        Args:
            file_path: File path with optional line number

        Returns:
            Line number or None if not found
        """
        if ":" in file_path:
            try:
                parts = file_path.split(":")
                if len(parts) >= 2:
                    return int(parts[1])
            except (ValueError, IndexError):
                pass
        return None

    def _extract_file_path(self, file_path: str) -> str:
        """
        Extract file path without line number.

        Args:
            file_path: File path with optional line number (e.g., "file.py:45")

        Returns:
            File path without line number
        """
        if ":" in file_path:
            return file_path.split(":")[0]
        return file_path


# ============================================================================
# EVIDENCE QUOTE RULE
# ============================================================================


class EvidenceQuoteRule(BaseValidationRule):
    """
    Validates that evidence quote exists in code snippet.

    This rule checks if the evidence_quote (if provided in message) exists as a
    substring in the code_snippet. Partial matches are allowed.

    Since WardenIssue doesn't have a dedicated evidence_quote field, this rule
    looks for quoted text in the message field.

    Penalty: -0.3

    Example:
        >>> rule = EvidenceQuoteRule()
        >>> issue = WardenIssue(
        ...     message="The code 'user_id = None' is problematic",
        ...     code_snippet="user_id = None  # Initialize"
        ... )
        >>> rule.validate(issue)
        True  # Quote found in snippet
    """

    def __init__(self) -> None:
        """Initialize evidence quote rule."""
        super().__init__(
            name="EvidenceQuoteMatch",
            confidence_penalty=-0.3,  # Moderate penalty
        )

    def validate(self, issue: WardenIssue) -> bool:
        """
        Validate evidence quote exists in code snippet.

        Args:
            issue: Issue with message and code_snippet

        Returns:
            True if evidence quote found in snippet, False otherwise
        """
        # Extract quoted text from message (text in single or double quotes)
        evidence_quotes = self._extract_quotes(issue.message)

        if not evidence_quotes:
            # No evidence quotes in message - skip validation
            return True

        # Normalize code snippet (strip whitespace, case-insensitive)
        normalized_snippet = issue.code_snippet.strip().lower()

        if not normalized_snippet:
            logger.warning(
                f"Issue {issue.id}: Code snippet is empty but message has evidence quotes"
            )
            return False

        # Check if any evidence quote exists in code snippet
        for quote in evidence_quotes:
            normalized_quote = quote.strip().lower()
            if normalized_quote and normalized_quote in normalized_snippet:
                return True

        # No evidence quotes found in snippet
        logger.debug(
            f"Issue {issue.id}: Evidence quotes not found in code snippet: {evidence_quotes}"
        )
        return False

    def _extract_quotes(self, text: str) -> list[str]:
        """
        Extract quoted text from message.

        Args:
            text: Message text

        Returns:
            List of quoted strings
        """
        quotes = []

        # Extract single-quoted strings
        single_quotes = re.findall(r"'([^']+)'", text)
        quotes.extend(single_quotes)

        # Extract double-quoted strings
        double_quotes = re.findall(r'"([^"]+)"', text)
        quotes.extend(double_quotes)

        # Extract backtick-quoted strings (markdown code)
        backtick_quotes = re.findall(r"`([^`]+)`", text)
        quotes.extend(backtick_quotes)

        return quotes


# ============================================================================
# TITLE/DESCRIPTION QUALITY RULE
# ============================================================================


class TitleDescriptionQualityRule(BaseValidationRule):
    """
    Validates title and description quality.

    This rule checks:
    - Message (used as title) is not empty and has minimum 10 characters
    - Message doesn't contain placeholders (TODO, FIX, ISSUE)

    Note: WardenIssue doesn't have separate title/description fields,
    so we validate the message field.

    Penalty: -0.2

    Example:
        >>> rule = TitleDescriptionQualityRule()
        >>> issue = WardenIssue(message="TODO: Fix this")
        >>> rule.validate(issue)
        False  # Contains placeholder
    """

    # Placeholder patterns to detect
    PLACEHOLDER_PATTERNS = [
        r"\bTODO\b",
        r"\bFIX\b",
        r"\bFIXME\b",
        r"\bISSUE\b",
        r"\bXXX\b",
        r"\bHACK\b",
        r"\bNOTE\b",
    ]

    def __init__(self, min_message_length: int = 10) -> None:
        """
        Initialize title/description quality rule.

        Args:
            min_message_length: Minimum message length (default: 10)
        """
        super().__init__(
            name="TitleDescriptionQuality",
            confidence_penalty=-0.2,  # Low penalty
        )
        self._min_message_length = min_message_length

    def validate(self, issue: WardenIssue) -> bool:
        """
        Validate message (title) quality.

        Args:
            issue: Issue with message field

        Returns:
            True if message meets quality standards, False otherwise
        """
        message = issue.message.strip()

        # Check message is not empty and meets minimum length
        if not message:
            logger.warning(f"Issue {issue.id}: Message is empty")
            return False

        if len(message) < self._min_message_length:
            logger.debug(
                f"Issue {issue.id}: Message too short ({len(message)} < {self._min_message_length})"
            )
            return False

        # Check for placeholders in message
        message_upper = message.upper()
        for pattern in self.PLACEHOLDER_PATTERNS:
            if re.search(pattern, message_upper):
                logger.debug(f"Issue {issue.id}: Message contains placeholder: '{message}'")
                return False

        return True


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "CodeSnippetMatchRule",
    "EvidenceQuoteRule",
    "TitleDescriptionQualityRule",
]
