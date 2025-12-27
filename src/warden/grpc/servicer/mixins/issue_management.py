"""
Issue Management Mixin

Endpoints: GetAllIssues, GetOpenIssues, GetIssueByHash, ResolveIssue,
           SuppressIssue, ReopenIssue, GetIssueHistory, GetIssueStats

Uses repository pattern for persistent storage.
"""

import fnmatch
from datetime import datetime
from typing import TYPE_CHECKING

import grpc

try:
    from warden.grpc.generated import warden_pb2
except ImportError:
    warden_pb2 = None

from warden.grpc.converters import ProtoConverters

if TYPE_CHECKING:
    from warden.shared.domain.repository import IIssueHistoryRepository

try:
    from warden.shared.infrastructure.logging import get_logger

    logger = get_logger(__name__)
except ImportError:
    import logging

    logger = logging.getLogger(__name__)


class IssueManagementMixin:
    """Issue management endpoints (8 endpoints)."""

    async def GetAllIssues(self, request, context) -> "warden_pb2.IssueList":
        """Get all issues with optional filtering."""
        logger.info("grpc_get_all_issues")

        try:
            issues = list(self._issues.values())

            if request.states:
                state_values = [s for s in request.states]
                issues = [i for i in issues if i.get("state") in state_values]

            if request.severities:
                sev_values = [s for s in request.severities]
                issues = [i for i in issues if i.get("severity") in sev_values]

            if request.frame_ids:
                frame_ids = list(request.frame_ids)
                issues = [i for i in issues if i.get("frame_id") in frame_ids]

            if request.file_path_pattern:
                pattern = request.file_path_pattern
                issues = [
                    i for i in issues
                    if fnmatch.fnmatch(i.get("file_path", ""), pattern)
                ]

            total_count = len(issues)

            if request.offset > 0:
                issues = issues[request.offset:]
            if request.limit > 0:
                issues = issues[:request.limit]

            response = warden_pb2.IssueList(
                total_count=total_count,
                filtered_count=len(issues)
            )

            for issue in issues:
                response.issues.append(ProtoConverters.convert_issue(issue))

            return response

        except Exception as e:
            logger.error("grpc_get_all_issues_error: %s", str(e))
            return warden_pb2.IssueList()

    async def GetOpenIssues(self, request, context) -> "warden_pb2.IssueList":
        """Get only open issues."""
        logger.info("grpc_get_open_issues")
        request.states.append(warden_pb2.OPEN)
        return await self.GetAllIssues(request, context)

    async def GetIssueByHash(self, request, context) -> "warden_pb2.Issue":
        """Get issue by content hash."""
        logger.info("grpc_get_issue_by_hash", hash=request.hash)

        try:
            for issue in self._issues.values():
                if issue.get("hash") == request.hash:
                    return ProtoConverters.convert_issue(issue)

            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(f"Issue with hash {request.hash} not found")
            return warden_pb2.Issue()

        except Exception as e:
            logger.error("grpc_get_issue_hash_error: %s", str(e))
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return warden_pb2.Issue()

    async def ResolveIssue(self, request, context) -> "warden_pb2.IssueActionResponse":
        """Mark issue as resolved with persistence."""
        logger.info("grpc_resolve_issue", issue_id=request.issue_id)

        try:
            if request.issue_id not in self._issues:
                return warden_pb2.IssueActionResponse(
                    success=False,
                    error_message=f"Issue {request.issue_id} not found",
                )

            issue = self._issues[request.issue_id]
            old_state = issue.get("state", "open")
            issue["state"] = "resolved"
            issue["resolved_at"] = datetime.now().isoformat()
            issue["resolved_by"] = request.actor

            # Log state change to history repository
            await self.history_repository.add_event(
                issue_id=request.issue_id,
                event={
                    "event_type": "state_changed",
                    "from_state": old_state,
                    "to_state": "resolved",
                    "actor": request.actor,
                    "comment": request.comment if hasattr(request, "comment") else "",
                },
            )

            return warden_pb2.IssueActionResponse(
                success=True, issue=ProtoConverters.convert_issue(issue)
            )

        except Exception as e:
            logger.error("grpc_resolve_issue_error: %s", str(e))
            return warden_pb2.IssueActionResponse(
                success=False, error_message=str(e)
            )

    async def SuppressIssue(self, request, context) -> "warden_pb2.IssueActionResponse":
        """Mark issue as suppressed (false positive) with persistence."""
        logger.info("grpc_suppress_issue", issue_id=request.issue_id)

        try:
            if request.issue_id not in self._issues:
                return warden_pb2.IssueActionResponse(
                    success=False,
                    error_message=f"Issue {request.issue_id} not found",
                )

            issue = self._issues[request.issue_id]
            old_state = issue.get("state", "open")
            issue["state"] = "suppressed"
            issue["suppressed_at"] = datetime.now().isoformat()
            issue["suppressed_by"] = request.actor
            issue["suppression_reason"] = request.comment

            # Log state change to history repository
            await self.history_repository.add_event(
                issue_id=request.issue_id,
                event={
                    "event_type": "state_changed",
                    "from_state": old_state,
                    "to_state": "suppressed",
                    "actor": request.actor,
                    "comment": request.comment,
                },
            )

            return warden_pb2.IssueActionResponse(
                success=True, issue=ProtoConverters.convert_issue(issue)
            )

        except Exception as e:
            logger.error("grpc_suppress_issue_error: %s", str(e))
            return warden_pb2.IssueActionResponse(
                success=False, error_message=str(e)
            )

    async def ReopenIssue(self, request, context) -> "warden_pb2.IssueActionResponse":
        """Reopen a resolved/suppressed issue with persistence."""
        logger.info("grpc_reopen_issue", issue_id=request.issue_id)

        try:
            if request.issue_id not in self._issues:
                return warden_pb2.IssueActionResponse(
                    success=False,
                    error_message=f"Issue {request.issue_id} not found",
                )

            issue = self._issues[request.issue_id]
            old_state = issue.get("state", "open")
            issue["state"] = "open"
            issue["resolved_at"] = None
            issue["suppressed_at"] = None
            issue["reopen_count"] = issue.get("reopen_count", 0) + 1

            # Log state change to history repository
            await self.history_repository.add_event(
                issue_id=request.issue_id,
                event={
                    "event_type": "state_changed",
                    "from_state": old_state,
                    "to_state": "open",
                    "actor": request.actor,
                    "comment": request.comment if hasattr(request, "comment") else "",
                },
            )

            return warden_pb2.IssueActionResponse(
                success=True, issue=ProtoConverters.convert_issue(issue)
            )

        except Exception as e:
            logger.error("grpc_reopen_issue_error: %s", str(e))
            return warden_pb2.IssueActionResponse(
                success=False, error_message=str(e)
            )

    async def GetIssueHistory(self, request, context) -> "warden_pb2.IssueHistory":
        """Get issue history from repository."""
        logger.info("grpc_get_issue_history")

        try:
            response = warden_pb2.IssueHistory()

            # Get events from history repository
            events = await self.history_repository.get_all_events(limit=50)

            for event in events:
                proto_snapshot = warden_pb2.IssueSnapshot(
                    snapshot_id=event.get("issue_id", ""),
                    timestamp=event.get("timestamp", ""),
                    run_id=event.get("run_id", ""),
                    total_issues=event.get("total_issues", 0),
                    new_issues=1 if event.get("event_type") == "issue_created" else 0,
                    resolved_issues=(
                        1 if event.get("to_state") == "resolved" else 0
                    ),
                    reopened_issues=1 if event.get("to_state") == "open" else 0,
                )
                response.snapshots.append(proto_snapshot)

            return response

        except Exception as e:
            logger.error("grpc_get_issue_history_error: %s", str(e))
            return warden_pb2.IssueHistory()

    async def GetIssueStats(self, request, context) -> "warden_pb2.IssueStats":
        """Get issue statistics."""
        logger.info("grpc_get_issue_stats")

        try:
            issues = list(self._issues.values())

            stats = warden_pb2.IssueStats(
                total=len(issues),
                open=sum(1 for i in issues if i.get("state") == "open"),
                resolved=sum(1 for i in issues if i.get("state") == "resolved"),
                suppressed=sum(1 for i in issues if i.get("state") == "suppressed"),
                critical=sum(1 for i in issues if i.get("severity") == "critical"),
                high=sum(1 for i in issues if i.get("severity") == "high"),
                medium=sum(1 for i in issues if i.get("severity") == "medium"),
                low=sum(1 for i in issues if i.get("severity") == "low"),
                info=sum(1 for i in issues if i.get("severity") == "info")
            )

            frame_counts = {}
            for issue in issues:
                frame_id = issue.get("frame_id", "unknown")
                frame_counts[frame_id] = frame_counts.get(frame_id, 0) + 1
            stats.by_frame.update(frame_counts)

            file_counts = {}
            for issue in issues:
                file_path = issue.get("file_path", "unknown")
                file_counts[file_path] = file_counts.get(file_path, 0) + 1
            top_files = dict(
                sorted(file_counts.items(), key=lambda x: x[1], reverse=True)[:10]
            )
            stats.by_file.update(top_files)

            return stats

        except Exception as e:
            logger.error("grpc_get_issue_stats_error: %s", str(e))
            return warden_pb2.IssueStats()
