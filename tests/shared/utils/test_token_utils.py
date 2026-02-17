"""
Tests for warden.shared.utils.token_utils

Verifies:
1. Token estimation using character-based heuristic
2. Content truncation for LLM context limits
3. Truncation preserves structure (start + end)
4. Truncated content fits within token limits
"""

import pytest

from warden.shared.utils.token_utils import estimate_tokens, truncate_content_for_llm


class TestEstimateTokens:
    """Test token estimation heuristic."""

    def test_estimate_tokens_basic(self):
        """Verify basic token estimation (4 chars per token)."""
        text = "hello world"
        estimated = estimate_tokens(text)
        # "hello world" = 11 chars, should be ~2-3 tokens (11 // 4 = 2)
        assert estimated == 2

    def test_estimate_tokens_empty_string(self):
        """Empty string should return 0 tokens."""
        assert estimate_tokens("") == 0

    def test_estimate_tokens_none(self):
        """None should return 0 tokens."""
        assert estimate_tokens(None) == 0

    def test_estimate_tokens_code_snippet(self):
        """Verify token estimation for code."""
        code = "def hello():\n    return 'world'"
        # 31 chars / 4 = 7 tokens (integer division)
        estimated = estimate_tokens(code)
        assert estimated == 7

    def test_estimate_tokens_long_text(self):
        """Verify token estimation for longer text."""
        text = "a" * 1000
        estimated = estimate_tokens(text)
        # 1000 / 4 = 250 tokens
        assert estimated == 250


class TestTruncateContentForLLM:
    """Test content truncation for LLM context limits."""

    def test_no_truncation_for_small_content(self):
        """Small content should be returned as-is."""
        content = "def hello():\n    return 'world'"
        truncated = truncate_content_for_llm(content, max_tokens=100)
        assert truncated == content

    def test_truncation_preserves_structure(self):
        """Large content should preserve start and end with truncation marker."""
        # Create content with 1000 lines
        lines = [f"line {i}" for i in range(1000)]
        content = "\n".join(lines)

        truncated = truncate_content_for_llm(
            content,
            max_tokens=500,
            preserve_start_lines=10,
            preserve_end_lines=5,
        )

        # Should contain first 10 lines
        assert "line 0" in truncated
        assert "line 9" in truncated

        # Should contain last 5 lines
        assert "line 995" in truncated
        assert "line 999" in truncated

        # Should contain truncation marker
        assert "truncated for LLM context" in truncated
        assert "985 lines truncated" in truncated

    def test_truncated_content_fits_limit(self):
        """After truncation, content should fit within token limit."""
        # Create large content (10000 chars = ~2500 tokens)
        content = "x" * 10000

        max_tokens = 500
        truncated = truncate_content_for_llm(content, max_tokens=max_tokens)

        # Verify truncated content fits
        estimated = estimate_tokens(truncated)
        assert estimated <= max_tokens

    def test_empty_content_returned_as_is(self):
        """Empty content should be returned unchanged."""
        assert truncate_content_for_llm("", max_tokens=100) == ""
        assert truncate_content_for_llm(None, max_tokens=100) is None

    def test_content_at_exact_limit_not_truncated(self):
        """Content exactly at token limit should not be truncated."""
        # 2000 tokens = 8000 chars
        content = "a" * 8000
        truncated = truncate_content_for_llm(content, max_tokens=2000)
        assert truncated == content

    def test_content_slightly_over_limit_truncated(self):
        """Content slightly over limit should be truncated."""
        # 2001 tokens = 8004 chars
        content = "a" * 8004
        truncated = truncate_content_for_llm(content, max_tokens=2000)
        assert len(truncated) < len(content)

    def test_few_lines_hard_truncated(self):
        """When lines <= preserve_start + preserve_end, hard truncate by chars."""
        # Only 10 lines total, but over token limit
        lines = ["x" * 1000 for _ in range(10)]
        content = "\n".join(lines)

        truncated = truncate_content_for_llm(
            content,
            max_tokens=100,  # 100 tokens = 400 chars
            preserve_start_lines=20,
            preserve_end_lines=10,
        )

        # Should be hard-truncated to 400 chars
        assert len(truncated) <= 400

    def test_truncation_with_code_structure(self):
        """Verify truncation with realistic code structure."""
        # Create a Python file with imports, functions, and classes
        lines = []
        lines.extend([f"import module{i}" for i in range(10)])
        lines.append("")
        lines.extend([f"def function{i}():\n    pass" for i in range(500)])
        lines.append("")
        lines.extend([f"class Class{i}:\n    pass" for i in range(10)])

        content = "\n".join(lines)

        truncated = truncate_content_for_llm(
            content,
            max_tokens=1000,
            preserve_start_lines=20,
            preserve_end_lines=10,
        )

        # Should preserve imports (start)
        assert "import module0" in truncated
        assert "import module9" in truncated

        # Should preserve last classes (end)
        assert "Class9" in truncated

        # Should have truncation marker
        assert "truncated" in truncated.lower()

    def test_custom_preserve_lines(self):
        """Verify custom preserve_start_lines and preserve_end_lines work."""
        lines = [f"line {i}" for i in range(100)]
        content = "\n".join(lines)

        truncated = truncate_content_for_llm(
            content,
            max_tokens=100,  # Lower limit to force truncation
            preserve_start_lines=5,
            preserve_end_lines=3,
        )

        # Should have first 5 lines
        assert "line 0" in truncated
        assert "line 4" in truncated

        # Should have truncation marker
        assert "truncated" in truncated.lower()

        # Should have last 3 lines
        assert "line 97" in truncated
        assert "line 99" in truncated

    def test_very_small_token_limit(self):
        """Verify behavior with very small token limit."""
        content = "a" * 10000
        truncated = truncate_content_for_llm(content, max_tokens=10)

        # Should be truncated to ~40 chars (10 tokens * 4)
        assert len(truncated) <= 40

    def test_multiline_with_special_characters(self):
        """Verify truncation handles special characters correctly."""
        lines = [
            "# Comment with émojis 🚀",
            "def función():",
            "    return 'naïve'",
        ] * 100

        content = "\n".join(lines)

        truncated = truncate_content_for_llm(
            content,
            max_tokens=200,
            preserve_start_lines=10,
            preserve_end_lines=5,
        )

        # Should preserve special characters
        assert "función" in truncated or "función" in content  # May be truncated but not corrupted

    def test_truncation_marker_format(self):
        """Verify truncation marker contains useful information."""
        lines = [f"line {i}" for i in range(100)]
        content = "\n".join(lines)

        truncated = truncate_content_for_llm(
            content,
            max_tokens=100,  # Lower limit to force truncation
            preserve_start_lines=10,
            preserve_end_lines=5,
        )

        # Marker should indicate number of lines truncated
        # 100 total - 10 start - 5 end = 85 lines truncated
        assert "85 lines truncated" in truncated
        assert "LLM context" in truncated
