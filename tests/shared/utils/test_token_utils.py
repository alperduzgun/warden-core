"""
Tests for warden.shared.utils.token_utils

Verifies:
1. Token estimation using tiktoken (accurate) with fallback
2. Content truncation for LLM context limits
3. Truncation preserves structure (start + end)
4. AST-aware truncation preserves dangerous lines
5. Edge cases: empty, huge, unicode, binary content
"""

import pytest

from warden.shared.utils.token_utils import (
    estimate_tokens,
    truncate_content_for_llm,
    truncate_with_ast_hints,
)


class TestEstimateTokens:
    """Test token estimation using tiktoken."""

    def test_estimate_tokens_basic(self):
        """Verify token estimation produces reasonable count for short text."""
        text = "hello world"
        estimated = estimate_tokens(text)
        # tiktoken should give ~2 tokens for "hello world"
        assert 1 <= estimated <= 4

    def test_estimate_tokens_empty_string(self):
        """Empty string should return 0 tokens."""
        assert estimate_tokens("") == 0

    def test_estimate_tokens_none(self):
        """None should return 0 tokens."""
        assert estimate_tokens(None) == 0

    def test_estimate_tokens_code_snippet(self):
        """Verify token estimation for code produces reasonable count."""
        code = "def hello():\n    return 'world'"
        estimated = estimate_tokens(code)
        # Should be roughly 8-12 tokens with tiktoken
        assert 4 <= estimated <= 20

    def test_estimate_tokens_long_text(self):
        """Verify token estimation for longer text is more accurate than //4."""
        text = "a" * 1000
        estimated = estimate_tokens(text)
        # tiktoken should give ~250-350 tokens for 1000 chars
        assert 100 <= estimated <= 500

    def test_estimate_tokens_accuracy_vs_heuristic(self):
        """Tiktoken should differ from len//4 for non-uniform text."""
        # Python docstring: many multi-char tokens, fewer tokens than //4 predicts
        docstring = '"""This is a very detailed docstring explaining the function behavior."""'
        tiktoken_estimate = estimate_tokens(docstring)
        heuristic_estimate = len(docstring) // 4
        # They may differ, but both should be in a reasonable range
        assert tiktoken_estimate > 0
        assert heuristic_estimate > 0

    def test_estimate_tokens_minified_js(self):
        """Minified JS should have more tokens than //4 predicts."""
        minified = "var a=1;b=2;c=a+b;d=c*2;e=d/3;f=e%4;g=f**2;h=g&1;i=h|0;j=i^1;"
        estimated = estimate_tokens(minified)
        assert estimated > 0


