"""
Tests for IssueTracker.

Validates issue lifecycle management and deduplication.
"""

import pytest
from datetime import datetime
import hashlib

from warden.analysis import IssueTracker, IssueSnapshot
from warden.issues.domain.models import WardenIssue
from warden.issues.domain.enums import IssueSeverity, IssueState


def create_test_issue(
    code: str,
    severity: IssueSeverity = IssueSeverity.HIGH,
    file_path: str = "test.py",
    message: str = "Test issue",
) -> WardenIssue:
    """Helper to create test issue."""
    code_hash = hashlib.sha256(f"{file_path}:{code}:{message}".encode()).hexdigest()[:16]

    return WardenIssue(
        id=f"issue-{code_hash}",
        type="TestIssue",
        severity=severity,
        file_path=file_path,
        message=message,
        code_snippet=code,
        code_hash=code_hash,
        state=IssueState.OPEN,
        first_detected=datetime.utcnow(),
        last_updated=datetime.utcnow(),
        reopen_count=0,
        state_history=[],
    )


def test_issue_tracker_first_snapshot():
    """Test tracking first snapshot - all issues should be new."""
    tracker = IssueTracker()

    # Create snapshot with 3 issues
    issues = [
        create_test_issue("password = 'admin'", IssueSeverity.CRITICAL),
        create_test_issue("api_key = 'sk-123'", IssueSeverity.HIGH),
        create_test_issue("TODO: Fix this", IssueSeverity.LOW),
    ]

    snapshot = IssueSnapshot(
        issues=issues,
        total_issues=len(issues),
    )

    # Track snapshot
    result = tracker.track_snapshot(snapshot)

    # All should be new
    assert len(result["new"]) == 3
    assert len(result["resolved"]) == 0
    assert len(result["reopened"]) == 0
    assert len(result["persistent"]) == 0


def test_issue_tracker_persistent_issues():
    """Test tracking persistent issues across snapshots."""
    tracker = IssueTracker()

    # First snapshot
    issue1 = create_test_issue("password = 'admin'")
    issue2 = create_test_issue("api_key = 'sk-123'")

    snapshot1 = IssueSnapshot(
        issues=[issue1, issue2],
        total_issues=2,
    )

    tracker.track_snapshot(snapshot1)

    # Second snapshot with same issues
    snapshot2 = IssueSnapshot(
        issues=[issue1, issue2],
        total_issues=2,
    )

    result = tracker.track_snapshot(snapshot2, previous_snapshot=snapshot1)

    # Both should be persistent
    assert len(result["new"]) == 0
    assert len(result["resolved"]) == 0
    assert len(result["reopened"]) == 0
    assert len(result["persistent"]) == 2


def test_issue_tracker_resolved_issues():
    """Test detecting resolved issues."""
    tracker = IssueTracker()

    # First snapshot with 3 issues
    issue1 = create_test_issue("password = 'admin'")
    issue2 = create_test_issue("api_key = 'sk-123'")
    issue3 = create_test_issue("TODO: Fix")

    snapshot1 = IssueSnapshot(
        issues=[issue1, issue2, issue3],
        total_issues=3,
    )

    tracker.track_snapshot(snapshot1)

    # Second snapshot - issue2 is fixed
    snapshot2 = IssueSnapshot(
        issues=[issue1, issue3],  # issue2 removed
        total_issues=2,
    )

    result = tracker.track_snapshot(snapshot2, previous_snapshot=snapshot1)

    # Check results
    assert len(result["resolved"]) == 1
    assert len(result["persistent"]) == 2
    assert len(result["new"]) == 0
    assert len(result["reopened"]) == 0

    # Resolved issue should have state RESOLVED
    resolved_issue = tracker.get_issue_by_hash(issue2.code_hash)
    assert resolved_issue is not None
    assert resolved_issue.state == IssueState.RESOLVED


