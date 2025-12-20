"""
Tests for ResultAnalyzer.

Validates result analysis and trend detection.
"""

import pytest
from warden.analysis import ResultAnalyzer, IssueTracker, TrendDirection
from warden.pipeline import PipelineResult, PipelineStatus
from warden.validation.domain.frame import FrameResult, Finding


def create_test_pipeline_result(
    total_findings: int = 5,
    critical: int = 1,
    high: int = 2,
    medium: int = 1,
    low: int = 1,
) -> PipelineResult:
    """Helper to create test pipeline result."""
    # Create findings
    findings = []

    for i in range(critical):
        findings.append(
            Finding(
                id=f"finding-critical-{i}",
                severity="critical",
                message="Critical issue",
                location=f"test.py:{i}",
                code=f"code_{i}",
            )
        )

    for i in range(high):
        findings.append(
            Finding(
                id=f"finding-high-{i}",
                severity="high",
                message="High issue",
                location=f"test.py:{i+10}",
                code=f"code_{i+10}",
            )
        )

    for i in range(medium):
        findings.append(
            Finding(
                id=f"finding-medium-{i}",
                severity="medium",
                message="Medium issue",
                location=f"test.py:{i+20}",
                code=f"code_{i+20}",
            )
        )

    for i in range(low):
        findings.append(
            Finding(
                id=f"finding-low-{i}",
                severity="low",
                message="Low issue",
                location=f"test.py:{i+30}",
                code=f"code_{i+30}",
            )
        )

    # Create frame result
    frame_result = FrameResult(
        frame_id="security",
        frame_name="Security Analysis",
        status="failed" if total_findings > 0 else "passed",
        duration=0.5,
        issues_found=total_findings,
        is_blocker=True,
        findings=findings,
    )

    return PipelineResult(
        pipeline_id="test-pipeline",
        pipeline_name="Test Pipeline",
        status=PipelineStatus.FAILED if total_findings > 0 else PipelineStatus.COMPLETED,
        duration=1.0,
        total_frames=1,
        frames_passed=0 if total_findings > 0 else 1,
        frames_failed=1 if total_findings > 0 else 0,
        frames_skipped=0,
        total_findings=total_findings,
        critical_findings=critical,
        high_findings=high,
        medium_findings=medium,
        low_findings=low,
        frame_results=[frame_result],
    )


@pytest.mark.asyncio
async def test_result_analyzer_first_run():
    """Test analysis of first pipeline run."""
    tracker = IssueTracker()
    analyzer = ResultAnalyzer(tracker)

    # Create pipeline result
    pipeline_result = create_test_pipeline_result(
        total_findings=5,
        critical=1,
        high=2,
        medium=1,
        low=1,
    )

    # Analyze
    analysis = await analyzer.analyze(pipeline_result)

    # Check results
    assert analysis.total_issues == 5
    assert analysis.new_issues == 5  # All new on first run
    assert analysis.resolved_issues == 0
    assert analysis.reopened_issues == 0
    assert analysis.persistent_issues == 0

    # Check severity stats
    assert analysis.severity_stats.critical == 1
    assert analysis.severity_stats.high == 2
    assert analysis.severity_stats.medium == 1
    assert analysis.severity_stats.low == 1

    # First run should have UNKNOWN trend
    assert analysis.overall_trend == TrendDirection.UNKNOWN


@pytest.mark.asyncio
async def test_result_analyzer_improving_trend():
    """Test detection of improving trend."""
    tracker = IssueTracker()
    analyzer = ResultAnalyzer(tracker)

    # First run with 10 issues
    result1 = create_test_pipeline_result(total_findings=10, critical=3, high=4, medium=2, low=1)
    await analyzer.analyze(result1)

    # Second run with 5 issues (50% reduction = improving)
    result2 = create_test_pipeline_result(total_findings=5, critical=1, high=2, medium=1, low=1)
    analysis = await analyzer.analyze(result2)

    # Should detect improving trend
    assert analysis.overall_trend == TrendDirection.IMPROVING
    assert analysis.resolved_issues > 0


@pytest.mark.asyncio
async def test_result_analyzer_degrading_trend():
    """Test detection of degrading trend."""
    tracker = IssueTracker()
    analyzer = ResultAnalyzer(tracker)

    # First run with 5 issues
    result1 = create_test_pipeline_result(total_findings=5, critical=1, high=2, medium=1, low=1)
    await analyzer.analyze(result1)

    # Second run with 15 issues (3x increase = degrading)
    result2 = create_test_pipeline_result(total_findings=15, critical=5, high=5, medium=3, low=2)
    analysis = await analyzer.analyze(result2)

    # Should detect degrading trend
    assert analysis.overall_trend == TrendDirection.DEGRADING
    assert analysis.new_issues > 0


