"""
Integration test for complete analysis flow.

Tests the complete workflow:
Pipeline → Analysis → Issue Tracking → Trends
"""

import pytest
from warden.pipeline import PipelineOrchestrator, PipelineConfig, ExecutionStrategy
from warden.validation.frames import SecurityFrame
from warden.validation.domain.frame import CodeFile
from warden.analysis import IssueTracker, ResultAnalyzer, TrendDirection


@pytest.mark.asyncio
async def test_complete_analysis_flow():
    """
    Test complete analysis workflow.

    Simulates multiple pipeline runs with code improvements.
    """
    # Setup
    tracker = IssueTracker()
    analyzer = ResultAnalyzer(tracker)

    # Run 1: Code with multiple issues
    print("\n=== RUN 1: Initial code scan ===")

    vulnerable_code = '''
# Multiple security issues
password = "admin123"
api_key = "sk-1234567890abcdefghijklmnopqrstuvwxyz123456789012"
query = f"SELECT * FROM users WHERE id = {user_id}"
'''

    code_file_1 = CodeFile(
        path="app.py",
        content=vulnerable_code,
        language="python",
    )

    orchestrator = PipelineOrchestrator(
        frames=[SecurityFrame()],
        config=PipelineConfig(strategy=ExecutionStrategy.SEQUENTIAL),
    )

    pipeline_result_1 = await orchestrator.execute([code_file_1])
    analysis_1 = await analyzer.analyze(
        pipeline_result_1,
        project_id="test-project",
        branch="main",
        commit_hash="commit-1",
    )

    # Assertions for Run 1
    assert analysis_1.total_issues > 0
    assert analysis_1.new_issues > 0  # All issues are new
    assert analysis_1.resolved_issues == 0
    assert analysis_1.overall_trend == TrendDirection.UNKNOWN  # First run

    print(f"Total Issues: {analysis_1.total_issues}")
    print(f"New Issues: {analysis_1.new_issues}")
    print(f"Quality Score: {analysis_1.quality_score:.1f}/100")

    # Run 2: Fix one issue (password)
    print("\n=== RUN 2: Fix hardcoded password ===")

    improved_code_v1 = '''
import os

# Fixed: Password now from environment
password = os.getenv("DB_PASSWORD")
api_key = "sk-1234567890abcdefghijklmnopqrstuvwxyz123456789012"
query = f"SELECT * FROM users WHERE id = {user_id}"
'''

    code_file_2 = CodeFile(
        path="app.py",
        content=improved_code_v1,
        language="python",
    )

    pipeline_result_2 = await orchestrator.execute([code_file_2])
    analysis_2 = await analyzer.analyze(
        pipeline_result_2,
        project_id="test-project",
        branch="main",
        commit_hash="commit-2",
    )

    # Assertions for Run 2
    assert analysis_2.total_issues < analysis_1.total_issues  # Fewer issues
    assert analysis_2.resolved_issues > 0  # Password issue resolved
    assert analysis_2.overall_trend == TrendDirection.IMPROVING  # Improving!

    print(f"Total Issues: {analysis_2.total_issues}")
    print(f"Resolved: {analysis_2.resolved_issues}")
    print(f"Trend: {analysis_2.overall_trend.value}")
    print(f"Quality Score: {analysis_2.quality_score:.1f}/100")

    # Run 3: Fix all remaining issues
    print("\n=== RUN 3: Fix all remaining issues ===")

    clean_code = '''
import os

# All issues fixed!
password = os.getenv("DB_PASSWORD")
api_key = os.getenv("OPENAI_API_KEY")

def get_user(user_id: str):
    # GOOD: Parameterized query
    query = "SELECT * FROM users WHERE id = ?"
    cursor.execute(query, (user_id,))
    return cursor.fetchone()
'''

    code_file_3 = CodeFile(
        path="app.py",
        content=clean_code,
        language="python",
    )

    pipeline_result_3 = await orchestrator.execute([code_file_3])
    analysis_3 = await analyzer.analyze(
        pipeline_result_3,
        project_id="test-project",
        branch="main",
        commit_hash="commit-3",
    )

    # Assertions for Run 3
    assert analysis_3.total_issues == 0  # All issues resolved!
    assert analysis_3.resolved_issues > 0
    assert analysis_3.overall_trend == TrendDirection.IMPROVING
    assert analysis_3.quality_score == 100.0  # Perfect score!

    print(f"Total Issues: {analysis_3.total_issues}")
    print(f"Resolved: {analysis_3.resolved_issues}")
    print(f"Trend: {analysis_3.overall_trend.value}")
    print(f"Quality Score: {analysis_3.quality_score:.1f}/100")

    # Run 4: Regression - reintroduce an issue
    print("\n=== RUN 4: Regression - issue returns ===")

    regressed_code = '''
import os

password = os.getenv("DB_PASSWORD")
api_key = "sk-1234567890abcdefghijklmnopqrstuvwxyz123456789012"

def get_user(user_id: str):
    query = "SELECT * FROM users WHERE id = ?"
    cursor.execute(query, (user_id,))
    return cursor.fetchone()
'''

    code_file_4 = CodeFile(
        path="app.py",
        content=regressed_code,
        language="python",
    )

    pipeline_result_4 = await orchestrator.execute([code_file_4])
    analysis_4 = await analyzer.analyze(
        pipeline_result_4,
        project_id="test-project",
        branch="main",
        commit_hash="commit-4",
    )

    # Assertions for Run 4
    assert analysis_4.total_issues > 0
    assert analysis_4.reopened_issues > 0  # Issue came back!
    assert analysis_4.overall_trend == TrendDirection.DEGRADING  # Regression detected

    print(f"Total Issues: {analysis_4.total_issues}")
    print(f"Reopened: {analysis_4.reopened_issues}")
    print(f"Trend: {analysis_4.overall_trend.value}")
    print(f"Quality Score: {analysis_4.quality_score:.1f}/100")

    # Verify reopened issue has correct metadata
    reopened_issues = [
        issue
        for issue in tracker.get_all_issues()
        if issue.reopen_count > 0
    ]

    assert len(reopened_issues) > 0
    assert reopened_issues[0].reopen_count == 1

    # Summary
    print("\n=== ANALYSIS SUMMARY ===")
    print(f"Runs: 4")
    print(f"Total Issues Tracked: {len(tracker.get_all_issues())}")
    print(f"Currently Open: {len(tracker.get_open_issues())}")
    print(f"Currently Resolved: {len(tracker.get_resolved_issues())}")
    print(f"\nQuality Score Progression:")
    print(f"  Run 1: {analysis_1.quality_score:.1f}")
    print(f"  Run 2: {analysis_2.quality_score:.1f} (↑ Improving)")
    print(f"  Run 3: {analysis_3.quality_score:.1f} (↑ Perfect!)")
    print(f"  Run 4: {analysis_4.quality_score:.1f} (↓ Regression)")


