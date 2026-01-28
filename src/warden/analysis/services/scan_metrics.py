"""
Scan Metrics Tracking.

Collects and aggregates metrics for scan operations,
including intelligence hit rate and file risk distribution.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
from enum import Enum


class ScanStrategy(Enum):
    """Scan strategy used for a file."""
    FULL_LLM = "full_llm"           # Deep LLM analysis
    RUST_ONLY = "rust_only"         # Fast Rust-based scan
    SKIPPED = "skipped"             # Skipped (test file, etc.)
    CACHED = "cached"               # Used cached result


@dataclass
class FileMetrics:
    """Metrics for a single scanned file."""
    file_path: str
    risk_level: str  # P0, P1, P2, P3
    strategy: ScanStrategy
    duration_ms: int = 0
    llm_used: bool = False
    intelligence_hit: bool = False  # True if risk level came from intelligence
    findings_count: int = 0


@dataclass
class ScanMetricsCollector:
    """
    Collects and aggregates scan metrics.

    Tracks:
    - Intelligence hit rate
    - Files by risk level
    - LLM usage
    - Scan performance
    """

    files: List[FileMetrics] = field(default_factory=list)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    intelligence_available: bool = False
    intelligence_quality: int = 0

    def start(self) -> None:
        """Mark scan start time."""
        self.start_time = datetime.now(timezone.utc)

    def end(self) -> None:
        """Mark scan end time."""
        self.end_time = datetime.now(timezone.utc)

    def record_file(
        self,
        file_path: str,
        risk_level: str,
        strategy: ScanStrategy,
        duration_ms: int = 0,
        llm_used: bool = False,
        intelligence_hit: bool = False,
        findings_count: int = 0
    ) -> None:
        """Record metrics for a single file."""
        self.files.append(FileMetrics(
            file_path=file_path,
            risk_level=risk_level,
            strategy=strategy,
            duration_ms=duration_ms,
            llm_used=llm_used,
            intelligence_hit=intelligence_hit,
            findings_count=findings_count
        ))

    def get_summary(self) -> Dict[str, Any]:
        """Generate summary statistics."""
        if not self.files:
            return {}

        total_files = len(self.files)
        total_duration_ms = sum(f.duration_ms for f in self.files)

        # Risk distribution
        risk_counts = {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
        for f in self.files:
            if f.risk_level in risk_counts:
                risk_counts[f.risk_level] += 1

        # Strategy distribution
        strategy_counts = {s.value: 0 for s in ScanStrategy}
        for f in self.files:
            strategy_counts[f.strategy.value] += 1

        # Intelligence hit rate
        intel_hits = sum(1 for f in self.files if f.intelligence_hit)
        intel_hit_rate = (intel_hits / total_files * 100) if total_files > 0 else 0

        # LLM usage
        llm_files = sum(1 for f in self.files if f.llm_used)
        llm_rate = (llm_files / total_files * 100) if total_files > 0 else 0

        # Findings
        total_findings = sum(f.findings_count for f in self.files)

        # Scan duration
        scan_duration_ms = 0
        if self.start_time and self.end_time:
            scan_duration_ms = int((self.end_time - self.start_time).total_seconds() * 1000)

        return {
            "summary": {
                "totalFiles": total_files,
                "totalDuration": self._format_duration(scan_duration_ms),
                "totalDurationMs": scan_duration_ms,
                "totalFindings": total_findings,
            },
            "riskDistribution": {
                "P0_critical": risk_counts["P0"],
                "P1_high": risk_counts["P1"],
                "P2_medium": risk_counts["P2"],
                "P3_low": risk_counts["P3"],
            },
            "strategyDistribution": strategy_counts,
            "intelligence": {
                "available": self.intelligence_available,
                "quality": self.intelligence_quality,
                "hitRate": round(intel_hit_rate, 1),
                "hitCount": intel_hits,
            },
            "llm": {
                "filesAnalyzed": llm_files,
                "usageRate": round(llm_rate, 1),
            }
        }

    def _format_duration(self, ms: int) -> str:
        """Format duration in human-readable format."""
        if ms < 1000:
            return f"{ms}ms"
        elif ms < 60000:
            return f"{ms / 1000:.1f}s"
        else:
            minutes = ms // 60000
            seconds = (ms % 60000) / 1000
            return f"{minutes}m {seconds:.0f}s"

    def get_intelligence_report(self) -> Dict[str, Any]:
        """
        Generate a detailed intelligence usage report.

        Shows how effectively the pre-computed intelligence
        was used during the scan.
        """
        if not self.files:
            return {"status": "no_files_scanned"}

        # Files with intelligence hit
        intel_files = [f for f in self.files if f.intelligence_hit]
        no_intel_files = [f for f in self.files if not f.intelligence_hit]

        # Breakdown by risk for intelligence hits
        intel_by_risk = {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
        for f in intel_files:
            if f.risk_level in intel_by_risk:
                intel_by_risk[f.risk_level] += 1

        # Calculate LLM savings
        # P3 files with intelligence hit = LLM calls saved
        llm_calls_saved = sum(1 for f in intel_files if f.risk_level == "P3" and not f.llm_used)

        report = {
            "intelligenceUsage": {
                "totalFiles": len(self.files),
                "withIntelligence": len(intel_files),
                "withoutIntelligence": len(no_intel_files),
                "hitRate": round(len(intel_files) / len(self.files) * 100, 1) if self.files else 0,
            },
            "riskClassification": intel_by_risk,
            "efficiency": {
                "llmCallsSaved": llm_calls_saved,
                "estimatedTimeSaved": f"{llm_calls_saved * 2}s",  # Assume 2s per LLM call
            },
            "quality": {
                "score": self.intelligence_quality,
                "status": self._quality_status(self.intelligence_quality)
            }
        }

        return report

    def _quality_status(self, score: int) -> str:
        """Get human-readable quality status."""
        if score >= 80:
            return "excellent"
        elif score >= 60:
            return "good"
        elif score >= 40:
            return "fair"
        else:
            return "needs_refresh"


# Global singleton for collecting scan metrics across the scan
_global_scan_metrics: Optional[ScanMetricsCollector] = None


def get_scan_metrics() -> ScanMetricsCollector:
    """Get the global scan metrics collector."""
    global _global_scan_metrics
    if _global_scan_metrics is None:
        _global_scan_metrics = ScanMetricsCollector()
    return _global_scan_metrics


def reset_scan_metrics() -> ScanMetricsCollector:
    """Reset and return a new scan metrics collector."""
    global _global_scan_metrics
    _global_scan_metrics = ScanMetricsCollector()
    return _global_scan_metrics
