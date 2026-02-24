"""Tests for per-frame metrics tracking."""

import asyncio
import pytest
from warden.llm.metrics import LLMMetricsCollector, FrameMetrics, _current_frame_scope


class TestFrameScope:
    def test_frame_scope_attribution(self):
        collector = LLMMetricsCollector()
        with collector.frame_scope("security"):
            collector.record_request(
                tier="fast",
                provider="ollama",
                model="qwen",
                success=True,
                duration_ms=100,
                input_tokens=50,
                output_tokens=30,
            )

        metrics = collector.get_frame_metrics()
        assert len(metrics) == 1
        assert metrics[0].frame_name == "security"
        assert metrics[0].llm_calls == 1
        assert metrics[0].input_tokens == 50

    def test_unattributed(self):
        collector = LLMMetricsCollector()
        collector.record_request(
            tier="smart",
            provider="azure",
            model="gpt-4",
            success=True,
            duration_ms=200,
            input_tokens=100,
            output_tokens=50,
        )

        metrics = collector.get_frame_metrics()
        assert metrics[0].frame_name == "_unattributed"

    def test_cost_estimation(self):
        collector = LLMMetricsCollector()
        collector.record_request(
            tier="smart",
            provider="azure",
            model="gpt-4",
            success=True,
            duration_ms=200,
            input_tokens=1000,
            output_tokens=500,
        )

        metrics = collector.get_frame_metrics()
        assert metrics[0].estimated_cost_usd > 0

    def test_backward_compat_summary(self):
        """Existing get_summary() should still work."""
        collector = LLMMetricsCollector()
        collector.record_request(tier="fast", provider="ollama", model="qwen", success=True, duration_ms=100)
        summary = collector.get_summary()
        assert summary["totalRequests"] == 1

    def test_multiple_frames(self):
        collector = LLMMetricsCollector()
        with collector.frame_scope("security"):
            collector.record_request(
                tier="fast",
                provider="ollama",
                model="q",
                success=True,
                duration_ms=100,
                input_tokens=50,
                output_tokens=30,
            )
        with collector.frame_scope("resilience"):
            collector.record_request(
                tier="fast",
                provider="ollama",
                model="q",
                success=True,
                duration_ms=200,
                input_tokens=100,
                output_tokens=60,
            )

        metrics = collector.get_frame_metrics()
        assert len(metrics) == 2
        names = {m.frame_name for m in metrics}
        assert names == {"security", "resilience"}

    def test_error_tracking(self):
        collector = LLMMetricsCollector()
        with collector.frame_scope("security"):
            collector.record_request(
                tier="fast", provider="ollama", model="q", success=False, duration_ms=100, error="timeout"
            )

        metrics = collector.get_frame_metrics()
        assert metrics[0].errors == 1

    def test_explicit_frame_name_overrides_scope(self):
        """Explicit frame_name parameter should override context scope."""
        collector = LLMMetricsCollector()
        with collector.frame_scope("security"):
            collector.record_request(
                tier="fast", provider="ollama", model="q", success=True, duration_ms=100, frame_name="explicit_frame"
            )

        metrics = collector.get_frame_metrics()
        assert len(metrics) == 1
        assert metrics[0].frame_name == "explicit_frame"

    def test_cost_estimation_gpt4(self):
        """Verify GPT-4 cost estimation with known pricing."""
        cost = LLMMetricsCollector._estimate_cost(1000, 500, "gpt-4")
        # GPT-4: input=$0.03/1K, output=$0.06/1K
        # (1000/1000 * 0.03) + (500/1000 * 0.06) = 0.03 + 0.03 = 0.06
        assert abs(cost - 0.06) < 0.0001

    def test_cost_estimation_unknown_model(self):
        """Unknown models should use default pricing."""
        cost = LLMMetricsCollector._estimate_cost(1000, 500, "some-local-model")
        # Default: input=$0.001/1K, output=$0.002/1K
        # (1000/1000 * 0.001) + (500/1000 * 0.002) = 0.001 + 0.001 = 0.002
        assert abs(cost - 0.002) < 0.0001

    def test_frame_metrics_sorted_by_cost(self):
        """Frame metrics should be sorted by estimated cost descending."""
        collector = LLMMetricsCollector()
        with collector.frame_scope("cheap_frame"):
            collector.record_request(
                tier="fast",
                provider="ollama",
                model="q",
                success=True,
                duration_ms=100,
                input_tokens=10,
                output_tokens=5,
            )
        with collector.frame_scope("expensive_frame"):
            collector.record_request(
                tier="smart",
                provider="azure",
                model="gpt-4",
                success=True,
                duration_ms=500,
                input_tokens=5000,
                output_tokens=2000,
            )

        metrics = collector.get_frame_metrics()
        assert len(metrics) == 2
        assert metrics[0].frame_name == "expensive_frame"
        assert metrics[1].frame_name == "cheap_frame"

    def test_multiple_requests_same_frame(self):
        """Multiple requests in the same frame should aggregate correctly."""
        collector = LLMMetricsCollector()
        with collector.frame_scope("security"):
            collector.record_request(
                tier="fast",
                provider="ollama",
                model="q",
                success=True,
                duration_ms=100,
                input_tokens=50,
                output_tokens=30,
            )
            collector.record_request(
                tier="fast",
                provider="ollama",
                model="q",
                success=True,
                duration_ms=200,
                input_tokens=100,
                output_tokens=60,
            )

        metrics = collector.get_frame_metrics()
        assert len(metrics) == 1
        assert metrics[0].llm_calls == 2
        assert metrics[0].input_tokens == 150
        assert metrics[0].output_tokens == 90
        assert metrics[0].total_duration_ms == 300

    def test_empty_collector_returns_empty_metrics(self):
        """Empty collector should return empty frame metrics list."""
        collector = LLMMetricsCollector()
        metrics = collector.get_frame_metrics()
        assert metrics == []

    def test_context_var_cleanup(self):
        """Context variable should be properly cleaned up after scope exits."""
        collector = LLMMetricsCollector()
        with collector.frame_scope("security"):
            pass
        # After exiting scope, recording should be unattributed
        collector.record_request(tier="fast", provider="ollama", model="q", success=True, duration_ms=100)
        metrics = collector.get_frame_metrics()
        assert len(metrics) == 1
        assert metrics[0].frame_name == "_unattributed"
