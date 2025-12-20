"""
Tests for suppression matcher.

Tests coverage:
- Inline comment parsing
- Suppression matching
- Configuration-based suppression
- Global rule suppression
- Multi-line suppressions
- Adding/removing inline suppressions
"""

import pytest
from warden.suppression.matcher import SuppressionMatcher
from warden.suppression.models import (
    SuppressionConfig,
    SuppressionEntry,
    SuppressionType,
)


class TestInlineCommentParsing:
    """Test inline comment parsing."""

    def test_parse_python_suppress_all(self) -> None:
        """Test parsing Python comment that suppresses all rules."""
        matcher = SuppressionMatcher()
        code = "x = 1  # warden-ignore"
        assert matcher.is_suppressed(line=1, rule='magic-number', code=code) is True
        assert matcher.is_suppressed(line=1, rule='any-rule', code=code) is True

    def test_parse_python_suppress_specific(self) -> None:
        """Test parsing Python comment with specific rule."""
        matcher = SuppressionMatcher()
        code = "x = 1  # warden-ignore: magic-number"
        assert matcher.is_suppressed(line=1, rule='magic-number', code=code) is True
        assert matcher.is_suppressed(line=1, rule='other-rule', code=code) is False

    def test_parse_python_suppress_multiple(self) -> None:
        """Test parsing Python comment with multiple rules."""
        matcher = SuppressionMatcher()
        code = "x = 1  # warden-ignore: magic-number, unused-import"
        assert matcher.is_suppressed(line=1, rule='magic-number', code=code) is True
        assert matcher.is_suppressed(line=1, rule='unused-import', code=code) is True
        assert matcher.is_suppressed(line=1, rule='other-rule', code=code) is False

    def test_parse_javascript_suppress_all(self) -> None:
        """Test parsing JavaScript comment that suppresses all rules."""
        matcher = SuppressionMatcher()
        code = "const x = 1;  // warden-ignore"
        assert matcher.is_suppressed(line=1, rule='magic-number', code=code) is True
        assert matcher.is_suppressed(line=1, rule='any-rule', code=code) is True

    def test_parse_javascript_suppress_specific(self) -> None:
        """Test parsing JavaScript comment with specific rule."""
        matcher = SuppressionMatcher()
        code = "const x = 1;  // warden-ignore: magic-number"
        assert matcher.is_suppressed(line=1, rule='magic-number', code=code) is True
        assert matcher.is_suppressed(line=1, rule='other-rule', code=code) is False

    def test_parse_multiline_comment(self) -> None:
        """Test parsing multi-line comment."""
        matcher = SuppressionMatcher()
        code = "const x = 1;  /* warden-ignore: magic-number */"
        assert matcher.is_suppressed(line=1, rule='magic-number', code=code) is True
        assert matcher.is_suppressed(line=1, rule='other-rule', code=code) is False

    def test_parse_with_whitespace(self) -> None:
        """Test parsing with various whitespace."""
        matcher = SuppressionMatcher()
        code = "x = 1  #  warden-ignore  :  magic-number  "
        assert matcher.is_suppressed(line=1, rule='magic-number', code=code) is True

    def test_no_suppression(self) -> None:
        """Test line without suppression."""
        matcher = SuppressionMatcher()
        code = "x = 1  # regular comment"
        assert matcher.is_suppressed(line=1, rule='magic-number', code=code) is False