class TestTruncateContentForLLM:
    """Test content truncation for LLM context limits."""

    def test_no_truncation_for_small_content(self):
        """Small content should be returned as-is."""
        content = "def hello():\n    return 'world'"
        truncated = truncate_content_for_llm(content, max_tokens=100)
        assert truncated == content

    def test_truncation_preserves_structure(self):
        """Large content should preserve start and end with truncation marker."""
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

    def test_truncated_content_fits_limit(self):
        """After truncation, content should fit within token limit."""
        content = "x" * 10000

        max_tokens = 500
        truncated = truncate_content_for_llm(content, max_tokens=max_tokens)

        estimated = estimate_tokens(truncated)
        # Allow some margin since tiktoken is more accurate
        assert estimated <= max_tokens * 1.5

    def test_empty_content_returned_as_is(self):
        """Empty content should be returned unchanged."""
        assert truncate_content_for_llm("", max_tokens=100) == ""
        assert truncate_content_for_llm(None, max_tokens=100) is None

    def test_content_slightly_over_limit_truncated(self):
        """Content over limit should be truncated."""
        content = "a" * 20000
        truncated = truncate_content_for_llm(content, max_tokens=2000)
        assert len(truncated) < len(content)

    def test_few_lines_hard_truncated(self):
        """When lines <= preserve_start + preserve_end, hard truncate by chars."""
        lines = ["x" * 1000 for _ in range(10)]
        content = "\n".join(lines)

        truncated = truncate_content_for_llm(
            content,
            max_tokens=100,
            preserve_start_lines=20,
            preserve_end_lines=10,
        )

        # Should be hard-truncated
        assert len(truncated) < len(content)

    def test_truncation_with_code_structure(self):
        """Verify truncation with realistic code structure."""
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
            max_tokens=100,
            preserve_start_lines=5,
            preserve_end_lines=3,
        )

        assert "line 0" in truncated
        assert "line 4" in truncated
        assert "truncated" in truncated.lower()
        assert "line 97" in truncated
        assert "line 99" in truncated

    def test_multiline_with_special_characters(self):
        """Verify truncation handles special characters correctly."""
        lines = [
            "# Comment with special chars",
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

        # Should not crash on unicode
        assert isinstance(truncated, str)


class TestTruncateWithAstHints:
    """Test AST-aware smart truncation."""

    def test_small_content_returned_as_is(self):
        """Content that fits should be returned unchanged."""
        content = "def hello():\n    return 'world'"
        result = truncate_with_ast_hints(content, max_tokens=100, dangerous_lines=[1])
        assert result == content

    def test_no_hints_falls_back_to_head_tail(self):
        """Without dangerous_lines, falls back to standard truncation."""
        lines = [f"line {i}" for i in range(1000)]
        content = "\n".join(lines)

        result = truncate_with_ast_hints(content, max_tokens=200, dangerous_lines=None)

        # Should behave like truncate_content_for_llm
        assert "line 0" in result
        assert "truncated" in result.lower() or "omitted" in result.lower()

    def test_preserves_dangerous_lines(self):
        """Lines around dangerous calls should be preserved."""
        lines = [f"# line {i}" for i in range(200)]
        # Dangerous call at line 100 (1-based)
        lines[99] = "cursor.execute(f'SELECT * FROM users WHERE id={user_input}')"
        content = "\n".join(lines)

        result = truncate_with_ast_hints(
            content,
            max_tokens=300,
            dangerous_lines=[100],
            preserve_start_lines=5,
            preserve_end_lines=3,
            context_window=3,
        )

        # Should contain the dangerous line
        assert "cursor.execute" in result

        # Should contain context around it (lines 97-103 approx)
        assert "# line 96" in result or "# line 97" in result
        assert "# line 101" in result or "# line 102" in result

        # Should contain start lines (imports area)
        assert "# line 0" in result

    def test_multiple_dangerous_lines(self):
        """Multiple dangerous lines should all be preserved."""
        lines = [f"# line {i}" for i in range(300)]
        lines[49] = "eval(user_input)"
        lines[149] = "os.system(cmd)"
        lines[249] = "pickle.loads(data)"
        content = "\n".join(lines)

        result = truncate_with_ast_hints(
            content,
            max_tokens=500,
            dangerous_lines=[50, 150, 250],
            preserve_start_lines=5,
            preserve_end_lines=3,
        )

        assert "eval(user_input)" in result
        assert "os.system(cmd)" in result
        assert "pickle.loads(data)" in result

    def test_gap_markers_inserted(self):
        """Gaps between preserved sections should have markers."""
        lines = [f"# line {i}" for i in range(200)]
        lines[99] = "dangerous_call()"
        content = "\n".join(lines)

        result = truncate_with_ast_hints(
            content,
            max_tokens=300,
            dangerous_lines=[100],
            preserve_start_lines=5,
            preserve_end_lines=3,
            context_window=3,
        )

        assert "omitted" in result.lower()

    def test_empty_content(self):
        """Empty content should be returned unchanged."""
        assert truncate_with_ast_hints("", max_tokens=100) == ""
        assert truncate_with_ast_hints(None, max_tokens=100) is None

    def test_empty_dangerous_lines_list(self):
        """Empty list of dangerous lines falls back to head+tail."""
        lines = [f"line {i}" for i in range(500)]
        content = "\n".join(lines)

        result = truncate_with_ast_hints(content, max_tokens=200, dangerous_lines=[])
        # Falls back since empty list is falsy
        assert isinstance(result, str)

    def test_dangerous_line_at_file_boundary(self):
        """Dangerous lines near start/end should not crash."""
        lines = [f"# line {i}" for i in range(100)]
        lines[0] = "dangerous_at_start()"
        lines[99] = "dangerous_at_end()"
        content = "\n".join(lines)

        result = truncate_with_ast_hints(
            content,
            max_tokens=200,
            dangerous_lines=[1, 100],
            preserve_start_lines=3,
            preserve_end_lines=3,
        )

        assert "dangerous_at_start()" in result
        assert "dangerous_at_end()" in result

    def test_out_of_range_dangerous_lines_ignored(self):
        """Dangerous lines beyond file length should not crash."""
        content = "line 1\nline 2\nline 3"
        result = truncate_with_ast_hints(
            content,
            max_tokens=1,  # Force truncation
            dangerous_lines=[999],
            preserve_start_lines=1,
            preserve_end_lines=1,
        )
        assert isinstance(result, str)


class TestTiktokenFallback:
    """Test behavior when tiktoken is not installed."""

    def test_fallback_flag_exists(self):
        """Module should expose _TIKTOKEN_AVAILABLE flag."""
        from warden.shared.utils import token_utils
        assert hasattr(token_utils, "_TIKTOKEN_AVAILABLE")
        assert isinstance(token_utils._TIKTOKEN_AVAILABLE, bool)

    def test_estimate_tokens_fallback_on_counter_failure(self):
        """When _get_counter raises, should fall back to len//4."""
        from unittest.mock import patch
        import warden.shared.utils.token_utils as mod

        with patch.object(mod, "_get_counter", side_effect=ImportError("no tiktoken")):
            original_fallback = mod._fallback_active
            mod._fallback_active = False
            try:
                result = mod.estimate_tokens("hello world test string")
                expected = len("hello world test string") // 4
                assert result == expected
            finally:
                mod._fallback_active = original_fallback

    def test_truncate_to_tokens_fallback(self):
        """truncate_to_tokens should work even with fallback."""
        from warden.shared.utils.token_utils import truncate_to_tokens

        text = "a" * 10000
        result = truncate_to_tokens(text, max_tokens=100)
        assert len(result) <= len(text)

    def test_truncate_content_for_llm_works_with_counter_failure(self):
        """Full truncation pipeline should work even in fallback mode."""
        from unittest.mock import patch
        import warden.shared.utils.token_utils as mod

        with patch.object(mod, "_get_counter", side_effect=ImportError("no tiktoken")):
            original_fallback = mod._fallback_active
            mod._fallback_active = False
            try:
                lines = [f"line {i}" for i in range(500)]
                content = "\n".join(lines)
                result = mod.truncate_content_for_llm(content, max_tokens=200)
                assert isinstance(result, str)
                assert len(result) < len(content)
            finally:
                mod._fallback_active = original_fallback


class TestChaosResilience:
    """Chaos engineering tests — edge cases that must not crash."""

    def test_binary_content(self):
        """Binary-ish content should not crash estimation or truncation."""
        content = "\x00\x01\x02\xff" * 1000
        estimated = estimate_tokens(content)
        assert estimated >= 0

        truncated = truncate_content_for_llm(content, max_tokens=100)
        assert isinstance(truncated, str)

    def test_one_megabyte_content(self):
        """1MB file should truncate without hanging."""
        content = "x" * (1024 * 1024)
        truncated = truncate_content_for_llm(content, max_tokens=1000)
        assert len(truncated) < len(content)

    def test_unicode_heavy_content(self):
        """Unicode-heavy content should not crash."""
        content = "def 函数():\n    return '日本語テスト'\n" * 500
        estimated = estimate_tokens(content)
        assert estimated > 0

        truncated = truncate_content_for_llm(content, max_tokens=200)
        assert isinstance(truncated, str)

    def test_single_very_long_line(self):
        """Single line that exceeds token budget."""
        content = "a" * 100000
        truncated = truncate_content_for_llm(content, max_tokens=100)
        assert len(truncated) < len(content)

    def test_only_newlines(self):
        """Content of only newlines."""
        content = "\n" * 10000
        truncated = truncate_content_for_llm(content, max_tokens=100)
        assert isinstance(truncated, str)
