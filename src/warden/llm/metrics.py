"""
LLM Performance Metrics Tracking

Collects and aggregates metrics for LLM requests across tiers.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime


@dataclass
class LLMRequestMetrics:
    """Metrics for a single LLM request."""
    tier: str  # "fast" or "smart"
    provider: str  # "ollama", "azure_openai", etc.
    model: str
    success: bool
    duration_ms: int
    error: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class LLMMetricsCollector:
    """Collects and aggregates LLM metrics."""
    requests: List[LLMRequestMetrics] = field(default_factory=list)
    
    def record_request(
        self, 
        tier: str, 
        provider: str, 
        model: str, 
        success: bool, 
        duration_ms: int, 
        error: Optional[str] = None
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
    
    def get_summary(self) -> Dict:
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
    
    def _tier_stats(self, requests: List[LLMRequestMetrics]) -> Dict:
        """Calculate statistics for a tier."""
        if not requests:
            return None
        
        successful = [r for r in requests if r.success]
        timeouts = [r for r in requests if not r.success and "timeout" in (r.error or "").lower()]
        
        total_time_ms = sum(r.duration_ms for r in requests)
        total_scan_time_ms = sum(r.duration_ms for r in self.requests)
        
        return {
            "provider": requests[0].provider,
            "model": requests[0].model,
            "requests": len(requests),
            "percentage": round(len(requests) / len(self.requests) * 100, 1),
            "successRate": round(len(successful) / len(requests) * 100, 1) if requests else 0,
            "timeouts": len(timeouts),
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
    
    def _cost_analysis(self, fast_requests: List, smart_requests: List) -> Dict:
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
    
    def _detect_issues(self) -> List[Dict]:
        """Detect performance issues."""
        issues = []
        
        fast_requests = [r for r in self.requests if r.tier == "fast"]
        if fast_requests:
            timeouts = [r for r in fast_requests if not r.success]
            timeout_rate = len(timeouts) / len(fast_requests)
            
            if timeout_rate > 0.1:  # >10% timeout rate
                issues.append({
                    "type": "timeout",
                    "tier": "fast",
                    "count": len(timeouts),
                    "severity": "warning",
                    "message": f"{len(timeouts)} Qwen requests timed out, fell back to Azure",
                    "recommendations": [
                        "Increase timeout from 30s to 60s",
                        "Reduce concurrency to avoid resource exhaustion"
                    ]
                })
        
        return issues