class TestSuppressionMatching:
    """Test suppression matching logic."""

    def test_inline_suppression(self) -> None:
        """Test inline suppression matching."""
        matcher = SuppressionMatcher()
        code = """
def foo():
    x = 1  # warden-ignore: magic-number
    y = 2
    return x + y
"""
        # Line 3 has suppression
        assert matcher.is_suppressed(line=3, rule='magic-number', code=code) is True
        # Line 4 doesn't have suppression
        assert matcher.is_suppressed(line=4, rule='magic-number', code=code) is False

    def test_global_rule_suppression(self) -> None:
        """Test global rule suppression."""
        config = SuppressionConfig(
            global_rules=['unused-import', 'magic-number']
        )
        matcher = SuppressionMatcher(config)

        # Global rules are suppressed everywhere
        assert matcher.is_suppressed(line=1, rule='unused-import') is True
        assert matcher.is_suppressed(line=1, rule='magic-number') is True
        assert matcher.is_suppressed(line=100, rule='unused-import') is True

        # Other rules are not suppressed
        assert matcher.is_suppressed(line=1, rule='sql-injection') is False

    def test_file_ignored(self) -> None:
        """Test file ignorance."""
        config = SuppressionConfig(
            ignored_files=['test_*.py', 'migrations/*.py']
        )
        matcher = SuppressionMatcher(config)

        # Ignored files suppress all rules
        assert matcher.is_suppressed(
            line=1, rule='any-rule', file_path='test_app.py'
        ) is True
        assert matcher.is_suppressed(
            line=1, rule='any-rule', file_path='migrations/001.py'
        ) is True

        # Non-ignored files don't suppress
        assert matcher.is_suppressed(
            line=1, rule='any-rule', file_path='src/app.py'
        ) is False

    def test_config_entry_suppression(self) -> None:
        """Test configuration entry suppression."""
        entry = SuppressionEntry(
            id='test-1',
            type=SuppressionType.CONFIG,
            rules=['sql-injection'],
            file='legacy/*.py',
        )
        config = SuppressionConfig(entries=[entry])
        matcher = SuppressionMatcher(config)

        # Matching file and rule
        assert matcher.is_suppressed(
            line=1, rule='sql-injection', file_path='legacy/db.py'
        ) is True

        # Non-matching rule
        assert matcher.is_suppressed(
            line=1, rule='xss', file_path='legacy/db.py'
        ) is False

        # Non-matching file
        assert matcher.is_suppressed(
            line=1, rule='sql-injection', file_path='src/db.py'
        ) is False

    def test_disabled_config(self) -> None:
        """Test disabled configuration doesn't suppress."""
        config = SuppressionConfig(
            enabled=False,
            global_rules=['unused-import'],
        )
        matcher = SuppressionMatcher(config)

        assert matcher.is_suppressed(line=1, rule='unused-import') is False

    def test_priority_order(self) -> None:
        """Test suppression priority order."""
        entry = SuppressionEntry(
            id='test-1',
            type=SuppressionType.CONFIG,
            rules=['magic-number'],
            file='src/app.py',
        )
        config = SuppressionConfig(
            global_rules=['unused-import'],
            ignored_files=['test_*.py'],
            entries=[entry],
        )
        matcher = SuppressionMatcher(config)

        # Global rule takes priority
        assert matcher.is_suppressed(
            line=1, rule='unused-import', file_path='any.py'
        ) is True

        # Ignored file takes priority
        assert matcher.is_suppressed(
            line=1, rule='any-rule', file_path='test_foo.py'
        ) is True

        # Config entry
        assert matcher.is_suppressed(
            line=1, rule='magic-number', file_path='src/app.py'
        ) is True