def test_issue_tracker_reopened_issues():
    """Test detecting reopened issues."""
    tracker = IssueTracker()

    # First snapshot
    issue1 = create_test_issue("password = 'admin'")
    snapshot1 = IssueSnapshot(issues=[issue1], total_issues=1)
    tracker.track_snapshot(snapshot1)

    # Second snapshot - issue1 resolved
    snapshot2 = IssueSnapshot(issues=[], total_issues=0)
    tracker.track_snapshot(snapshot2, previous_snapshot=snapshot1)

    # Verify issue is resolved
    resolved = tracker.get_issue_by_hash(issue1.code_hash)
    assert resolved.state == IssueState.RESOLVED

    # Third snapshot - issue1 is back!
    snapshot3 = IssueSnapshot(issues=[issue1], total_issues=1)
    result = tracker.track_snapshot(snapshot3, previous_snapshot=snapshot2)

    # Should be detected as reopened
    assert len(result["reopened"]) == 1
    assert len(result["new"]) == 0

    # Check reopen count
    reopened = result["reopened"][0]
    assert reopened.reopen_count == 1
    assert reopened.state == IssueState.OPEN


def test_issue_tracker_new_issues_added():
    """Test detecting new issues in subsequent snapshots."""
    tracker = IssueTracker()

    # First snapshot
    issue1 = create_test_issue("password = 'admin'")
    snapshot1 = IssueSnapshot(issues=[issue1], total_issues=1)
    tracker.track_snapshot(snapshot1)

    # Second snapshot with new issue
    issue2 = create_test_issue("api_key = 'sk-123'")
    snapshot2 = IssueSnapshot(
        issues=[issue1, issue2],
        total_issues=2,
    )

    result = tracker.track_snapshot(snapshot2, previous_snapshot=snapshot1)

    # Check results
    assert len(result["new"]) == 1
    assert len(result["persistent"]) == 1
    assert result["new"][0].code_hash == issue2.code_hash


def test_issue_tracker_deduplication():
    """Test issue deduplication using code_hash."""
    tracker = IssueTracker()

    # Create two issues with same code but different IDs
    issue1 = create_test_issue("password = 'admin'")
    issue2 = create_test_issue("password = 'admin'")  # Same code

    # They should have the same hash
    assert issue1.code_hash == issue2.code_hash

    # First snapshot
    snapshot1 = IssueSnapshot(issues=[issue1], total_issues=1)
    tracker.track_snapshot(snapshot1)

    # Second snapshot with "same" issue (different ID, same code)
    snapshot2 = IssueSnapshot(issues=[issue2], total_issues=1)
    result = tracker.track_snapshot(snapshot2, previous_snapshot=snapshot1)

    # Should be recognized as persistent, not new
    assert len(result["persistent"]) == 1
    assert len(result["new"]) == 0


def test_issue_tracker_get_open_issues():
    """Test getting only open issues."""
    tracker = IssueTracker()

    # Create and track issues
    issue1 = create_test_issue("password = 'admin'")
    issue2 = create_test_issue("api_key = 'sk-123'")

    snapshot1 = IssueSnapshot(issues=[issue1, issue2], total_issues=2)
    tracker.track_snapshot(snapshot1)

    # Resolve one issue
    snapshot2 = IssueSnapshot(issues=[issue2], total_issues=1)
    tracker.track_snapshot(snapshot2, previous_snapshot=snapshot1)

    # Get open issues
    open_issues = tracker.get_open_issues()

    # Should only have issue2
    assert len(open_issues) == 1
    assert open_issues[0].code_hash == issue2.code_hash


def test_issue_tracker_snapshot_history():
    """Test snapshot history tracking."""
    tracker = IssueTracker()

    # Create multiple snapshots
    for i in range(5):
        issue = create_test_issue(f"issue_{i}")
        snapshot = IssueSnapshot(issues=[issue], total_issues=1)
        tracker.track_snapshot(snapshot)

    # Get history
    history = tracker.get_snapshot_history(limit=3)

    # Should get last 3, most recent first
    assert len(history) == 3
    assert history[0] == tracker.snapshots[-1]
    assert history[1] == tracker.snapshots[-2]
    assert history[2] == tracker.snapshots[-3]


def test_issue_tracker_clear():
    """Test clearing tracked data."""
    tracker = IssueTracker()

    # Add some data
    issue = create_test_issue("test")
    snapshot = IssueSnapshot(issues=[issue], total_issues=1)
    tracker.track_snapshot(snapshot)

    assert len(tracker.get_all_issues()) > 0
    assert len(tracker.snapshots) > 0

    # Clear
    tracker.clear()

    # Should be empty
    assert len(tracker.get_all_issues()) == 0
    assert len(tracker.snapshots) == 0
