"""
LLM Performance Metrics Tracking

Collects and aggregates metrics for LLM requests across tiers.
Supports per-frame cost attribution via context-based scoping.
"""

import threading
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime

_global_metrics_collector = None

# Context variable for automatic frame attribution
_current_frame_scope: ContextVar[str | None] = ContextVar("_current_frame_scope", default=None)


def get_global_metrics_collector():
    """Get the global LLM metrics collector singleton."""
    global _global_metrics_collector
    if _global_metrics_collector is None:
        _global_metrics_collector = LLMMetricsCollector()
    return _global_metrics_collector


@dataclass
class LLMRequestMetrics:
    """Metrics for a single LLM request."""

    tier: str  # "fast" or "smart"
    provider: str  # "ollama", "azure_openai", etc.
    model: str
    success: bool
    duration_ms: int
    error: str | None = None
    timestamp: datetime = field(default_factory=datetime.now)
    frame_name: str = "_unattributed"
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class FrameMetrics:
    """Per-frame LLM usage metrics."""

    frame_name: str
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    total_duration_ms: int = 0
    errors: int = 0


@dataclass
class LLMMetricsCollector:
    """Collects and aggregates LLM metrics."""

    requests: list[LLMRequestMetrics] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    @contextmanager
    def frame_scope(self, frame_name: str):
        """Context manager for attributing LLM calls to a specific frame."""
        token = _current_frame_scope.set(frame_name)
        try:
            yield
        finally:
            _current_frame_scope.reset(token)

    def record_request(
        self,
        tier: str,
        provider: str,
        model: str,
        success: bool,
        duration_ms: int,
        error: str | None = None,
        frame_name: str | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ):
        """Record a single LLM request with optional frame attribution."""
        # Auto-detect frame from context if not explicitly provided
        effective_frame = frame_name or _current_frame_scope.get(None) or "_unattributed"

        with self._lock:
            self.requests.append(
                LLMRequestMetrics(
                    tier=tier,
                    provider=provider,
                    model=model,
                    success=success,
                    duration_ms=duration_ms,
                    error=error,
                    frame_name=effective_frame,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )
            )

    def get_frame_metrics(self) -> list[FrameMetrics]:
        """Get per-frame metrics breakdown."""
        frame_data: dict[str, FrameMetrics] = {}

        with self._lock:
            for req in self.requests:
                name = req.frame_name
                if name not in frame_data:
                    frame_data[name] = FrameMetrics(frame_name=name)
                fm = frame_data[name]
                fm.llm_calls += 1
                fm.input_tokens += req.input_tokens
                fm.output_tokens += req.output_tokens
                fm.total_duration_ms += req.duration_ms
                fm.estimated_cost_usd += self._estimate_cost(req.input_tokens, req.output_tokens, req.model)
                if not req.success:
                    fm.errors += 1

        return sorted(frame_data.values(), key=lambda m: m.estimated_cost_usd, reverse=True)

    @staticmethod
    def _estimate_cost(input_tokens: int, output_tokens: int, model: str) -> float:
        """Estimate USD cost based on model pricing."""
        # Approximate pricing per 1K tokens
        pricing = {
            "gpt-4": (0.03, 0.06),
            "gpt-4o": (0.005, 0.015),
            "gpt-3.5-turbo": (0.0005, 0.0015),
        }
        # Default pricing for unknown models
        input_rate, output_rate = pricing.get(model, (0.001, 0.002))
        return (input_tokens / 1000 * input_rate) + (output_tokens / 1000 * output_rate)

    def get_summary(self) -> dict:
        """Generate summary statistics."""
        if not self.requests:
            return {}

        with self._lock:
            requests_snapshot = list(self.requests)

        fast_requests = [r for r in requests_snapshot if r.tier == "fast"]
        smart_requests = [r for r in requests_snapshot if r.tier == "smart"]

        total_time_ms = sum(r.duration_ms for r in requests_snapshot)

        summary = {"totalRequests": len(requests_snapshot), "totalTime": self._format_duration(total_time_ms)}

        if fast_requests:
            summary["fastTier"] = self._tier_stats(fast_requests, requests_snapshot)

        if smart_requests:
            summary["smartTier"] = self._tier_stats(smart_requests, requests_snapshot)

        if fast_requests and smart_requests:
            summary["costAnalysis"] = self._cost_analysis(fast_requests, smart_requests)

        issues = self._detect_issues(requests_snapshot)
        if issues:
            summary["issues"] = issues

        return summary

    def _tier_stats(
        self, requests: list[LLMRequestMetrics], all_requests: list[LLMRequestMetrics] | None = None
    ) -> dict:
        """Calculate statistics for a tier."""
        if not requests:
            return None

        if all_requests is None:
            all_requests = self.requests

        successful = [r for r in requests if r.success]
        # Group by provider for clearer insights
        providers = sorted({r.provider for r in requests})

        total_time_ms = sum(r.duration_ms for r in requests)
        total_scan_time_ms = sum(r.duration_ms for r in all_requests)

        return {
            "providers": providers,
            "provider": requests[-1].provider,  # Show latest
            "model": requests[-1].model,
            "requests": len(requests),
            "percentage": round(len(requests) / len(all_requests) * 100, 1),
            "successRate": round(len(successful) / len(requests) * 100, 1) if requests else 0,
            "timeouts": len([r for r in requests if not r.success and "timeout" in (r.error or "").lower()]),
            "avgResponseTime": f"{sum(r.duration_ms for r in successful) / len(successful) / 1000:.1f}s"
            if successful
            else "N/A",
            "totalTime": self._format_duration(total_time_ms),
            "timePercentage": round(total_time_ms / total_scan_time_ms * 100, 1) if total_scan_time_ms > 0 else 0,
        }

    def _format_duration(self, ms: int) -> str:
        """Format milliseconds to human-readable duration."""
        seconds = ms / 1000
        if seconds < 60:
            return f"{seconds:.1f}s"
        elif seconds < 3600:
            minutes = int(seconds // 60)
            secs = int(seconds % 60)
            return f"{minutes}m {secs}s"
        else:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            secs = int(seconds % 60)
            return f"{hours}h {minutes}m {secs}s"

    def _cost_analysis(self, fast_requests: list, smart_requests: list) -> dict:
        """Calculate cost and time savings."""
        COST_PER_SMART_REQUEST = 0.05  # $0.05 per request estimate

        # Cost savings
        cost_savings = len(fast_requests) * COST_PER_SMART_REQUEST

        # Time savings
        fast_successful = [r for r in fast_requests if r.success]
        smart_successful = [r for r in smart_requests if r.success]

        if fast_successful and smart_successful:
            fast_avg = sum(r.duration_ms for r in fast_successful) / len(fast_successful)
            smart_avg = sum(r.duration_ms for r in smart_successful) / len(smart_successful)
            time_saved_ms = len(fast_requests) * (smart_avg - fast_avg)
        else:
            time_saved_ms = 0
            fast_avg = 0
            smart_avg = 0

        return {
            "estimatedCostSavings": f"${cost_savings:.2f}",
            "estimatedTimeSavings": self._format_duration(int(time_saved_ms)) if time_saved_ms > 0 else "0s",
            "fastTierRequests": len(fast_requests),
            "explanation": {
                "cost": f"{len(fast_requests)} requests x ${COST_PER_SMART_REQUEST} = ${cost_savings:.2f} saved",
                "time": f"{len(fast_requests)} requests x ({smart_avg / 1000:.1f}s - {fast_avg / 1000:.1f}s) = {self._format_duration(int(time_saved_ms))} saved"
                if time_saved_ms > 0
                else "No time savings",
            },
        }

    def _detect_issues(self, requests_snapshot: list[LLMRequestMetrics] | None = None) -> list[dict]:
        """Detect performance issues."""
        issues = []

        if requests_snapshot is None:
            requests_snapshot = self.requests

        fast_requests = [r for r in requests_snapshot if r.tier == "fast"]
        if fast_requests:
            failed = [r for r in fast_requests if not r.success]
            failure_rate = len(failed) / len(fast_requests)

            if failure_rate > 0.1:  # >10% failure rate
                providers = list({r.provider for r in failed})
                issues.append(
                    {
                        "type": "reliability",
                        "tier": "fast",
                        "count": len(failed),
                        "severity": "warning",
                        "message": f"{len(failed)} fast tier requests ({', '.join(providers)}) failed or timed out",
                        "recommendations": [
                            "Check local service (Ollama) health",
                            "Increase fast tier timeout",
                            "Verify Groq/Cloud failover status",
                        ],
                    }
                )

        # Rate limit detection (across all tiers)
        rate_limited = [r for r in requests_snapshot if not r.success and "rate limit" in (r.error or "").lower()]
        if rate_limited:
            providers = sorted({r.provider for r in rate_limited})
            issues.append(
                {
                    "type": "rate_limit",
                    "severity": "error",
                    "count": len(rate_limited),
                    "message": f"Provider rate limit hit ({', '.join(providers)}): {len(rate_limited)} requests blocked",
                    "recommendations": [
                        "Check provider quota/subscription status",
                        "Switch to a different provider: WARDEN_LLM_PROVIDER=groq",
                        "Use local model: WARDEN_LLM_PROVIDER=ollama",
                    ],
                }
            )

        return issues