@pytest.mark.asyncio
async def test_panel_json_complete_flow():
    """Test Panel JSON output in complete analysis flow."""
    tracker = IssueTracker()
    analyzer = ResultAnalyzer(tracker)

    # Simple pipeline run
    code_file = CodeFile(
        path="test.py",
        content='password = "admin"',
        language="python",
    )

    orchestrator = PipelineOrchestrator(
        frames=[SecurityFrame()],
        config=PipelineConfig(),
    )

    pipeline_result = await orchestrator.execute([code_file])
    analysis = await analyzer.analyze(pipeline_result)

    # Convert to Panel JSON
    json_data = analysis.to_json()

    # Validate Panel schema
    required_fields = [
        "id",
        "status",
        "executedAt",
        "totalIssues",
        "newIssues",
        "resolvedIssues",
        "reopenedIssues",
        "persistentIssues",
        "severityStats",
        "frameStats",
        "overallTrend",
        "qualityScore",
        "duration",
        "metadata",
    ]

    for field in required_fields:
        assert field in json_data, f"Missing required field: {field}"

    # Validate types
    assert isinstance(json_data["status"], int)
    assert isinstance(json_data["totalIssues"], int)
    assert isinstance(json_data["qualityScore"], float)
    assert isinstance(json_data["overallTrend"], str)
    assert isinstance(json_data["severityStats"], dict)
    assert isinstance(json_data["frameStats"], list)

    print("\n=== PANEL JSON OUTPUT ===")
    print(f"Status: {json_data['status']}")
    print(f"Total Issues: {json_data['totalIssues']}")
    print(f"Quality Score: {json_data['qualityScore']}")
    print(f"Trend: {json_data['overallTrend']}")
    print(f"Severity Breakdown:")
    print(f"  Critical: {json_data['severityStats']['critical']}")
    print(f"  High: {json_data['severityStats']['high']}")
    print(f"  Medium: {json_data['severityStats']['medium']}")
    print(f"  Low: {json_data['severityStats']['low']}")
