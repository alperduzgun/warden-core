"""
Tests for warden.shared.utils.quality_calculator

Covers:
1. calculate_quality_score — asymptotic decay formula
2. calculate_base_score — linter-metrics-based objective baseline
3. Edge cases: empty inputs, zero values, mixed object/dict formats
"""

import pytest

from warden.shared.utils.quality_calculator import (
    calculate_base_score,
    calculate_quality_score,
)


# ---------------------------------------------------------------------------
# calculate_quality_score
# ---------------------------------------------------------------------------


class TestCalculateQualityScore:
    """Asymptotic decay quality scoring."""

    def test_no_findings_returns_base(self):
        assert calculate_quality_score([], 10.0) == 10.0

    def test_no_findings_custom_base(self):
        assert calculate_quality_score([], 7.5) == 7.5

    def test_critical_findings_penalize_heavily(self):
        findings = [_make_finding("critical")]
        score = calculate_quality_score(findings, 10.0)
        # 1 critical = penalty 3.0 → 10 * (20 / 23) ≈ 8.7
        assert 8.0 < score < 9.0

    def test_many_findings_never_reach_zero(self):
        """Asymptotic formula guarantees score > 0."""
        findings = [_make_finding("critical") for _ in range(100)]
        score = calculate_quality_score(findings, 10.0)
        assert score >= 0.1

    def test_score_monotonically_decreases(self):
        """More findings → lower score."""
        s1 = calculate_quality_score([_make_finding("high")], 10.0)
        s2 = calculate_quality_score([_make_finding("high")] * 5, 10.0)
        s3 = calculate_quality_score([_make_finding("high")] * 20, 10.0)
        assert s1 > s2 > s3

    def test_severity_ordering(self):
        """critical > high > medium > low penalty."""
        sc = calculate_quality_score([_make_finding("critical")], 10.0)
        sh = calculate_quality_score([_make_finding("high")], 10.0)
        sm = calculate_quality_score([_make_finding("medium")], 10.0)
        sl = calculate_quality_score([_make_finding("low")], 10.0)
        assert sc < sh < sm < sl


# ---------------------------------------------------------------------------
# calculate_base_score
# ---------------------------------------------------------------------------


class TestCalculateBaseScore:
    """Linter-metrics-based objective baseline."""

    def test_none_returns_10(self):
        assert calculate_base_score(None) == 10.0

    def test_empty_dict_returns_10(self):
        assert calculate_base_score({}) == 10.0

    def test_unavailable_tool_ignored(self):
        """Tools that aren't available must not affect score."""
        metrics = {"ruff": _make_linter_result(is_available=False, blockers=100, errors=500)}
        assert calculate_base_score(metrics) == 10.0

    def test_blockers_penalize_more_than_errors(self):
        """Blockers have 10x the weight of regular errors."""
        blockers_only = {"ruff": _make_linter_result(blockers=10, errors=0)}
        errors_only = {"ruff": _make_linter_result(blockers=0, errors=100)}
        # 10 blockers * 0.5 = 5.0 penalty → 10 * 20/25 = 8.0
        # 100 errors * 0.05 = 5.0 penalty → same
        assert calculate_base_score(blockers_only) == calculate_base_score(errors_only)

    def test_high_penalty_degrades_gracefully(self):
        """Asymptotic formula: score > 0 even with extreme errors."""
        extreme = {"ruff": _make_linter_result(blockers=1000, errors=10000)}
        score = calculate_base_score(extreme)
        assert score >= 0.1
        assert score < 2.0  # Should be quite low

    def test_zero_errors_gives_perfect_score(self):
        metrics = {"ruff": _make_linter_result(blockers=0, errors=0)}
        assert calculate_base_score(metrics) == 10.0

    def test_multiple_tools_accumulate(self):
        """Penalties from multiple tools stack."""
        one_tool = {"ruff": _make_linter_result(blockers=5, errors=0)}
        two_tools = {
            "ruff": _make_linter_result(blockers=5, errors=0),
            "mypy": _make_linter_result(blockers=5, errors=0),
        }
        assert calculate_base_score(two_tools) < calculate_base_score(one_tool)

    def test_dict_format_metrics(self):
        """Supports plain dict format (resilience)."""
        metrics = {
            "ruff": {"is_available": True, "blocker_count": 2, "total_errors": 10},
        }
        score = calculate_base_score(metrics)
        # penalty = 2*0.5 + 10*0.05 = 1.5 → 10 * 20/21.5 ≈ 9.3
        assert 9.0 < score < 9.5

    def test_dict_format_unavailable_ignored(self):
        metrics = {
            "ruff": {"is_available": False, "blocker_count": 100, "total_errors": 500},
        }
        assert calculate_base_score(metrics) == 10.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeFinding:
    """Minimal finding stub."""

    def __init__(self, severity: str):
        self.severity = severity


class _FakeLinterResult:
    """Minimal linter result stub."""

    def __init__(self, is_available: bool, blocker_count: int, total_errors: int):
        self.is_available = is_available
        self.blocker_count = blocker_count
        self.total_errors = total_errors


def _make_finding(severity: str = "medium") -> _FakeFinding:
    return _FakeFinding(severity=severity)


def _make_linter_result(
    blockers: int = 0,
    errors: int = 0,
    is_available: bool = True,
) -> _FakeLinterResult:
    return _FakeLinterResult(
        is_available=is_available,
        blocker_count=blockers,
        total_errors=errors,
    )
