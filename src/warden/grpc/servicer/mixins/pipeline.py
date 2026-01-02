"""
Pipeline Operations Mixin

Endpoints: ExecutePipeline, ExecutePipelineStream
"""

import time
from typing import AsyncIterator

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


class PipelineMixin:
    """Pipeline operation endpoints."""

    async def ExecutePipeline(self, request, context) -> "warden_pb2.PipelineResult":
        """Execute full validation pipeline."""
        logger.info("grpc_execute_pipeline", path=request.path, frames=list(request.frames))

        start_time = time.time()

        try:
            frames = list(request.frames) if request.frames else None

            result = await self.bridge.execute_pipeline(
                path=request.path,
                frames=frames
            )

            duration_ms = int((time.time() - start_time) * 1000)
            self.total_scans += 1

            response = warden_pb2.PipelineResult(
                success=result.get("success", False),
                run_id=result.get("run_id", ""),
                total_findings=result.get("total_findings", 0),
                critical_count=result.get("critical_count", 0),
                high_count=result.get("high_count", 0),
                medium_count=result.get("medium_count", 0),
                low_count=result.get("low_count", 0),
                duration_ms=duration_ms,
                frames_executed=result.get("frames_executed", []),
                error_message=result.get("error", "")
            )

            for finding in result.get("findings", []):
                response.findings.append(ProtoConverters.convert_finding(finding))
                self.track_issue(finding)

            for fort in result.get("fortifications", []):
                response.fortifications.append(ProtoConverters.convert_fortification(fort))

            for clean in result.get("cleanings", []):
                response.cleanings.append(ProtoConverters.convert_cleaning(clean))

            self.total_findings += response.total_findings
            logger.info(
                "grpc_pipeline_complete",
                findings=response.total_findings,
                duration_ms=duration_ms
            )

            return response

        except Exception as e:
            logger.error("grpc_pipeline_error: %s", str(e))
            return warden_pb2.PipelineResult(
                success=False,
                error_message=str(e)
            )

    async def ExecutePipelineStream(
        self, request, context
    ) -> AsyncIterator["warden_pb2.PipelineEvent"]:
        """Execute pipeline with streaming progress events."""
        logger.info("grpc_execute_pipeline_stream", path=request.path)

        try:
            yield warden_pb2.PipelineEvent(
                event_type="pipeline_start",
                message=f"Starting pipeline for {request.path}",
                timestamp_ms=int(time.time() * 1000)
            )

            frames = list(request.frames) if request.frames else None

            async for event in self.bridge.execute_pipeline_stream(
                path=request.path,
                frames=frames
            ):
                proto_event = warden_pb2.PipelineEvent(
                    event_type=event.get("type", "progress"),
                    stage=event.get("stage", ""),
                    progress=event.get("progress", 0.0),
                    message=event.get("message", ""),
                    timestamp_ms=int(time.time() * 1000)
                )

                if "finding" in event:
                    proto_event.finding.CopyFrom(
                        ProtoConverters.convert_finding(event["finding"])
                    )

                yield proto_event

            yield warden_pb2.PipelineEvent(
                event_type="pipeline_complete",
                progress=1.0,
                message="Pipeline completed",
                timestamp_ms=int(time.time() * 1000)
            )

        except Exception as e:
            logger.error("grpc_stream_error: %s", str(e))
            yield warden_pb2.PipelineEvent(
                event_type="error",
                message=str(e),
                timestamp_ms=int(time.time() * 1000)
            )
