"""Tests for HealingMetricsCollector."""

from __future__ import annotations

from warden.self_healing.metrics import HealingMetricsCollector
from warden.self_healing.models import DiagnosticResult, ErrorCategory


class TestMetricsCollector:
    def test_record_attempt(self):
        m = HealingMetricsCollector()
        m.record_attempt(ErrorCategory.IMPORT_ERROR)
        m.record_attempt(ErrorCategory.IMPORT_ERROR)
        m.record_attempt(ErrorCategory.TIMEOUT)
        metrics = m.get_metrics()
        assert metrics.total_attempts == 3
        assert metrics.by_category["import_error"] == 2
        assert metrics.by_category["timeout"] == 1

    def test_record_result_fixed(self):
        m = HealingMetricsCollector()
        result = DiagnosticResult(fixed=True, strategy_used="import_healer", duration_ms=50)
        m.record_result(result)
        metrics = m.get_metrics()
        assert metrics.total_fixed == 1
        assert metrics.total_failed == 0
        assert metrics.by_strategy["import_healer"] == 1
        assert metrics.total_duration_ms == 50

    def test_record_result_failed(self):
        m = HealingMetricsCollector()
        result = DiagnosticResult(fixed=False, strategy_used="llm_healer", duration_ms=100)
        m.record_result(result)
        metrics = m.get_metrics()
        assert metrics.total_fixed == 0
        assert metrics.total_failed == 1

    def test_success_rate(self):
        m = HealingMetricsCollector()
        m.record_attempt(ErrorCategory.UNKNOWN)
        m.record_result(DiagnosticResult(fixed=True, duration_ms=10))
        m.record_attempt(ErrorCategory.UNKNOWN)
        m.record_result(DiagnosticResult(fixed=False, duration_ms=20))
        m.record_attempt(ErrorCategory.UNKNOWN)
        m.record_result(DiagnosticResult(fixed=True, duration_ms=30))
        assert m.get_metrics().success_rate == pytest.approx(2 / 3, abs=0.01)

    def test_success_rate_zero_attempts(self):
        m = HealingMetricsCollector()
        assert m.get_metrics().success_rate == 0.0

    def test_cache_hit_miss(self):
        m = HealingMetricsCollector()
        m.record_cache_hit()
        m.record_cache_hit()
        m.record_cache_miss()
        metrics = m.get_metrics()
        assert metrics.cache_hits == 2
        assert metrics.cache_misses == 1

    def test_timer(self):
        m = HealingMetricsCollector()
        m.start_timer("test")
        elapsed = m.stop_timer("test")
        assert elapsed >= 0

    def test_timer_not_started(self):
        m = HealingMetricsCollector()
        assert m.stop_timer("nonexistent") == 0

    def test_reset(self):
        m = HealingMetricsCollector()
        m.record_attempt(ErrorCategory.UNKNOWN)
        m.record_result(DiagnosticResult(fixed=True))
        m.reset()
        metrics = m.get_metrics()
        assert metrics.total_attempts == 0
        assert metrics.total_fixed == 0

    def test_to_dict(self):
        m = HealingMetricsCollector()
        m.record_attempt(ErrorCategory.IMPORT_ERROR)
        m.record_result(DiagnosticResult(fixed=True, strategy_used="import_healer", duration_ms=42))
        d = m.get_metrics().to_dict()
        assert d["total_attempts"] == 1
        assert d["total_fixed"] == 1
        assert "success_rate" in d


import pytest  # noqa: E402