class TestSuppressionReason:
    """Test getting suppression reasons."""

    def test_global_rule_reason(self) -> None:
        """Test reason for global rule suppression."""
        config = SuppressionConfig(global_rules=['unused-import'])
        matcher = SuppressionMatcher(config)

        reason = matcher.get_suppression_reason(line=1, rule='unused-import')
        assert reason is not None
        assert 'globally suppressed' in reason.lower()

    def test_ignored_file_reason(self) -> None:
        """Test reason for ignored file."""
        config = SuppressionConfig(ignored_files=['test_*.py'])
        matcher = SuppressionMatcher(config)

        reason = matcher.get_suppression_reason(
            line=1, rule='any-rule', file_path='test_app.py'
        )
        assert reason is not None
        assert 'ignored' in reason.lower()

    def test_config_entry_reason(self) -> None:
        """Test reason for config entry suppression."""
        entry = SuppressionEntry(
            id='test-1',
            type=SuppressionType.CONFIG,
            rules=['sql-injection'],
            file='legacy/*.py',
            reason='Legacy code to be refactored',
        )
        config = SuppressionConfig(entries=[entry])
        matcher = SuppressionMatcher(config)

        reason = matcher.get_suppression_reason(
            line=1, rule='sql-injection', file_path='legacy/db.py'
        )
        assert reason is not None
        assert 'Legacy code to be refactored' in reason

    def test_inline_comment_reason(self) -> None:
        """Test reason for inline comment suppression."""
        matcher = SuppressionMatcher()
        code = "x = 1  # warden-ignore: magic-number"

        reason = matcher.get_suppression_reason(
            line=1, rule='magic-number', code=code
        )
        assert reason is not None
        assert 'inline comment' in reason.lower()

    def test_no_suppression_reason(self) -> None:
        """Test no reason when not suppressed."""
        matcher = SuppressionMatcher()

        reason = matcher.get_suppression_reason(line=1, rule='any-rule')
        assert reason is None


class TestAddRemoveInlineSuppression:
    """Test adding and removing inline suppressions."""

    def test_add_inline_suppression_all(self) -> None:
        """Test adding suppression for all rules."""
        matcher = SuppressionMatcher()
        code = "x = 1"

        modified = matcher.add_inline_suppression(code, line=1)
        assert "# warden-ignore" in modified

    def test_add_inline_suppression_specific(self) -> None:
        """Test adding suppression for specific rules."""
        matcher = SuppressionMatcher()
        code = "x = 1"

        modified = matcher.add_inline_suppression(
            code, line=1, rules=['magic-number', 'unused-var']
        )
        assert "# warden-ignore: magic-number, unused-var" in modified

    def test_add_inline_suppression_javascript(self) -> None:
        """Test adding JavaScript-style suppression."""
        matcher = SuppressionMatcher()
        code = "const x = 1;"

        modified = matcher.add_inline_suppression(
            code, line=1, comment_style='//'
        )
        assert "// warden-ignore" in modified

    def test_add_inline_suppression_duplicate(self) -> None:
        """Test adding suppression to line that already has one."""
        matcher = SuppressionMatcher()
        code = "x = 1  # warden-ignore"

        modified = matcher.add_inline_suppression(code, line=1)
        # Should not add duplicate
        assert modified == code

    def test_add_inline_suppression_invalid_line(self) -> None:
        """Test adding suppression to invalid line."""
        matcher = SuppressionMatcher()
        code = "x = 1"

        # Line 0
        modified = matcher.add_inline_suppression(code, line=0)
        assert modified == code

        # Line beyond end
        modified = matcher.add_inline_suppression(code, line=100)
        assert modified == code

    def test_remove_inline_suppression(self) -> None:
        """Test removing inline suppression."""
        matcher = SuppressionMatcher()
        code = "x = 1  # warden-ignore: magic-number"

        modified = matcher.remove_inline_suppression(code, line=1)
        assert "warden-ignore" not in modified
        assert "x = 1" in modified

    def test_remove_inline_suppression_javascript(self) -> None:
        """Test removing JavaScript-style suppression."""
        matcher = SuppressionMatcher()
        code = "const x = 1;  // warden-ignore"

        modified = matcher.remove_inline_suppression(code, line=1)
        assert "warden-ignore" not in modified
        assert "const x = 1;" in modified

    def test_remove_inline_suppression_no_suppression(self) -> None:
        """Test removing suppression from line without one."""
        matcher = SuppressionMatcher()
        code = "x = 1  # regular comment"

        modified = matcher.remove_inline_suppression(code, line=1)
        # Should preserve regular comment
        assert "# regular comment" in modified

    def test_remove_inline_suppression_invalid_line(self) -> None:
        """Test removing suppression from invalid line."""
        matcher = SuppressionMatcher()
        code = "x = 1"

        # Line 0
        modified = matcher.remove_inline_suppression(code, line=0)
        assert modified == code

        # Line beyond end
        modified = matcher.remove_inline_suppression(code, line=100)
        assert modified == code


