"""
Analysis domain models.

Core entities for code analysis and issue tracking.
"""

from datetime import datetime
from typing import List, Dict, Any
from uuid import uuid4

from pydantic import Field
from warden.shared.domain.base_model import BaseDomainModel
from warden.analysis.domain.enums import TrendDirection, AnalysisStatus
from warden.issues.domain.models import WardenIssue
from warden.issues.domain.enums import IssueSeverity


class IssueTrend(BaseDomainModel):
    """
    Trend analysis for a specific issue.

    Tracks how an issue evolves over multiple runs.
    """

    issue_id: str
    issue_type: str
    first_seen: datetime
    last_seen: datetime
    occurrence_count: int  # How many times detected
    resolution_count: int  # How many times resolved
    reopen_count: int  # How many times reopened
    trend: TrendDirection

    def to_json(self) -> Dict[str, Any]:
        """Convert to Panel-compatible JSON."""
        data = super().to_json()
        data["trend"] = self.trend.value  # String for Panel
        return data


class SeverityStats(BaseDomainModel):
    """
    Statistics by severity level.

    Aggregates findings by severity.
    """

    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0

    @property
    def total(self) -> int:
        """Total issues across all severities."""
        return self.critical + self.high + self.medium + self.low

    @property
    def blocker_count(self) -> int:
        """Count of critical and high severity issues."""
        return self.critical + self.high


class FrameStats(BaseDomainModel):
    """
    Statistics for a specific frame.

    Tracks frame execution and findings over time.
    """

    frame_id: str
    frame_name: str
    executions: int  # How many times executed
    passes: int  # How many times passed
    failures: int  # How many times failed
    total_findings: int
    severity_stats: SeverityStats

    @property
    def pass_rate(self) -> float:
        """Calculate pass rate percentage."""
        if self.executions == 0:
            return 0.0
        return (self.passes / self.executions) * 100


class AnalysisResult(BaseDomainModel):
    """
    Complete analysis result.

    Aggregates findings, trends, and statistics.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    status: AnalysisStatus = AnalysisStatus.PENDING
    executed_at: datetime = Field(default_factory=datetime.utcnow)

    # Issue tracking
    total_issues: int = 0
    new_issues: int = 0  # First time detected
    resolved_issues: int = 0  # Previously detected, now fixed
    reopened_issues: int = 0  # Previously resolved, now back
    persistent_issues: int = 0  # Still present from last run

    # Severity breakdown
    severity_stats: SeverityStats = Field(default_factory=SeverityStats)

    # Frame statistics
    frame_stats: List[FrameStats] = Field(default_factory=list)

    # Trend analysis
    overall_trend: TrendDirection = TrendDirection.UNKNOWN
    issue_trends: List[IssueTrend] = Field(default_factory=list)

    # Comparison with baseline
    baseline_comparison: Dict[str, Any] = Field(default_factory=dict)

    # Metadata
    duration: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def to_json(self) -> Dict[str, Any]:
        """Convert to Panel-compatible JSON."""
        data = super().to_json()

        # Convert enums
        data["status"] = self.status.value
        data["overallTrend"] = self.overall_trend.value

        # Convert nested objects
        data["severityStats"] = self.severity_stats.to_json()
        data["frameStats"] = [fs.to_json() for fs in self.frame_stats]
        data["issueTrends"] = [it.to_json() for it in self.issue_trends]

        # Add computed property
        data["qualityScore"] = self.quality_score

        return data

    @property
    def quality_score(self) -> float:
        """
        Calculate overall code quality score (0-100).

        Based on:
        - Issue count (fewer is better)
        - Severity distribution (critical/high reduce score more)
        - Trend direction (improving increases score)
        """
        # Start with 100
        score = 100.0

        # Deduct for issues
        score -= self.severity_stats.critical * 10  # Critical: -10 each
        score -= self.severity_stats.high * 5  # High: -5 each
        score -= self.severity_stats.medium * 2  # Medium: -2 each
        score -= self.severity_stats.low * 0.5  # Low: -0.5 each

        # Adjust for trend
        if self.overall_trend == TrendDirection.IMPROVING:
            score += 5  # Bonus for improving
        elif self.overall_trend == TrendDirection.DEGRADING:
            score -= 10  # Penalty for degrading

        # Clamp to 0-100
        return max(0.0, min(100.0, score))


class IssueSnapshot(BaseDomainModel):
    """
    Snapshot of issues at a specific point in time.

    Used for historical comparison and trend analysis.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    project_id: str = ""
    branch: str = "main"
    commit_hash: str = ""

    # Issues in this snapshot
    issues: List[WardenIssue] = Field(default_factory=list)

    # Summary statistics
    total_issues: int = 0
    severity_stats: SeverityStats = Field(default_factory=SeverityStats)

    # Metadata
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def to_json(self) -> Dict[str, Any]:
        """Convert to Panel-compatible JSON."""
        data = super().to_json()

        # Convert issues
        data["issues"] = [issue.to_json() for issue in self.issues]

        # Convert severity stats
        data["severityStats"] = self.severity_stats.to_json()

        return data

    @classmethod
    def from_pipeline_result(
        cls,
        pipeline_result: Any,  # PipelineResult
        project_id: str = "",
        branch: str = "main",
        commit_hash: str = "",
    ) -> "IssueSnapshot":
        """
        Create snapshot from pipeline result.

        Args:
            pipeline_result: PipelineResult from pipeline execution
            project_id: Project identifier
            branch: Git branch
            commit_hash: Git commit hash

        Returns:
            IssueSnapshot with issues from pipeline result
        """
        from warden.issues.domain.models import WardenIssue
        from warden.issues.domain.enums import IssueState
        import hashlib

        # Extract issues from pipeline result
        issues: List[WardenIssue] = []
        severity_stats = SeverityStats()

        for frame_result in pipeline_result.frame_results:
            for finding in frame_result.findings:
                # Convert Finding to WardenIssue
                # Hash based on file + code content (NOT line number for stable deduplication)
                file_path = finding.location.split(":")[0]
                code_hash = hashlib.sha256(
                    f"{file_path}:{finding.code}:{finding.message}".encode()
                ).hexdigest()[:16]

                issue = WardenIssue(
                    id=finding.id,
                    type=finding.message.split("]")[0].strip("["),
                    severity=IssueSeverity[finding.severity.upper()],
                    file_path=finding.location.split(":")[0],
                    message=finding.message,
                    code_snippet=finding.code or "",
                    code_hash=code_hash,
                    state=IssueState.OPEN,
                    first_detected=datetime.utcnow(),
                    last_updated=datetime.utcnow(),
                    reopen_count=0,
                    state_history=[],
                )

                issues.append(issue)

                # Update severity stats
                if issue.severity == IssueSeverity.CRITICAL:
                    severity_stats.critical += 1
                elif issue.severity == IssueSeverity.HIGH:
                    severity_stats.high += 1
                elif issue.severity == IssueSeverity.MEDIUM:
                    severity_stats.medium += 1
                elif issue.severity == IssueSeverity.LOW:
                    severity_stats.low += 1

        return cls(
            project_id=project_id,
            branch=branch,
            commit_hash=commit_hash,
            issues=issues,
            total_issues=len(issues),
            severity_stats=severity_stats,
        )
