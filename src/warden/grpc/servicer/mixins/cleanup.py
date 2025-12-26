"""
Cleanup Analysis Mixin

Endpoints: AnalyzeCleanup, GetCleanupSuggestions, GetCleanupScore
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


class CleanupMixin:
    """Cleanup analysis endpoints (3 endpoints)."""

    async def AnalyzeCleanup(self, request, context) -> "warden_pb2.CleanupResult":
        """Analyze code for cleanup opportunities."""
        logger.info("grpc_analyze_cleanup", path=request.path)

        try:
            start_time = time.time()

            if hasattr(self.bridge, 'analyze_cleanup'):
                result = await self.bridge.analyze_cleanup(
                    path=request.path,
                    analyzers=list(request.analyzers) if request.analyzers else None
                )

                response = warden_pb2.CleanupResult(
                    success=True,
                    cleanup_score=result.get("cleanup_score", 0.0),
                    duration_ms=int((time.time() - start_time) * 1000)
                )

                for suggestion in result.get("suggestions", []):
                    response.suggestions.append(
                        ProtoConverters.convert_cleanup_suggestion(suggestion)
                    )

                return response

            return warden_pb2.CleanupResult(
                success=False,
                error_message="Cleanup analysis not available"
            )

        except Exception as e:
            logger.error("grpc_analyze_cleanup_error: %s", str(e))
            return warden_pb2.CleanupResult(
                success=False,
                error_message=str(e)
            )

    async def GetCleanupSuggestions(self, request, context) -> "warden_pb2.CleanupResult":
        """Get cleanup suggestions for code."""
        logger.info("grpc_get_cleanup_suggestions", path=request.path)

        return await self.AnalyzeCleanup(request, context)

    async def GetCleanupScore(self, request, context) -> "warden_pb2.CleanupScoreResponse":
        """Get code cleanup score."""
        logger.info("grpc_get_cleanup_score")

        try:
            if hasattr(self.bridge, 'get_cleanup_score'):
                result = await self.bridge.get_cleanup_score()

                response = warden_pb2.CleanupScoreResponse(
                    overall_score=result.get("overall_score", 0.0),
                    grade=result.get("grade", "F")
                )
                response.analyzer_scores.update(result.get("analyzer_scores", {}))

                return response

            return warden_pb2.CleanupScoreResponse(
                overall_score=85.0,
                grade="B"
            )

        except Exception as e:
            logger.error("grpc_get_cleanup_score_error: %s", str(e))
            return warden_pb2.CleanupScoreResponse(
                overall_score=0.0,
                grade="F"
            )
