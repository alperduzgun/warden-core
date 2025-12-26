"""
Health & Status Mixin

Endpoints: HealthCheck, GetStatus
"""

from datetime import datetime

import psutil

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


class HealthStatusMixin:
    """Health and status endpoints (2 endpoints)."""

    async def HealthCheck(self, request, context) -> "warden_pb2.HealthResponse":
        """Health check."""
        uptime = (datetime.now() - self.start_time).total_seconds()

        components = {
            "bridge": self.bridge is not None,
            "orchestrator": (
                self.bridge.orchestrator is not None if self.bridge else False
            )
        }

        try:
            providers = await self.bridge.get_available_providers()
            providers_list = (
                providers if isinstance(providers, list)
                else providers.get("providers", [])
            )
            components["llm"] = any(p.get("available") for p in providers_list)
        except Exception:
            components["llm"] = False

        return warden_pb2.HealthResponse(
            healthy=all(components.values()),
            version="1.0.0",
            uptime_seconds=int(uptime),
            components=components
        )

    async def GetStatus(self, request, context) -> "warden_pb2.StatusResponse":
        """Get server status."""
        process = psutil.Process()

        return warden_pb2.StatusResponse(
            running=True,
            active_pipelines=0,
            total_scans=self.total_scans,
            total_findings=self.total_findings,
            memory_mb=int(process.memory_info().rss / 1024 / 1024),
            cpu_percent=process.cpu_percent()
        )