@pytest.mark.asyncio
async def test_result_analyzer_stable_trend():
    """Test detection of stable trend."""
    tracker = IssueTracker()
    analyzer = ResultAnalyzer(tracker)

    # First run with 10 issues
    result1 = create_test_pipeline_result(total_findings=10, critical=2, high=4, medium=2, low=2)
    await analyzer.analyze(result1)

    # Second run with 10 issues (same = stable)
    result2 = create_test_pipeline_result(total_findings=10, critical=2, high=4, medium=2, low=2)
    analysis = await analyzer.analyze(result2)

    # Should detect stable trend (within 5% tolerance)
    assert analysis.overall_trend == TrendDirection.STABLE


@pytest.mark.asyncio
async def test_result_analyzer_quality_score():
    """Test quality score calculation."""
    tracker = IssueTracker()
    analyzer = ResultAnalyzer(tracker)

    # Perfect code (no issues)
    result_perfect = create_test_pipeline_result(
        total_findings=0,
        critical=0,
        high=0,
        medium=0,
        low=0,
    )
    analysis_perfect = await analyzer.analyze(result_perfect)

    # Should have high quality score
    assert analysis_perfect.quality_score == 100.0

    tracker.clear()

    # Code with critical issues
    result_critical = create_test_pipeline_result(
        total_findings=3,
        critical=3,
        high=0,
        medium=0,
        low=0,
    )

    analyzer2 = ResultAnalyzer(IssueTracker())
    analysis_critical = await analyzer2.analyze(result_critical)

    # Quality score should be reduced significantly
    # 100 - (3 * 10) = 70
    assert analysis_critical.quality_score == 70.0


@pytest.mark.asyncio
async def test_result_analyzer_frame_stats():
    """Test frame statistics calculation."""
    tracker = IssueTracker()
    analyzer = ResultAnalyzer(tracker)

    pipeline_result = create_test_pipeline_result(total_findings=5)
    analysis = await analyzer.analyze(pipeline_result)

    # Should have frame stats
    assert len(analysis.frame_stats) == 1

    frame_stat = analysis.frame_stats[0]
    assert frame_stat.frame_id == "security"
    assert frame_stat.frame_name == "Security Analysis"
    assert frame_stat.executions == 1
    assert frame_stat.total_findings == 5


@pytest.mark.asyncio
async def test_result_analyzer_persistent_issues():
    """Test tracking of persistent issues."""
    tracker = IssueTracker()
    analyzer = ResultAnalyzer(tracker)

    # First run
    result1 = create_test_pipeline_result(total_findings=5)
    await analyzer.analyze(result1)

    # Second run with same issues (persistent)
    result2 = create_test_pipeline_result(total_findings=5)
    analysis = await analyzer.analyze(result2)

    # Issues should be persistent
    assert analysis.persistent_issues == 5
    assert analysis.new_issues == 0


@pytest.mark.asyncio
async def test_result_analyzer_metadata():
    """Test analysis metadata."""
    tracker = IssueTracker()
    analyzer = ResultAnalyzer(tracker)

    pipeline_result = create_test_pipeline_result()
    analysis = await analyzer.analyze(
        pipeline_result,
        project_id="test-project",
        branch="main",
        commit_hash="abc123",
    )

    # Check metadata
    assert analysis.metadata["project_id"] == "test-project"
    assert analysis.metadata["branch"] == "main"
    assert analysis.metadata["commit_hash"] == "abc123"
    assert "pipeline_id" in analysis.metadata
    assert "snapshot_id" in analysis.metadata


@pytest.mark.asyncio
async def test_result_analyzer_panel_json():
    """Test Panel JSON compatibility."""
    tracker = IssueTracker()
    analyzer = ResultAnalyzer(tracker)

    pipeline_result = create_test_pipeline_result()
    analysis = await analyzer.analyze(pipeline_result)

    # Convert to JSON
    json_data = analysis.to_json()

    # Check camelCase fields
    assert "totalIssues" in json_data
    assert "newIssues" in json_data
    assert "resolvedIssues" in json_data
    assert "reopenedIssues" in json_data
    assert "persistentIssues" in json_data
    assert "severityStats" in json_data
    assert "frameStats" in json_data
    assert "overallTrend" in json_data
    assert "qualityScore" in json_data

    # Status should be integer
    assert isinstance(json_data["status"], int)

    # Trend should be string
    assert isinstance(json_data["overallTrend"], str)