class TestGetSuppressedLines:
    """Test getting all suppressed lines."""

    def test_get_suppressed_lines_empty(self) -> None:
        """Test getting suppressed lines from code without suppressions."""
        matcher = SuppressionMatcher()
        code = """
def foo():
    x = 1
    return x
"""
        result = matcher.get_suppressed_lines(code)
        assert result == {}

    def test_get_suppressed_lines_multiple(self) -> None:
        """Test getting multiple suppressed lines."""
        matcher = SuppressionMatcher()
        code = """
def foo():
    x = 1  # warden-ignore: magic-number
    y = 2  # warden-ignore
    z = 3
    return x + y + z  # warden-ignore: complexity
"""
        result = matcher.get_suppressed_lines(code)

        # Line 3 suppresses specific rule
        assert 3 in result
        assert 'magic-number' in result[3]

        # Line 4 suppresses all rules (empty set)
        assert 4 in result
        assert len(result[4]) == 0

        # Line 5 has no suppression
        assert 5 not in result

        # Line 6 suppresses specific rule
        assert 6 in result
        assert 'complexity' in result[6]

    def test_get_suppressed_lines_javascript(self) -> None:
        """Test getting suppressed lines from JavaScript code."""
        matcher = SuppressionMatcher()
        code = """
function foo() {
    const x = 1;  // warden-ignore: magic-number
    const y = 2;  /* warden-ignore */
    return x + y;
}
"""
        result = matcher.get_suppressed_lines(code)

        assert 3 in result
        assert 'magic-number' in result[3]

        assert 4 in result
        assert len(result[4]) == 0


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_code(self) -> None:
        """Test with empty code."""
        matcher = SuppressionMatcher()
        assert matcher.is_suppressed(line=1, rule='any-rule', code='') is False

    def test_line_out_of_bounds(self) -> None:
        """Test with line number out of bounds."""
        matcher = SuppressionMatcher()
        code = "x = 1"

        assert matcher.is_suppressed(line=0, rule='any-rule', code=code) is False
        assert matcher.is_suppressed(line=100, rule='any-rule', code=code) is False

    def test_multiline_code(self) -> None:
        """Test with multi-line code."""
        matcher = SuppressionMatcher()
        code = """
def calculate_total(items):
    total = 0  # warden-ignore: magic-number
    for item in items:
        total += item.price
    return total
"""
        # Line 3 has suppression
        assert matcher.is_suppressed(line=3, rule='magic-number', code=code) is True
        # Line 4 doesn't have suppression
        assert matcher.is_suppressed(line=4, rule='magic-number', code=code) is False

    def test_disabled_entry(self) -> None:
        """Test with disabled entry."""
        entry = SuppressionEntry(
            id='test-1',
            type=SuppressionType.CONFIG,
            rules=['magic-number'],
            enabled=False,
        )
        config = SuppressionConfig(entries=[entry])
        matcher = SuppressionMatcher(config)

        assert matcher.is_suppressed(line=1, rule='magic-number') is False

    def test_case_sensitivity(self) -> None:
        """Test case sensitivity in rule names."""
        matcher = SuppressionMatcher()
        code = "x = 1  # warden-ignore: magic-number"

        # Exact case match
        assert matcher.is_suppressed(line=1, rule='magic-number', code=code) is True
        # Different case should not match
        assert matcher.is_suppressed(line=1, rule='Magic-Number', code=code) is False
        assert matcher.is_suppressed(line=1, rule='MAGIC-NUMBER', code=code) is False
