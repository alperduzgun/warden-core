"""
Suppression matcher for checking if issues should be suppressed.

Main class:
- SuppressionMatcher: Checks if a specific line/rule should be suppressed

Supports:
- Inline comments (# warden-ignore, // warden-ignore, /* warden-ignore */)
- Configuration-based suppression
- Global rule suppression
- File pattern matching
"""

import re
from typing import Dict, List, Optional, Set

from warden.suppression.models import SuppressionConfig, SuppressionType


class SuppressionMatcher:
    """
    Matches suppressions against code locations.

    Checks suppressions in priority order:
    1. Global rules
    2. Ignored files
    3. Configuration entries
    4. Inline comments
    """

    def __init__(self, config: SuppressionConfig | None = None):
        """
        Initialize suppression matcher.

        Args:
            config: Suppression configuration (default: empty config)
        """
        self.config = config or SuppressionConfig()

        # Compile inline comment patterns
        self._inline_patterns = [
            # Python-style: # warden-ignore or # warden-ignore: rule1, rule2
            re.compile(r"#\s*warden-ignore(?:\s*:\s*(.+?))?\s*$"),
            # JavaScript-style: // warden-ignore or // warden-ignore: rule1, rule2
            re.compile(r"//\s*warden-ignore(?:\s*:\s*(.+?))?\s*$"),
            # Multi-line comment: /* warden-ignore */ or /* warden-ignore: rule1 */
            re.compile(r"/\*\s*warden-ignore(?:\s*:\s*(.+?))?\s*\*/"),
        ]

    def is_suppressed(
        self,
        line: int,
        rule: str,
        file_path: str | None = None,
        code: str | None = None,
    ) -> bool:
        """
        Check if a specific line/rule should be suppressed.

        Args:
            line: Line number (1-indexed)
            rule: Rule name to check
            file_path: Optional file path
            code: Optional source code (for inline comment parsing)

        Returns:
            True if suppressed, False otherwise
        """
        # Check if config is disabled
        if not self.config.enabled:
            return False

        # Priority 1: Global rules
        if self.config.is_rule_globally_suppressed(rule):
            return True

        # Priority 2: Ignored files
        if file_path and self.config.is_file_ignored(file_path):
            return True

        # Priority 3: Configuration entries
        for entry in self.config.entries:
            if not entry.enabled:
                continue

            # Check if entry matches this location
            if entry.matches_location(file_path=file_path, line_number=line):
                # Check if entry suppresses this rule
                if entry.matches_rule(rule):
                    return True

        # Priority 4: Inline comments
        if code:
            suppressed_rules = self._parse_inline_suppression(code, line)
            if suppressed_rules is not None:
                # Empty set means suppress all rules
                if len(suppressed_rules) == 0:
                    return True
                # Check if rule is in the set
                if rule in suppressed_rules:
                    return True

        return False

    def get_suppression_reason(
        self,
        line: int,
        rule: str,
        file_path: str | None = None,
        code: str | None = None,
    ) -> str | None:
        """
        Get the reason why a line/rule is suppressed.

        Args:
            line: Line number (1-indexed)
            rule: Rule name
            file_path: Optional file path
            code: Optional source code

        Returns:
            Reason string if suppressed, None otherwise
        """
        # Check if config is disabled
        if not self.config.enabled:
            return None

        # Priority 1: Global rules
        if self.config.is_rule_globally_suppressed(rule):
            return f"Rule '{rule}' is globally suppressed"

        # Priority 2: Ignored files
        if file_path and self.config.is_file_ignored(file_path):
            return f"File '{file_path}' is ignored"

        # Priority 3: Configuration entries
        for entry in self.config.entries:
            if not entry.enabled:
                continue

            if entry.matches_location(file_path=file_path, line_number=line) and entry.matches_rule(rule):
                if entry.reason:
                    return entry.reason
                return f"Suppressed by configuration entry '{entry.id}'"

        # Priority 4: Inline comments
        if code:
            suppressed_rules = self._parse_inline_suppression(code, line)
            if suppressed_rules is not None and (len(suppressed_rules) == 0 or rule in suppressed_rules):
                return "Suppressed by inline comment"

        return None

    def _parse_inline_suppression(self, code: str, line: int) -> set[str] | None:
        """
        Parse inline suppression comment from code.

        Args:
            code: Source code
            line: Line number (1-indexed)

        Returns:
            Set of suppressed rules, or empty set if all rules suppressed,
            or None if no suppression found
        """
        if not code or line <= 0:
            return None

        lines = code.split("\n")
        if line > len(lines):
            return None

        line_content = lines[line - 1]

        # Safety: Skip extremely long lines to prevent ReDoS
        if len(line_content) > 4096:
            return None

        # Try each pattern
        for pattern in self._inline_patterns:
            match = pattern.search(line_content)
            if match:
                rules_str = match.group(1)
                if rules_str:
                    # Specific rules
                    rules = [rule.strip() for rule in rules_str.split(",") if rule.strip()]
                    return set(rules)
                else:
                    # Suppress all rules
                    return set()

        return None

    def add_inline_suppression(
        self,
        code: str,
        line: int,
        rules: list[str] | None = None,
        comment_style: str = "#",
    ) -> str:
        """
        Add inline suppression comment to code.

        Args:
            code: Source code
            line: Line number (1-indexed)
            rules: Optional list of specific rules to suppress (None = all)
            comment_style: Comment style ('#' or '//')

        Returns:
            Modified code with suppression comment added
        """
        if not code or line <= 0:
            return code

        lines = code.split("\n")
        if line > len(lines):
            return code

        line_content = lines[line - 1]

        # Check if already has suppression
        if self._parse_inline_suppression(code, line) is not None:
            return code

        # Build suppression comment
        if rules:
            suppression = f"warden-ignore: {', '.join(rules)}"
        else:
            suppression = "warden-ignore"

        # Add comment to line
        modified_line = f"{line_content}  {comment_style} {suppression}"
        lines[line - 1] = modified_line

        return "\n".join(lines)

    def remove_inline_suppression(self, code: str, line: int) -> str:
        """
        Remove inline suppression comment from code.

        Args:
            code: Source code
            line: Line number (1-indexed)

        Returns:
            Modified code with suppression comment removed
        """
        if not code or line <= 0:
            return code

        lines = code.split("\n")
        if line > len(lines):
            return code

        line_content = lines[line - 1]

        # Remove suppression patterns
        modified_line = line_content
        for pattern in self._inline_patterns:
            modified_line = pattern.sub("", modified_line)

        # Clean up trailing whitespace
        modified_line = modified_line.rstrip()

        lines[line - 1] = modified_line
        return "\n".join(lines)

    def get_suppressed_lines(self, code: str) -> dict[int, set[str]]:
        """
        Get all lines with inline suppressions.

        Args:
            code: Source code

        Returns:
            Dictionary mapping line numbers to sets of suppressed rules
            (empty set means all rules suppressed)
        """
        if not code:
            return {}

        result: dict[int, set[str]] = {}
        lines = code.split("\n")

        for line_num, _line_content in enumerate(lines, start=1):
            suppressed_rules = self._parse_inline_suppression(code, line_num)
            if suppressed_rules is not None:
                result[line_num] = suppressed_rules

        return result
