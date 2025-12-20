"""
Issue Tracker - Issue lifecycle management.

Tracks issues across multiple pipeline runs:
- Deduplication using code_hash
- State transitions (new → resolved → reopened)
- Historical tracking
"""

from typing import List, Dict, Set
from datetime import datetime

from warden.issues.domain.models import WardenIssue, StateTransition
from warden.issues.domain.enums import IssueState
from warden.analysis.domain.models import IssueSnapshot
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)


class IssueTracker:
    """
    Tracks issue lifecycle across multiple runs.

    Responsibilities:
    - Deduplicate issues using code_hash
    - Detect new vs existing issues
    - Detect resolved issues
    - Detect reopened issues
    - Maintain issue history
    """

    def __init__(self) -> None:
        """Initialize issue tracker."""
        # In-memory storage (will be replaced with persistent storage)
        self.issues_by_hash: Dict[str, WardenIssue] = {}
        self.snapshots: List[IssueSnapshot] = []

    def track_snapshot(
        self,
        snapshot: IssueSnapshot,
        previous_snapshot: IssueSnapshot | None = None,
    ) -> Dict[str, List[WardenIssue]]:
        """
        Track issues from a new snapshot.

        Args:
            snapshot: Current issue snapshot
            previous_snapshot: Previous snapshot for comparison

        Returns:
            Dictionary with categorized issues:
            - new: First time detected
            - resolved: Previously detected, now fixed
            - reopened: Previously resolved, now back
            - persistent: Still present from last run
        """
        logger.info(
            "tracking_snapshot",
            snapshot_id=snapshot.id,
            total_issues=snapshot.total_issues,
        )

        result = {
            "new": [],
            "resolved": [],
            "reopened": [],
            "persistent": [],
        }

        if previous_snapshot is None:
            # First run - all issues are new
            result["new"] = snapshot.issues
            self._update_issue_store(snapshot.issues)
            self.snapshots.append(snapshot)

            logger.info(
                "first_snapshot",
                new_issues=len(result["new"]),
            )

            return result

        # Build hash sets for comparison
        current_hashes = {issue.code_hash for issue in snapshot.issues}
        previous_hashes = {issue.code_hash for issue in previous_snapshot.issues}
        stored_hashes = set(self.issues_by_hash.keys())

        # Categorize issues
        for issue in snapshot.issues:
            stored_issue = self.issues_by_hash.get(issue.code_hash)

            if issue.code_hash not in previous_hashes:
                if stored_issue and stored_issue.state == IssueState.RESOLVED:
                    # Issue was resolved but is back
                    issue.state = IssueState.OPEN
                    issue.reopen_count = stored_issue.reopen_count + 1
                    issue.state_history = stored_issue.state_history + [
                        StateTransition(
                            from_state=IssueState.RESOLVED,
                            to_state=IssueState.OPEN,
                            timestamp=datetime.utcnow(),
                            transitioned_by="system",
                            comment="Issue reappeared in code",
                        )
                    ]
                    result["reopened"].append(issue)

                    logger.debug(
                        "issue_reopened",
                        issue_hash=issue.code_hash,
                        reopen_count=issue.reopen_count,
                    )
                else:
                    # Truly new issue
                    result["new"].append(issue)

                    logger.debug(
                        "new_issue_detected",
                        issue_hash=issue.code_hash,
                        severity=issue.severity.name,
                    )

            else:
                # Issue still present
                if stored_issue:
                    # Update stored issue
                    issue.first_detected = stored_issue.first_detected
                    issue.reopen_count = stored_issue.reopen_count
                    issue.state_history = stored_issue.state_history

                result["persistent"].append(issue)

        # Detect resolved issues (in previous but not in current)
        for prev_issue in previous_snapshot.issues:
            if prev_issue.code_hash not in current_hashes:
                stored_issue = self.issues_by_hash.get(prev_issue.code_hash)

                if stored_issue:
                    # Mark as resolved
                    stored_issue.resolve(
                        resolved_by="system",
                        comment="Issue no longer detected in code",
                    )
                    result["resolved"].append(stored_issue)

                    logger.debug(
                        "issue_resolved",
                        issue_hash=stored_issue.code_hash,
                    )

        # Update issue store
        self._update_issue_store(snapshot.issues)

        # Store snapshot
        self.snapshots.append(snapshot)

        logger.info(
            "snapshot_tracked",
            new=len(result["new"]),
            resolved=len(result["resolved"]),
            reopened=len(result["reopened"]),
            persistent=len(result["persistent"]),
        )

        return result

    def _update_issue_store(self, issues: List[WardenIssue]) -> None:
        """Update internal issue store with latest issues."""
        for issue in issues:
            self.issues_by_hash[issue.code_hash] = issue

    def get_issue_by_hash(self, code_hash: str) -> WardenIssue | None:
        """Get issue by code hash."""
        return self.issues_by_hash.get(code_hash)

    def get_all_issues(self) -> List[WardenIssue]:
        """Get all tracked issues."""
        return list(self.issues_by_hash.values())

    def get_open_issues(self) -> List[WardenIssue]:
        """Get all open issues."""
        return [
            issue
            for issue in self.issues_by_hash.values()
            if issue.state == IssueState.OPEN
        ]

    def get_resolved_issues(self) -> List[WardenIssue]:
        """Get all resolved issues."""
        return [
            issue
            for issue in self.issues_by_hash.values()
            if issue.state == IssueState.RESOLVED
        ]

    def get_issue_count_by_state(self) -> Dict[IssueState, int]:
        """Get issue count by state."""
        counts = {state: 0 for state in IssueState}

        for issue in self.issues_by_hash.values():
            counts[issue.state] += 1

        return counts

    def get_latest_snapshot(self) -> IssueSnapshot | None:
        """Get the most recent snapshot."""
        if not self.snapshots:
            return None
        return self.snapshots[-1]

    def get_snapshot_history(self, limit: int = 10) -> List[IssueSnapshot]:
        """
        Get snapshot history.

        Args:
            limit: Maximum number of snapshots to return

        Returns:
            List of snapshots, most recent first
        """
        return list(reversed(self.snapshots[-limit:]))

    def clear(self) -> None:
        """Clear all tracked data (for testing)."""
        self.issues_by_hash.clear()
        self.snapshots.clear()

        logger.info("issue_tracker_cleared")
