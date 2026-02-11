"""
LLM Performance Metrics Tracking

Collects and aggregates metrics for LLM requests across tiers.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

_global_metrics_collector = None

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


@dataclass
class LLMMetricsCollector:
    """Collects and aggregates LLM metrics."""
    requests: list[LLMRequestMetrics] = field(default_factory=list)

    def record_request(
        self,
        tier: str,
        provider: str,
        model: str,
        success: bool,
        duration_ms: int,
        error: str | None = None
    ):
        """Record a single LLM request."""
        self.requests.append(LLMRequestMetrics(
            tier=tier,
            provider=provider,
            model=model,
            success=success,
            duration_ms=duration_ms,
            error=error
        ))

    def get_summary(self) -> dict:
        """Generate summary statistics."""
        if not self.requests:
            return {}

        fast_requests = [r for r in self.requests if r.tier == "fast"]
        smart_requests = [r for r in self.requests if r.tier == "smart"]

        total_time_ms = sum(r.duration_ms for r in self.requests)

        summary = {
            "totalRequests": len(self.requests),
            "totalTime": self._format_duration(total_time_ms)
        }

        if fast_requests:
            summary["fastTier"] = self._tier_stats(fast_requests)

        if smart_requests:
            summary["smartTier"] = self._tier_stats(smart_requests)

        if fast_requests and smart_requests:
            summary["costAnalysis"] = self._cost_analysis(fast_requests, smart_requests)

        issues = self._detect_issues()
        if issues:
            summary["issues"] = issues

        return summary

    def _tier_stats(self, requests: list[LLMRequestMetrics]) -> dict:
        """Calculate statistics for a tier."""
        if not requests:
            return None

        successful = [r for r in requests if r.success]
        # Group by provider for clearer insights
        providers = sorted({r.provider for r in requests})

        total_time_ms = sum(r.duration_ms for r in requests)
        total_scan_time_ms = sum(r.duration_ms for r in self.requests)

        return {
            "providers": providers,
            "provider": requests[-1].provider,  # Show latest
            "model": requests[-1].model,
            "requests": len(requests),
            "percentage": round(len(requests) / len(self.requests) * 100, 1),
            "successRate": round(len(successful) / len(requests) * 100, 1) if requests else 0,
            "timeouts": len([r for r in requests if not r.success and "timeout" in (r.error or "").lower()]),
            "avgResponseTime": f"{sum(r.duration_ms for r in successful) / len(successful) / 1000:.1f}s" if successful else "N/A",
            "totalTime": self._format_duration(total_time_ms),
            "timePercentage": round(total_time_ms / total_scan_time_ms * 100, 1) if total_scan_time_ms > 0 else 0
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
                "cost": f"{len(fast_requests)} requests × ${COST_PER_SMART_REQUEST} = ${cost_savings:.2f} saved",
                "time": f"{len(fast_requests)} requests × ({smart_avg/1000:.1f}s - {fast_avg/1000:.1f}s) = {self._format_duration(int(time_saved_ms))} saved" if time_saved_ms > 0 else "No time savings"
            }
        }

    def _detect_issues(self) -> list[dict]:
        """Detect performance issues."""
        issues = []

        fast_requests = [r for r in self.requests if r.tier == "fast"]
        if fast_requests:
            failed = [r for r in fast_requests if not r.success]
            failure_rate = len(failed) / len(fast_requests)

            if failure_rate > 0.1:  # >10% failure rate
                providers = list({r.provider for r in failed})
                issues.append({
                    "type": "reliability",
                    "tier": "fast",
                    "count": len(failed),
                    "severity": "warning",
                    "message": f"{len(failed)} fast tier requests ({', '.join(providers)}) failed or timed out",
                    "recommendations": [
                        "Check local service (Ollama) health",
                        "Increase fast tier timeout",
                        "Verify Groq/Cloud failover status"
                    ]
                })

        return issues
