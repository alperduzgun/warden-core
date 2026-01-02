"""
Suppression Mixin

Endpoints: AddSuppression, RemoveSuppression, GetSuppressions, CheckSuppression

Uses repository pattern for persistent storage.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

try:
    from warden.grpc.generated import warden_pb2
except ImportError:
    warden_pb2 = None

from warden.grpc.converters import ProtoConverters

if TYPE_CHECKING:
    from warden.shared.domain.repository import ISuppressionRepository

try:
    from warden.shared.infrastructure.logging import get_logger

    logger = get_logger(__name__)
except ImportError:
    import logging

    logger = logging.getLogger(__name__)


class SuppressionMixin:
    """Suppression endpoints (4 endpoints) with repository persistence."""

    async def AddSuppression(
        self, request, context
    ) -> "warden_pb2.AddSuppressionResponse":
        """Add a suppression rule with persistence."""
        logger.info("grpc_add_suppression", rule_id=request.rule_id)

        try:
            suppression_id = str(uuid.uuid4())

            suppression = {
                "id": suppression_id,
                "rule_id": request.rule_id,
                "file_path": request.file_path,
                "line_number": request.line_number,
                "justification": request.justification,
                "created_by": request.created_by,
                "created_at": datetime.now().isoformat(),
                "expires_at": request.expires_at or None,
                "is_global": request.is_global,
                "enabled": True,
            }

            # Save to in-memory cache
            self._suppressions[suppression_id] = suppression

            # Persist to repository
            await self.suppression_repository.save(suppression)

            return warden_pb2.AddSuppressionResponse(
                success=True,
                suppression=ProtoConverters.convert_suppression(suppression),
            )

        except Exception as e:
            logger.error("grpc_add_suppression_error: %s", str(e))
            return warden_pb2.AddSuppressionResponse(
                success=False, error_message=str(e)
            )

    async def RemoveSuppression(
        self, request, context
    ) -> "warden_pb2.RemoveSuppressionResponse":
        """Remove a suppression rule with persistence."""
        logger.info("grpc_remove_suppression", suppression_id=request.suppression_id)

        try:
            if request.suppression_id not in self._suppressions:
                return warden_pb2.RemoveSuppressionResponse(
                    success=False,
                    error_message=f"Suppression {request.suppression_id} not found",
                )

            # Remove from in-memory cache
            del self._suppressions[request.suppression_id]

            # Delete from repository
            await self.suppression_repository.delete(request.suppression_id)

            return warden_pb2.RemoveSuppressionResponse(success=True)

        except Exception as e:
            logger.error("grpc_remove_suppression_error: %s", str(e))
            return warden_pb2.RemoveSuppressionResponse(
                success=False, error_message=str(e)
            )

    async def GetSuppressions(self, request, context) -> "warden_pb2.SuppressionList":
        """Get all suppression rules."""
        logger.info("grpc_get_suppressions")

        try:
            response = warden_pb2.SuppressionList(
                total_count=len(self._suppressions)
            )

            for suppression in self._suppressions.values():
                response.suppressions.append(
                    ProtoConverters.convert_suppression(suppression)
                )

            return response

        except Exception as e:
            logger.error("grpc_get_suppressions_error: %s", str(e))
            return warden_pb2.SuppressionList()

    async def CheckSuppression(
        self, request, context
    ) -> "warden_pb2.CheckSuppressionResponse":
        """Check if an issue is suppressed."""
        logger.info("grpc_check_suppression", rule_id=request.rule_id)

        try:
            for suppression in self._suppressions.values():
                if (suppression.get("is_global") and
                        suppression.get("rule_id") == request.rule_id):
                    return warden_pb2.CheckSuppressionResponse(
                        is_suppressed=True,
                        suppression=ProtoConverters.convert_suppression(suppression),
                        reason="Global suppression rule"
                    )

                if (suppression.get("rule_id") == request.rule_id and
                        suppression.get("file_path") == request.file_path):
                    if (suppression.get("line_number", 0) == 0 or
                            suppression.get("line_number") == request.line_number):
                        return warden_pb2.CheckSuppressionResponse(
                            is_suppressed=True,
                            suppression=ProtoConverters.convert_suppression(suppression),
                            reason="File-specific suppression rule"
                        )

            return warden_pb2.CheckSuppressionResponse(
                is_suppressed=False,
                reason="No matching suppression rule"
            )

        except Exception as e:
            logger.error("grpc_check_suppression_error: %s", str(e))
            return warden_pb2.CheckSuppressionResponse(
                is_suppressed=False,
                reason=str(e)
            )
