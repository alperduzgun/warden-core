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

from warden.shared.utils.token_utils import estimate_tokens, truncate_content_for_llm


class TestEstimateTokens:
    def test_empty_string(self):
        assert estimate_tokens("") == 0

    def test_approximation(self):
        # 4 chars ≈ 1 token
        assert estimate_tokens("abcd") == 1
        assert estimate_tokens("a" * 400) == 100

    def test_scales_linearly(self):
        short = estimate_tokens("x" * 100)
        long = estimate_tokens("x" * 1000)
        assert long == short * 10


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

        # Result must fit within char budget
        assert len(result) <= 5 * 4 + 1  # small tolerance

    def test_result_fits_char_budget(self):
        """Truncated result must not exceed max_tokens * 4 chars (approx)."""
        lines = [f"{'x' * 50}" for _ in range(500)]
        content = "\n".join(lines)
        max_tokens = 100

        result = truncate_content_for_llm(content, max_tokens=max_tokens)

        # Allow some overhead for the truncation marker itself
        assert len(result) <= max_tokens * 4 + 200

    def test_exact_budget_not_truncated(self):
        """Content at exactly the token budget should not be truncated."""
        # 2000 tokens * 4 chars = 8000 chars
        content = "a" * 8000
        result = truncate_content_for_llm(content, max_tokens=2000)
        assert result == content
        assert "truncated" not in result
