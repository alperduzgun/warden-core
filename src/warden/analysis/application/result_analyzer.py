"""
Result Analyzer - Pipeline result analysis and trend detection.

Analyzes pipeline results to:
- Calculate trends
- Aggregate statistics
- Compare with baseline
- Generate quality scores
"""

from typing import List, Dict, Any
from datetime import datetime

from warden.analysis.domain.models import (
    AnalysisResult,
    IssueTrend,
    SeverityStats,
    FrameStats,
    IssueSnapshot,
)
from warden.analysis.domain.enums import TrendDirection, AnalysisStatus
from warden.analysis.application.issue_tracker import IssueTracker
from warden.pipeline.domain.models import PipelineResult
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)


class ResultAnalyzer:
    """
    Analyzes pipeline results and generates insights.

    Responsibilities:
    - Calculate trends (improving, stable, degrading)
    - Aggregate frame statistics
    - Generate quality scores
    - Compare with baseline
    """

    def __init__(self, issue_tracker: IssueTracker) -> None:
        """
        Initialize result analyzer.

        Args:
            issue_tracker: IssueTracker for historical data
        """
        self.issue_tracker = issue_tracker

    async def analyze(
        self,
        pipeline_result: PipelineResult,
        project_id: str = "",
        branch: str = "main",
        commit_hash: str = "",
    ) -> AnalysisResult:
        """
        Analyze pipeline result.

        Args:
            pipeline_result: Result from pipeline execution
            project_id: Project identifier
            branch: Git branch
            commit_hash: Git commit hash

        Returns:
            AnalysisResult with trends and statistics
        """
        start_time = datetime.utcnow()

        logger.info(
            "analysis_started",
            pipeline_id=pipeline_result.pipeline_id,
            total_findings=pipeline_result.total_findings,
        )

        # Create snapshot from pipeline result
        snapshot = IssueSnapshot.from_pipeline_result(
            pipeline_result,
            project_id=project_id,
            branch=branch,
            commit_hash=commit_hash,
        )

        # Get previous snapshot for comparison
        previous_snapshot = self.issue_tracker.get_latest_snapshot()

        # Track issues and get categorization
        issue_categorization = self.issue_tracker.track_snapshot(
            snapshot,
            previous_snapshot,
        )

        # Calculate severity stats
        severity_stats = SeverityStats(
            critical=pipeline_result.critical_findings,
            high=pipeline_result.high_findings,
            medium=pipeline_result.medium_findings,
            low=pipeline_result.low_findings,
        )

        # Calculate frame statistics
        frame_stats = self._calculate_frame_stats(pipeline_result)

        # Calculate trend
        overall_trend = self._calculate_trend(
            snapshot,
            previous_snapshot,
        )

        # Calculate issue trends
        issue_trends = self._calculate_issue_trends()

        # Create analysis result
        duration = (datetime.utcnow() - start_time).total_seconds()

        analysis_result = AnalysisResult(
            status=AnalysisStatus.COMPLETED,
            executed_at=start_time,
            total_issues=snapshot.total_issues,
            new_issues=len(issue_categorization["new"]),
            resolved_issues=len(issue_categorization["resolved"]),
            reopened_issues=len(issue_categorization["reopened"]),
            persistent_issues=len(issue_categorization["persistent"]),
            severity_stats=severity_stats,
            frame_stats=frame_stats,
            overall_trend=overall_trend,
            issue_trends=issue_trends,
            duration=duration,
            metadata={
                "pipeline_id": pipeline_result.pipeline_id,
                "project_id": project_id,
                "branch": branch,
                "commit_hash": commit_hash,
                "snapshot_id": snapshot.id,
            },
        )

        logger.info(
            "analysis_completed",
            analysis_id=analysis_result.id,
            quality_score=analysis_result.quality_score,
            trend=overall_trend.value,
            new_issues=analysis_result.new_issues,
            resolved_issues=analysis_result.resolved_issues,
        )

        return analysis_result

    def _calculate_frame_stats(
        self,
        pipeline_result: PipelineResult,
    ) -> List[FrameStats]:
        """Calculate statistics for each frame."""
        frame_stats: List[FrameStats] = []

        for frame_result in pipeline_result.frame_results:
            # Count severity
            severity_stats = SeverityStats()

            for finding in frame_result.findings:
                if finding.severity == "critical":
                    severity_stats.critical += 1
                elif finding.severity == "high":
                    severity_stats.high += 1
                elif finding.severity == "medium":
                    severity_stats.medium += 1
                elif finding.severity == "low":
                    severity_stats.low += 1

            stats = FrameStats(
                frame_id=frame_result.frame_id,
                frame_name=frame_result.frame_name,
                executions=1,  # Current execution
                passes=1 if frame_result.status == "passed" else 0,
                failures=1 if frame_result.status == "failed" else 0,
                total_findings=frame_result.issues_found,
                severity_stats=severity_stats,
            )

            frame_stats.append(stats)

        return frame_stats

    def _calculate_trend(
        self,
        current_snapshot: IssueSnapshot,
        previous_snapshot: IssueSnapshot | None,
    ) -> TrendDirection:
        """
        Calculate overall trend direction.

        Args:
            current_snapshot: Current issue snapshot
            previous_snapshot: Previous snapshot

        Returns:
            TrendDirection (improving, stable, degrading, unknown)
        """
        if previous_snapshot is None:
            return TrendDirection.UNKNOWN

        current_total = current_snapshot.total_issues
        previous_total = previous_snapshot.total_issues

        # Calculate percentage change
        if previous_total == 0:
            if current_total == 0:
                return TrendDirection.STABLE
            else:
                return TrendDirection.DEGRADING

        change_percent = ((current_total - previous_total) / previous_total) * 100

        # Determine trend
        if change_percent < -5:  # 5% improvement
            return TrendDirection.IMPROVING
        elif change_percent > 5:  # 5% degradation
            return TrendDirection.DEGRADING
        else:
            return TrendDirection.STABLE

    def _calculate_issue_trends(self) -> List[IssueTrend]:
        """
        Calculate trends for individual issues.

        Returns:
            List of IssueTrend for frequently occurring issues
        """
        issue_trends: List[IssueTrend] = []

        # Get all issues
        all_issues = self.issue_tracker.get_all_issues()

        # Group by issue type
        issue_by_type: Dict[str, List[Any]] = {}

        for issue in all_issues:
            if issue.type not in issue_by_type:
                issue_by_type[issue.type] = []
            issue_by_type[issue.type].append(issue)

        # Calculate trends for each type
        for issue_type, issues in issue_by_type.items():
            if not issues:
                continue

            # Calculate statistics
            occurrence_count = len(issues)
            resolution_count = sum(
                1 for i in issues if i.state.value == 1  # RESOLVED
            )
            reopen_count = sum(i.reopen_count for i in issues)

            # Determine trend
            if resolution_count > occurrence_count * 0.7:
                trend = TrendDirection.IMPROVING
            elif reopen_count > occurrence_count * 0.3:
                trend = TrendDirection.DEGRADING
            else:
                trend = TrendDirection.STABLE

            # Get first and last seen
            first_seen = min(i.first_detected for i in issues)
            last_seen = max(i.last_updated for i in issues)

            issue_trend = IssueTrend(
                issue_id=issues[0].id,
                issue_type=issue_type,
                first_seen=first_seen,
                last_seen=last_seen,
                occurrence_count=occurrence_count,
                resolution_count=resolution_count,
                reopen_count=reopen_count,
                trend=trend,
            )

            issue_trends.append(issue_trend)

        # Sort by occurrence count (most frequent first)
        issue_trends.sort(key=lambda t: t.occurrence_count, reverse=True)

        return issue_trends[:10]  # Top 10 trending issues
