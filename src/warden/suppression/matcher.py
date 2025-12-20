"""
Suppression matcher for inline comments and configuration.

This module provides the SuppressionMatcher class for checking if issues
should be suppressed based on inline comments, configuration, or global rules.

Supported inline comment patterns:
- # warden-ignore (suppress all rules on this line)
- # warden-ignore: rule-name (suppress specific rule)
- # warden-ignore: rule1, rule2 (suppress multiple rules)
- // warden-ignore (JavaScript/TypeScript variant)
"""

import re
from typing import Optional, List, Set
from pathlib import Path

from warden.suppression.models import (
    SuppressionConfig,
    SuppressionEntry,
    SuppressionType,
)


# Regex patterns for inline suppressions
INLINE_COMMENT_PATTERNS = [
    # Python: # warden-ignore or # warden-ignore: rule-name
    re.compile(r'#\s*warden-ignore(?:\s*:\s*([a-zA-Z0-9_,\s-]+))?'),
    # JavaScript/TypeScript: // warden-ignore or // warden-ignore: rule-name
    re.compile(r'//\s*warden-ignore(?:\s*:\s*([a-zA-Z0-9_,\s-]+))?'),
    # Multi-line comments: /* warden-ignore */ or /* warden-ignore: rule-name */
    re.compile(r'/\*\s*warden-ignore(?:\s*:\s*([a-zA-Z0-9_,\s-]+))?\s*\*/'),
]


