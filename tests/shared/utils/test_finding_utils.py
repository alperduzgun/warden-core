"""
Tests for finding_utils — including LLM line-reference validation.

These tests cover:
- extract_finding_keywords: tokenisation and stop-word removal
- validate_llm_line_reference: core hallucination detection logic
- Pre-existing get_finding_attribute / set_finding_attribute / get_finding_severity
"""

import pytest

from warden.shared.utils.finding_utils import (
    extract_finding_keywords,
    get_finding_attribute,
    get_finding_severity,
    set_finding_attribute,
    validate_llm_line_reference,
)


# =============================================================================
# extract_finding_keywords
# =============================================================================


class TestExtractFindingKeywords:
    def test_returns_meaningful_tokens(self):
        keywords = extract_finding_keywords("disable_bundle_id_capability validation missing")
        assert "disable" in keywords
        assert "bundle" in keywords
        assert "capability" in keywords

    def test_strips_stop_words(self):
        keywords = extract_finding_keywords("missing input validation for the function")
        # Stop words that should be removed
        assert "the" not in keywords
        assert "for" not in keywords
        assert "missing" not in keywords
        assert "input" not in keywords
        assert "validation" not in keywords
        assert "function" not in keywords

    def test_strips_short_tokens(self):
        keywords = extract_finding_keywords("x is a bug")
        assert "x" not in keywords
        assert "is" not in keywords
        assert "a" not in keywords

    def test_lowercase_output(self):
        keywords = extract_finding_keywords("SQL Injection In UserLogin")
        assert all(k == k.lower() for k in keywords)

    def test_handles_empty_string(self):
        assert extract_finding_keywords("") == []

    def test_handles_all_stop_words(self):
        # All tokens are stop words or short — returns empty
        result = extract_finding_keywords("the and for with")
        assert result == []

    def test_splits_on_punctuation(self):
        keywords = extract_finding_keywords("sql-injection; xss_attack, buffer.overflow")
        assert "injection" in keywords
        assert "attack" in keywords
        assert "overflow" in keywords

    def test_real_finding_title(self):
        """Simulate a realistic LLM finding title."""
        title = "Incomplete Input Validation in disable_bundle_id_capability"
        keywords = extract_finding_keywords(title)
        assert "disable" in keywords
        assert "bundle" in keywords
        assert "capability" in keywords


# =============================================================================
# validate_llm_line_reference
# =============================================================================

_SAMPLE_CODE = """\
def create_user(name, email):
    if not name:
        raise ValueError("Name required")
    if not email:
        raise ValueError("Email required")
    return {"name": name, "email": email}


def disable_bundle_id_capability(bundle_id, capability):
    if not bundle_id:
        return {"error": "bundle_id required"}
    return {"bundle_id": bundle_id, "disabled": capability}


def helper():
    return {"status": "ok"}
"""


