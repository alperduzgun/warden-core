"""Healing metrics collector for tracking success/failure rates."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from warden.self_healing.models import DiagnosticResult, ErrorCategory


@dataclass
class HealingMetrics:
    """Aggregated metrics from healing attempts."""

    total_attempts: int = 0
    total_fixed: int = 0
    total_failed: int = 0
    by_category: dict[str, int] = field(default_factory=dict)
    by_strategy: dict[str, int] = field(default_factory=dict)
    total_duration_ms: int = 0
    cache_hits: int = 0
    cache_misses: int = 0

    @property
    def success_rate(self) -> float:
        if self.total_attempts == 0:
            return 0.0
        return self.total_fixed / self.total_attempts

    def to_dict(self) -> dict:
        return {
            "total_attempts": self.total_attempts,
            "total_fixed": self.total_fixed,
            "total_failed": self.total_failed,
            "success_rate": round(self.success_rate, 3),
            "by_category": self.by_category,
            "by_strategy": self.by_strategy,
            "total_duration_ms": self.total_duration_ms,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
        }


class HealingMetricsCollector:
    """Collects metrics from healing attempts."""

    def __init__(self) -> None:
        self._metrics = HealingMetrics()
        self._start_times: dict[str, float] = {}

    def record_attempt(self, category: ErrorCategory) -> None:
        self._metrics.total_attempts += 1
        cat_key = category.value
        self._metrics.by_category[cat_key] = self._metrics.by_category.get(cat_key, 0) + 1

    def record_result(self, result: DiagnosticResult) -> None:
        if result.fixed:
            self._metrics.total_fixed += 1
        else:
            self._metrics.total_failed += 1

        if result.strategy_used:
            self._metrics.by_strategy[result.strategy_used] = (
                self._metrics.by_strategy.get(result.strategy_used, 0) + 1
            )

        self._metrics.total_duration_ms += result.duration_ms

    def record_cache_hit(self) -> None:
        self._metrics.cache_hits += 1

    def record_cache_miss(self) -> None:
        self._metrics.cache_misses += 1

    def start_timer(self, key: str) -> None:
        self._start_times[key] = time.monotonic()

    def stop_timer(self, key: str) -> int:
        """Stop timer and return elapsed ms."""
        start = self._start_times.pop(key, None)
        if start is None:
            return 0
        return int((time.monotonic() - start) * 1000)

    def get_metrics(self) -> HealingMetrics:
        return self._metrics

    def reset(self) -> None:
        self._metrics = HealingMetrics()
        self._start_times.clear()