class SuppressionMatcher:
    """
    Matcher for checking if issues should be suppressed.

    This class handles:
    - Inline comment parsing (# warden-ignore, // warden-ignore)
    - Configuration file suppressions
    - Global rule suppressions
    - Multi-line suppressions

    Usage:
        >>> matcher = SuppressionMatcher()
        >>> code = 'x = 1  # warden-ignore: magic-number'
        >>> matcher.is_suppressed(line=1, rule="magic-number", code=code)
        True
    """

    def __init__(self, config: Optional[SuppressionConfig] = None):
        """
        Initialize the suppression matcher.

        Args:
            config: Suppression configuration (optional)
        """
        self.config = config or SuppressionConfig()
        self._inline_cache: dict[str, dict[int, Set[str]]] = {}

    def is_suppressed(
        self,
        line: int,
        rule: str,
        code: Optional[str] = None,
        file_path: Optional[str] = None,
    ) -> bool:
        """
        Check if an issue should be suppressed.

        Checks in order:
        1. Global rule suppressions
        2. Ignored files
        3. Inline comments (if code provided)
        4. Configuration entries

        Args:
            line: Line number (1-indexed)
            rule: Rule name to check
            code: Source code (optional, for inline comments)
            file_path: File path (optional, for file-based suppressions)

        Returns:
            True if issue should be suppressed, False otherwise
        """
        if not self.config.enabled:
            return False

        # Check global rule suppressions
        if self.config.is_rule_globally_suppressed(rule):
            return True

        # Check if entire file is ignored
        if file_path and self.config.is_file_ignored(file_path):
            return True

        # Check inline comments
        if code:
            if self._check_inline_suppression(code, line, rule):
                return True

        # Check configuration entries
        if self._check_config_suppression(rule, file_path, line):
            return True

        return False

    def _check_inline_suppression(self, code: str, line: int, rule: str) -> bool:
        """
        Check if issue is suppressed by inline comment.

        Args:
            code: Source code
            line: Line number (1-indexed)
            rule: Rule name

        Returns:
            True if suppressed by inline comment, False otherwise
        """
        lines = code.splitlines()
        if line < 1 or line > len(lines):
            return False

        # Get the line (convert to 0-indexed)
        line_text = lines[line - 1]

        # Parse inline suppressions from this line
        suppressions = self._parse_inline_suppressions(line_text)

        # Empty set means suppress all rules
        if not suppressions:
            # Check if there's any warden-ignore comment
            for pattern in INLINE_COMMENT_PATTERNS:
                if pattern.search(line_text):
                    return True
            return False

        # Check if specific rule is suppressed
        return rule in suppressions

    def _parse_inline_suppressions(self, line_text: str) -> Set[str]:
        """
        Parse inline suppression comment from a line.

        Args:
            line_text: Single line of source code

        Returns:
            Set of rule names to suppress (empty set = suppress all)
        """
        for pattern in INLINE_COMMENT_PATTERNS:
            match = pattern.search(line_text)
            if match:
                # Get the rule list (group 1)
                rule_text = match.group(1)
                if not rule_text:
                    # No specific rules = suppress all
                    return set()

                # Parse comma-separated rules
                rules = {
                    rule.strip()
                    for rule in rule_text.split(',')
                    if rule.strip()
                }
                return rules

        return set()

    def _check_config_suppression(
        self,
        rule: str,
        file_path: Optional[str] = None,
        line: Optional[int] = None,
    ) -> bool:
        """
        Check if issue is suppressed by configuration entry.

        Args:
            rule: Rule name
            file_path: File path (optional)
            line: Line number (optional)

        Returns:
            True if suppressed by configuration, False otherwise
        """
        for entry in self.config.entries:
            # Check if entry is enabled
            if not entry.enabled:
                continue

            # Check if rule matches
            if not entry.matches_rule(rule):
                continue

            # Check if location matches
            if entry.matches_location(file_path, line):
                return True

        return False

    def get_suppression_reason(
        self,
        line: int,
        rule: str,
        code: Optional[str] = None,
        file_path: Optional[str] = None,
    ) -> Optional[str]:
        """
        Get the reason why an issue is suppressed.

        Args:
            line: Line number (1-indexed)
            rule: Rule name
            code: Source code (optional)
            file_path: File path (optional)

        Returns:
            Suppression reason if available, None otherwise
        """
        if not self.is_suppressed(line, rule, code, file_path):
            return None

        # Check global suppressions
        if self.config.is_rule_globally_suppressed(rule):
            return f"Rule '{rule}' is globally suppressed"

        # Check file ignorance
        if file_path and self.config.is_file_ignored(file_path):
            return f"File '{file_path}' is ignored"

        # Check configuration entries
        for entry in self.config.entries:
            if not entry.enabled:
                continue
            if entry.matches_rule(rule) and entry.matches_location(file_path, line):
                return entry.reason or f"Suppressed by configuration entry '{entry.id}'"

        # Inline comment
        if code:
            lines = code.splitlines()
            if 0 < line <= len(lines):
                line_text = lines[line - 1]
                for pattern in INLINE_COMMENT_PATTERNS:
                    if pattern.search(line_text):
                        return "Suppressed by inline comment"

        return "Suppressed (reason unknown)"

    def add_inline_suppression(
        self,
        code: str,
        line: int,
        rules: Optional[List[str]] = None,
        comment_style: str = '#',
    ) -> str:
        """
        Add inline suppression comment to code.

        Args:
            code: Source code
            line: Line number (1-indexed) to add suppression
            rules: List of rules to suppress (None = suppress all)
            comment_style: Comment style ('#' or '//')

        Returns:
            Modified code with suppression comment
        """
        lines = code.splitlines()
        if line < 1 or line > len(lines):
            return code

        # Build suppression comment
        if rules:
            rule_str = ', '.join(rules)
            comment = f"{comment_style} warden-ignore: {rule_str}"
        else:
            comment = f"{comment_style} warden-ignore"

        # Add comment to line
        line_idx = line - 1
        line_text = lines[line_idx]

        # Check if line already has a suppression
        has_suppression = any(
            pattern.search(line_text) for pattern in INLINE_COMMENT_PATTERNS
        )

        if has_suppression:
            # Don't add duplicate
            return code

        # Add comment at end of line
        if line_text.rstrip().endswith(comment_style):
            # Line already ends with comment marker
            lines[line_idx] = f"{line_text.rstrip()} warden-ignore"
        else:
            # Add new comment
            lines[line_idx] = f"{line_text}  {comment}"

        return '\n'.join(lines)

    def remove_inline_suppression(self, code: str, line: int) -> str:
        """
        Remove inline suppression comment from code.

        Args:
            code: Source code
            line: Line number (1-indexed) to remove suppression

        Returns:
            Modified code without suppression comment
        """
        lines = code.splitlines()
        if line < 1 or line > len(lines):
            return code

        line_idx = line - 1
        line_text = lines[line_idx]

        # Remove suppression comment
        for pattern in INLINE_COMMENT_PATTERNS:
            line_text = pattern.sub('', line_text)

        # Clean up trailing whitespace
        lines[line_idx] = line_text.rstrip()

        return '\n'.join(lines)

    def get_suppressed_lines(self, code: str) -> dict[int, Set[str]]:
        """
        Get all lines with inline suppressions.

        Args:
            code: Source code

        Returns:
            Dictionary mapping line number to set of suppressed rules
            (empty set means all rules suppressed)
        """
        result: dict[int, Set[str]] = {}

        for line_num, line_text in enumerate(code.splitlines(), start=1):
            suppressions = self._parse_inline_suppressions(line_text)
            if suppressions is not None:
                # Check if line has any suppression
                has_suppression = any(
                    pattern.search(line_text) for pattern in INLINE_COMMENT_PATTERNS
                )
                if has_suppression:
                    result[line_num] = suppressions

        return result
