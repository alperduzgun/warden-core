"""
Fortification Mixin

Endpoints: GetFortificationSuggestions, ApplyFortification, GetSecurityScore
"""

import time

try:
    from warden.grpc.generated import warden_pb2
except ImportError:
    warden_pb2 = None

from warden.grpc.converters import ProtoConverters

try:
    from warden.shared.infrastructure.logging import get_logger
    logger = get_logger(__name__)
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


class FortificationMixin:
    """Fortification endpoints (3 endpoints)."""

    async def GetFortificationSuggestions(
        self, request, context
    ) -> "warden_pb2.FortificationResult":
        """Get security fortification suggestions."""
        logger.info("grpc_get_fortification_suggestions", path=request.path)

        try:
            start_time = time.time()

            if hasattr(self.bridge, 'get_fortification_suggestions'):
                result = await self.bridge.get_fortification_suggestions(
                    path=request.path,
                    fortifiers=list(request.fortifiers) if request.fortifiers else None
                )

                response = warden_pb2.FortificationResult(
                    success=True,
                    security_score=result.get("security_score", 0.0),
                    duration_ms=int((time.time() - start_time) * 1000)
                )

                for suggestion in result.get("suggestions", []):
                    response.suggestions.append(
                        ProtoConverters.convert_fortification_suggestion(suggestion)
                    )

                return response

            return warden_pb2.FortificationResult(
                success=False,
                error_message="Fortification analysis not available"
            )

        except Exception as e:
            logger.error("grpc_get_fortification_error: %s", str(e))
            return warden_pb2.FortificationResult(
                success=False,
                error_message=str(e)
            )

    async def ApplyFortification(
        self, request, context
    ) -> "warden_pb2.ApplyFortificationResponse":
        """Apply a fortification suggestion."""
        logger.info("grpc_apply_fortification", suggestion_id=request.suggestion_id)

        try:
            if hasattr(self.bridge, 'apply_fortification'):
                result = await self.bridge.apply_fortification(
                    suggestion_id=request.suggestion_id,
                    dry_run=request.dry_run
                )

                return warden_pb2.ApplyFortificationResponse(
                    success=result.get("success", False),
                    file_path=result.get("file_path", ""),
                    diff=result.get("diff", ""),
                    error_message=result.get("error", "")
                )

            return warden_pb2.ApplyFortificationResponse(
                success=False,
                error_message="Fortification application not available"
            )

        except Exception as e:
            logger.error("grpc_apply_fortification_error: %s", str(e))
            return warden_pb2.ApplyFortificationResponse(
                success=False,
                error_message=str(e)
            )

    async def GetSecurityScore(self, request, context) -> "warden_pb2.SecurityScoreResponse":
        """Get overall security score."""
        logger.info("grpc_get_security_score")

        try:
            issues = list(self._issues.values())

            if not issues:
                score = 100.0
            else:
                security_issues = [
                    i for i in issues if i.get("frame_id") == "security"
                ]
                weighted = sum(
                    10 if i.get("severity") == "critical" else
                    5 if i.get("severity") == "high" else
                    2 if i.get("severity") == "medium" else
                    1 for i in security_issues
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

            response = warden_pb2.SecurityScoreResponse(
                overall_score=score,
                grade=grade
            )

            response.category_scores["authentication"] = min(100.0, score + 5)
            response.category_scores["authorization"] = min(100.0, score + 3)
            response.category_scores["injection"] = score
            response.category_scores["cryptography"] = min(100.0, score + 10)

            for issue in issues[:10]:
                if issue.get("severity") in ["critical", "high"]:
                    response.vulnerabilities.append(issue.get("title", ""))

            return response

        except Exception as e:
            logger.error("grpc_get_security_score_error: %s", str(e))
            return warden_pb2.SecurityScoreResponse(
                overall_score=0.0,
                grade="F"
            )
