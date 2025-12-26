"""
Result Analysis Mixin

Endpoints: AnalyzeResults, GetTrends, GetFrameStats, GetSeverityStats, GetQualityScore
"""

from datetime import datetime
from typing import Dict, List

try:
    from warden.grpc.generated import warden_pb2
except ImportError:
    warden_pb2 = None

try:
    from warden.shared.infrastructure.logging import get_logger
    logger = get_logger(__name__)
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


class ResultAnalysisMixin:
    """Result analysis endpoints (5 endpoints)."""

    async def AnalyzeResults(self, request, context) -> "warden_pb2.AnalysisResult":
        """Analyze pipeline results for trends."""
        logger.info("grpc_analyze_results")

        try:
            result = request.result

            new_issues = 0
            resolved_issues = 0

            for finding in result.findings:
                finding_hash = self.hash_finding(finding)
                if finding_hash not in self._issues:
                    new_issues += 1

            if result.total_findings == 0:
                quality_score = 100.0
            else:
                weighted = (
                    result.critical_count * 10 +
                    result.high_count * 5 +
                    result.medium_count * 2 +
                    result.low_count * 1
                )
                quality_score = max(0.0, 100.0 - weighted)

            if new_issues == 0 and resolved_issues > 0:
                trend = warden_pb2.IMPROVING
            elif new_issues > resolved_issues:
                trend = warden_pb2.DEGRADING
            else:
                trend = warden_pb2.STABLE

            return warden_pb2.AnalysisResult(
                success=True,
                trend=trend,
                quality_score=quality_score,
                new_issues=new_issues,
                resolved_issues=resolved_issues,
                persistent_issues=len(self._issues),
                analysis_timestamp=datetime.now().isoformat()
            )

        except Exception as e:
            logger.error("grpc_analyze_results_error: %s", str(e))
            return warden_pb2.AnalysisResult(success=False)

    async def GetTrends(self, request, context) -> "warden_pb2.TrendResponse":
        """Get trend data over time."""
        logger.info("grpc_get_trends", limit=request.limit)

        try:
            limit = request.limit if request.limit > 0 else 10

            response = warden_pb2.TrendResponse(
                overall_trend=warden_pb2.STABLE
            )

            for snapshot in self._issue_history[-limit:]:
                point = warden_pb2.TrendPoint(
                    timestamp=snapshot.get("timestamp", ""),
                    total_issues=snapshot.get("total_issues", 0),
                    quality_score=snapshot.get("quality_score", 0.0)
                )
                response.points.append(point)

            if len(response.points) >= 2:
                first = response.points[0].total_issues
                last = response.points[-1].total_issues
                if last < first:
                    response.overall_trend = warden_pb2.IMPROVING
                elif last > first:
                    response.overall_trend = warden_pb2.DEGRADING

            return response

        except Exception as e:
            logger.error("grpc_get_trends_error: %s", str(e))
            return warden_pb2.TrendResponse()

    async def GetFrameStats(self, request, context) -> "warden_pb2.FrameStats":
        """Get statistics per frame."""
        logger.info("grpc_get_frame_stats")

        try:
            response = warden_pb2.FrameStats()

            frame_issues: Dict[str, List[dict]] = {}
            for issue in self._issues.values():
                frame_id = issue.get("frame_id", "unknown")
                if frame_id not in frame_issues:
                    frame_issues[frame_id] = []
                frame_issues[frame_id].append(issue)

            for frame_id, issues in frame_issues.items():
                stat = warden_pb2.FrameStat(
                    frame_id=frame_id,
                    frame_name=frame_id.replace("_", " ").title(),
                    total_findings=len(issues),
                    critical=sum(1 for i in issues if i.get("severity") == "critical"),
                    high=sum(1 for i in issues if i.get("severity") == "high"),
                    medium=sum(1 for i in issues if i.get("severity") == "medium"),
                    low=sum(1 for i in issues if i.get("severity") == "low")
                )
                response.stats[frame_id].CopyFrom(stat)

            return response

        except Exception as e:
            logger.error("grpc_get_frame_stats_error: %s", str(e))
            return warden_pb2.FrameStats()

    async def GetSeverityStats(self, request, context) -> "warden_pb2.SeverityStats":
        """Get severity distribution statistics."""
        logger.info("grpc_get_severity_stats")

        try:
            issues = list(self._issues.values())

            critical = sum(1 for i in issues if i.get("severity") == "critical")
            high = sum(1 for i in issues if i.get("severity") == "high")
            medium = sum(1 for i in issues if i.get("severity") == "medium")
            low = sum(1 for i in issues if i.get("severity") == "low")
            info = sum(1 for i in issues if i.get("severity") == "info")

            weighted_score = (critical * 10 + high * 5 + medium * 2 + low * 1)

            return warden_pb2.SeverityStats(
                critical=critical,
                high=high,
                medium=medium,
                low=low,
                info=info,
                weighted_score=float(weighted_score)
            )

        except Exception as e:
            logger.error("grpc_get_severity_stats_error: %s", str(e))
            return warden_pb2.SeverityStats()

    async def GetQualityScore(self, request, context) -> "warden_pb2.QualityScoreResponse":
        """Get overall quality score."""
        logger.info("grpc_get_quality_score")

        try:
            issues = list(self._issues.values())

            if not issues:
                return warden_pb2.QualityScoreResponse(
                    score=100.0,
                    grade="A"
                )

            weighted = sum(
                10 if i.get("severity") == "critical" else
                5 if i.get("severity") == "high" else
                2 if i.get("severity") == "medium" else
                1 for i in issues
            )
            score = max(0.0, 100.0 - weighted)

            if score >= 90:
                grade = "A"
            elif score >= 80:
                grade = "B"
            elif score >= 70:
                grade = "C"
            elif score >= 60:
                grade = "D"
            else:
                grade = "F"

            response = warden_pb2.QualityScoreResponse(
                score=score,
                grade=grade
            )

            response.breakdown["security"] = score
            response.breakdown["code_quality"] = min(100.0, score + 10)
            response.breakdown["maintainability"] = min(100.0, score + 5)

            return response

        except Exception as e:
            logger.error("grpc_get_quality_score_error: %s", str(e))
            return warden_pb2.QualityScoreResponse(score=0.0, grade="F")
