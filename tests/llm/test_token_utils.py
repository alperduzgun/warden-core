"""
Tests for warden.shared.utils.token_utils

Covers:
1. estimate_tokens heuristic
2. truncate_content_for_llm — within budget returns unchanged
3. truncate_content_for_llm — preserves start + end lines
4. truncate_content_for_llm — includes truncation marker with correct line count
5. truncate_content_for_llm — edge cases (empty, tiny, exact budget)
"""

from __future__ import annotations

from unittest.mock import patch

from warden.shared.utils.token_utils import estimate_tokens, truncate_content_for_llm, truncate_with_ast_hints


class TestEstimateTokens:
    def test_empty_string(self):
        assert estimate_tokens("") == 0

    def test_short_string(self):
        # tiktoken: "abcd" → 1 token
        assert estimate_tokens("abcd") == 1

    def test_long_repeated_chars(self):
        # tiktoken compresses repeated chars: "a"*400 → 50 tokens (not 100)
        result = estimate_tokens("a" * 400)
        assert 30 <= result <= 80  # BPE-compressed range

    def test_monotonically_increases(self):
        """More text → more tokens (not necessarily linear due to BPE)."""
        short = estimate_tokens("x" * 100)
        long = estimate_tokens("x" * 1000)
        assert long > short


class TestTruncateContentForLlm:
    def test_content_within_limit_unchanged(self):
        """Content that fits the budget is returned as-is."""
        content = "line1\nline2\nline3"
        # 17 chars ≈ 4 tokens, well below 2000
        result = truncate_content_for_llm(content, max_tokens=2000)
        assert result == content

    def test_empty_content_returned_unchanged(self):
        result = truncate_content_for_llm("", max_tokens=100)
        assert result == ""

    def test_truncation_preserves_start_lines(self):
        """First N lines must be present after truncation."""
        lines = [f"line_{i}" for i in range(200)]
        content = "\n".join(lines)

        result = truncate_content_for_llm(content, max_tokens=50, preserve_start_lines=5, preserve_end_lines=3)

        for i in range(5):
            assert f"line_{i}" in result

    def test_truncation_preserves_end_lines(self):
        """Last M lines must be present after truncation."""
        lines = [f"line_{i}" for i in range(200)]
        content = "\n".join(lines)

        result = truncate_content_for_llm(content, max_tokens=50, preserve_start_lines=5, preserve_end_lines=3)

        for i in range(197, 200):
            assert f"line_{i}" in result

    def test_truncation_marker_present(self):
        """Truncated content must include the marker with line count."""
        lines = [f"line_{i}" for i in range(200)]
        content = "\n".join(lines)

        result = truncate_content_for_llm(content, max_tokens=50, preserve_start_lines=5, preserve_end_lines=3)

        assert "lines truncated for LLM context" in result

    def test_truncation_marker_correct_count(self):
        """The marker must report correct number of truncated lines."""
        total_lines = 100
        start = 10
        end = 5
        lines = [f"line_{i}" for i in range(total_lines)]
        content = "\n".join(lines)

        result = truncate_content_for_llm(content, max_tokens=50, preserve_start_lines=start, preserve_end_lines=end)

        expected_truncated = total_lines - start - end
        assert f"{expected_truncated} lines truncated" in result

    def test_small_content_hard_truncated(self):
        """Content with fewer lines than start+end budget → hard char truncation."""
        # 15 lines, preserve_start=10, preserve_end=10 → total >= lines count
        lines = [f"line_{i}" for i in range(15)]
        content = "\n".join(lines)

        # Very tight token budget to force truncation
        result = truncate_content_for_llm(content, max_tokens=5, preserve_start_lines=10, preserve_end_lines=10)

        # Result must be truncated (shorter than original)
        assert len(result) < len(content)

    def test_result_fits_token_budget(self):
        """Truncated result token count must not greatly exceed max_tokens."""
        lines = [f"{'x' * 50}" for _ in range(500)]
        content = "\n".join(lines)
        max_tokens = 100

        result = truncate_content_for_llm(content, max_tokens=max_tokens)

        # truncate_content_for_llm uses 4 chars/token char budget as hard cap
        assert len(result) <= max_tokens * 4 + 200

    def test_within_budget_not_truncated(self):
        """Content within the token budget should not be truncated."""
        # tiktoken: "a"*8000 = 1000 tokens, well within 2000
        content = "a" * 8000
        result = truncate_content_for_llm(content, max_tokens=2000)
        assert result == content
        assert "truncated" not in result

class TestTruncateWithAstHints:
    def test_within_budget_unchanged(self):
        content = "line1\\nline2\\nline3"
        result = truncate_with_ast_hints(content, max_tokens=2000)
        assert result == content

    @patch('warden.shared.utils.token_utils.estimate_tokens')
    def test_overlapping_windows_merged(self, mock_est):
        mock_est.side_effect = lambda text: 1000 if len(text) > 500 else 10
        lines = [f"line_{i}" for i in range(1, 101)] # 100 lines
        content = "\n".join(lines)
        
        # dangerous lines 20 and 22. With +/- 5 window, they overlap (15-25 and 17-27 -> 15-27)
        result = truncate_with_ast_hints(content, max_tokens=100, dangerous_lines=[20, 22], preserve_start_lines=5, preserve_end_lines=5)
        
        assert "line_1\n" in result
        assert "line_5\n" in result
        assert "  ... [9 lines omitted] ..." in result
        assert "line_15\n" in result
        assert "line_27\n" in result
        assert "  ... [68 lines omitted] ..." in result
        assert "line_96\n" in result
        assert "line_100" in result

    @patch('warden.shared.utils.token_utils.estimate_tokens')
    def test_out_of_bounds_lines_handled(self, mock_est):
        mock_est.side_effect = lambda text: 1000 if len(text) > 500 else 10
        lines = [f"line_{i}" for i in range(1, 101)] # 100 lines
        content = "\n".join(lines)
        
        # dangerous line 200 (out of bounds)
        result = truncate_with_ast_hints(content, max_tokens=100, dangerous_lines=[200], preserve_start_lines=2, preserve_end_lines=2)
        
        assert "line_1\n" in result
        assert "line_2\n" in result
        assert "line_99\n" in result
        assert "line_100" in result

    @patch('warden.shared.utils.token_utils.estimate_tokens')
    def test_no_dangerous_lines(self, mock_est):
        mock_est.side_effect = lambda text: 1000 if len(text) > 500 else 10
        lines = [f"line_{i}" for i in range(1, 101)] # 100 lines
        content = "\n".join(lines)
        
        # Empty dangerous lines
        result = truncate_with_ast_hints(content, max_tokens=100, dangerous_lines=[], preserve_start_lines=5, preserve_end_lines=5)
        
        assert "line_1\n" in result
        assert "line_5\n" in result
        assert "... [90 lines truncated for LLM context] ..." in result
        assert "line_96\n" in result