class TestValidateLlmLineReference:

    # ------------------------------------------------------------------
    # Basic correct references
    # ------------------------------------------------------------------

    def test_valid_reference_exact_line(self):
        """LLM reports line 9 which contains 'disable_bundle_id_capability'."""
        assert validate_llm_line_reference(
            finding_message="Incomplete Input Validation in disable_bundle_id_capability",
            finding_title="Missing capability validation",
            code_content=_SAMPLE_CODE,
            reported_line=9,
        ) is True

    def test_valid_reference_within_window(self):
        """Keyword is 3 lines away from reported line — should still pass."""
        assert validate_llm_line_reference(
            finding_message="disable_bundle_id_capability lacks checks",
            finding_title="Incomplete validation",
            code_content=_SAMPLE_CODE,
            reported_line=12,  # line 9 is the def, 12 is 3 lines away — within window
        ) is True

    def test_valid_reference_first_function(self):
        """Finding about create_user pointing to line 1 (def line)."""
        assert validate_llm_line_reference(
            finding_message="create_user lacks email format validation",
            finding_title="Missing email validation",
            code_content=_SAMPLE_CODE,
            reported_line=1,
        ) is True

    # ------------------------------------------------------------------
    # Hallucination detection
    # ------------------------------------------------------------------

    def test_hallucination_wrong_line(self):
        """LLM says line 16 (helper) has disable_bundle_id_capability issue.
        Line 16 is 'def helper():' — keywords like 'disable', 'bundle',
        'capability' are nowhere near it.
        """
        result = validate_llm_line_reference(
            finding_message="disable_bundle_id_capability incomplete input validation",
            finding_title="Incomplete Input Validation in disable_bundle_id_capability",
            code_content=_SAMPLE_CODE,
            reported_line=16,  # helper function — far from disable_bundle_id_capability
        )
        assert result is False

    def test_hallucination_dict_return_line(self):
        """Simulate the exact reported bug: LLM says a line far from the
        disable_bundle_id_capability definition has the issue.

        We use a large file where the function is near the top and the
        reported line is at the bottom (many blank lines in between) so the
        ±3 window cannot bridge the gap.
        """
        # Build a file where disable_bundle_id_capability is at line 1 and the
        # erroneously reported line is at line 20 (blank/unrelated code).
        lines = ["def disable_bundle_id_capability(bundle_id): pass"]
        lines += [""] * 15
        lines += ["def unrelated_function(): return 42"]  # line 17
        lines += [""]
        lines += ["x = unrelated_function()"]  # line 19
        code = "\n".join(lines)

        # Report line 19 ("x = unrelated_function()") for a finding about
        # disable_bundle_id_capability — clearly wrong.
        result = validate_llm_line_reference(
            finding_message="Incomplete Input Validation in disable_bundle_id_capability",
            finding_title="Incomplete Input Validation in disable_bundle_id_capability",
            code_content=code,
            reported_line=19,  # far from line 1 where the function is defined
        )
        assert result is False

    # ------------------------------------------------------------------
    # Fail-open edge cases
    # ------------------------------------------------------------------

    def test_out_of_range_line_returns_true(self):
        """Line beyond end of file — cannot validate, keep finding."""
        assert validate_llm_line_reference(
            finding_message="some issue",
            finding_title="Some Issue",
            code_content=_SAMPLE_CODE,
            reported_line=9999,
        ) is True

    def test_zero_line_returns_true(self):
        """Line 0 is out of range (1-based). Should pass through."""
        assert validate_llm_line_reference(
            finding_message="some issue",
            finding_title="Some Issue",
            code_content=_SAMPLE_CODE,
            reported_line=0,
        ) is True

    def test_negative_line_returns_true(self):
        assert validate_llm_line_reference(
            finding_message="some issue",
            finding_title="Some Issue",
            code_content=_SAMPLE_CODE,
            reported_line=-5,
        ) is True

    def test_empty_source_code_returns_true(self):
        """No source to validate against — keep finding."""
        assert validate_llm_line_reference(
            finding_message="some issue",
            finding_title="Some Issue",
            code_content="",
            reported_line=1,
        ) is True

    def test_no_keywords_returns_true(self):
        """When the finding message/title yields no keywords, return True."""
        assert validate_llm_line_reference(
            finding_message="the and for with",   # all stop words
            finding_title="",
            code_content=_SAMPLE_CODE,
            reported_line=5,
        ) is True

    def test_blank_window_returns_true(self):
        """File with only blank lines around the reported line."""
        blank_code = "\n\n\n\n\n"
        assert validate_llm_line_reference(
            finding_message="some_function missing validation",
            finding_title="Some Issue",
            code_content=blank_code,
            reported_line=3,
        ) is True

    # ------------------------------------------------------------------
    # Window size
    # ------------------------------------------------------------------

    def test_wider_window_finds_match(self):
        """With window=10 the keyword 7 lines away should match."""
        assert validate_llm_line_reference(
            finding_message="disable_bundle_id_capability issue",
            finding_title="Capability issue",
            code_content=_SAMPLE_CODE,
            reported_line=16,  # helper at line 16; with window=10 reaches line 9 def
            window=10,
        ) is True

    def test_narrow_window_misses_match(self):
        """With window=0 only the exact line is checked."""
        result = validate_llm_line_reference(
            finding_message="disable_bundle_id_capability incomplete validation",
            finding_title="Incomplete Validation",
            code_content=_SAMPLE_CODE,
            reported_line=16,  # helper — no match at exactly line 16 with window=0
            window=0,
        )
        assert result is False

    # ------------------------------------------------------------------
    # Single-line and minimal files
    # ------------------------------------------------------------------

    def test_single_line_file_matching(self):
        """Keyword from the finding appears in the single-line source."""
        code = "def authenticate_user(username, password): pass"
        # "authenticate" is a meaningful keyword that appears in the code
        assert validate_llm_line_reference(
            finding_message="authenticate_user missing password strength check",
            finding_title="Weak authentication",
            code_content=code,
            reported_line=1,
        ) is True

    def test_single_line_file_no_match(self):
        """Finding keywords are completely absent from the single-line source."""
        code = "x = 1 + 2"
        result = validate_llm_line_reference(
            finding_message="authenticate_user missing auth check",
            finding_title="Missing authentication",
            code_content=code,
            reported_line=1,
        )
        assert result is False


# =============================================================================
# Pre-existing utility functions — regression tests
# =============================================================================


class TestGetFindingAttribute:
    def test_dict_access(self):
        finding = {"severity": "high", "message": "test"}
        assert get_finding_attribute(finding, "severity") == "high"

    def test_dict_missing_key_returns_default(self):
        finding = {"severity": "high"}
        assert get_finding_attribute(finding, "message", "default") == "default"

    def test_object_access(self):
        class MockFinding:
            severity = "medium"

        assert get_finding_attribute(MockFinding(), "severity") == "medium"

    def test_none_finding_returns_default(self):
        assert get_finding_attribute(None, "severity", "low") == "low"


class TestSetFindingAttribute:
    def test_dict_set(self):
        finding = {}
        set_finding_attribute(finding, "severity", "high")
        assert finding["severity"] == "high"

    def test_object_set(self):
        class MockFinding:
            severity = "low"

        f = MockFinding()
        set_finding_attribute(f, "severity", "high")
        assert f.severity == "high"

    def test_none_is_safe(self):
        # Should not raise
        set_finding_attribute(None, "severity", "high")


class TestGetFindingSeverity:
    def test_known_severity(self):
        assert get_finding_severity({"severity": "high"}) == "high"

    def test_unknown_severity_maps_to_low(self):
        assert get_finding_severity({"severity": "unknown"}) == "low"

    def test_missing_severity_defaults_to_medium_then_low(self):
        # default from get_finding_attribute is "medium", which is in _KNOWN_SEVERITIES
        assert get_finding_severity({}) == "medium"
