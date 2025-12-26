"""
Configuration Mixin

Endpoints: GetAvailableFrames, GetAvailableProviders, GetConfiguration,
           UpdateConfiguration, UpdateFrameStatus
"""

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


class ConfigurationMixin:
    """Configuration endpoints (5 endpoints)."""

    async def GetAvailableFrames(self, request, context) -> "warden_pb2.FrameList":
        """Get available validation frames."""
        logger.info("grpc_get_frames")

        try:
            result = await self.bridge.get_available_frames()

            frames = result if isinstance(result, list) else result.get("frames", [])

            response = warden_pb2.FrameList()
            for frame in frames:
                priority = frame.get("priority", 0)
                if isinstance(priority, str):
                    priority_map = {
                        "critical": 1,
                        "high": 2,
                        "medium": 3,
                        "low": 4,
                        "info": 5
                    }
                    priority = priority_map.get(priority.lower(), 0)

                response.frames.append(warden_pb2.Frame(
                    id=frame.get("id", ""),
                    name=frame.get("name", ""),
                    description=frame.get("description", ""),
                    priority=priority,
                    is_blocker=frame.get("is_blocker", False),
                    enabled=frame.get("enabled", True),
                    tags=frame.get("tags", [])
                ))

            return response

        except Exception as e:
            logger.error("grpc_frames_error: %s", str(e))
            return warden_pb2.FrameList()

    async def GetAvailableProviders(self, request, context) -> "warden_pb2.ProviderList":
        """Get available LLM providers."""
        logger.info("grpc_get_providers")

        try:
            result = await self.bridge.get_available_providers()

            if isinstance(result, list):
                providers = result
                default_provider = ""
            else:
                providers = result.get("providers", [])
                default_provider = result.get("default", "")

            response = warden_pb2.ProviderList(default_provider=default_provider)

            for provider in providers:
                response.providers.append(warden_pb2.Provider(
                    id=provider.get("id", provider.get("name", "")),
                    name=provider.get("name", ""),
                    available=provider.get("available", True),
                    is_default=provider.get("is_default", False),
                    status=provider.get("status", "ready")
                ))

            return response

        except Exception as e:
            logger.error("grpc_providers_error: %s", str(e))
            return warden_pb2.ProviderList()

    async def GetConfiguration(
        self, request, context
    ) -> "warden_pb2.ConfigurationResponse":
        """Get full configuration."""
        logger.info("grpc_get_config")

        try:
            config = await self.bridge.get_config()
            frames = await self.bridge.get_available_frames()
            providers_result = await self.bridge.get_available_providers()

            response = warden_pb2.ConfigurationResponse(
                project_root=str(self.bridge.project_root),
                config_file=config.get("config_file", ""),
                active_profile=config.get("active_profile", "default")
            )

            frames_list = frames if isinstance(frames, list) else frames.get("frames", [])
            for frame in frames_list:
                priority = frame.get("priority", 0)
                if isinstance(priority, str):
                    priority_map = {
                        "critical": 1,
                        "high": 2,
                        "medium": 3,
                        "low": 4,
                        "info": 5
                    }
                    priority = priority_map.get(priority.lower(), 0)

                response.available_frames.frames.append(warden_pb2.Frame(
                    id=frame.get("id", ""),
                    name=frame.get("name", ""),
                    description=frame.get("description", ""),
                    priority=priority,
                    is_blocker=frame.get("is_blocker", False),
                    enabled=frame.get("enabled", True)
                ))

            providers = (
                providers_result if isinstance(providers_result, list)
                else providers_result.get("providers", [])
            )
            for provider in providers:
                response.available_providers.providers.append(warden_pb2.Provider(
                    id=provider.get("id", provider.get("name", "")),
                    name=provider.get("name", ""),
                    available=provider.get("available", True),
                    is_default=provider.get("is_default", False)
                ))

            return response

        except Exception as e:
            logger.error("grpc_config_error: %s", str(e))
            return warden_pb2.ConfigurationResponse()

    async def UpdateConfiguration(
        self, request, context
    ) -> "warden_pb2.UpdateConfigResponse":
        """Update configuration settings."""
        logger.info("grpc_update_config")

        try:
            settings = dict(request.settings)

            if hasattr(self.bridge, 'update_config'):
                await self.bridge.update_config(settings)

            return warden_pb2.UpdateConfigResponse(success=True)

        except Exception as e:
            logger.error("grpc_update_config_error: %s", str(e))
            return warden_pb2.UpdateConfigResponse(
                success=False,
                error_message=str(e)
            )

    async def UpdateFrameStatus(
        self, request, context
    ) -> "warden_pb2.UpdateFrameStatusResponse":
        """Enable or disable a frame."""
        logger.info(
            "grpc_update_frame_status",
            frame_id=request.frame_id,
            enabled=request.enabled
        )

        try:
            if hasattr(self.bridge, 'update_frame_status'):
                await self.bridge.update_frame_status(
                    frame_id=request.frame_id,
                    enabled=request.enabled
                )

                return warden_pb2.UpdateFrameStatusResponse(
                    success=True,
                    frame=warden_pb2.Frame(
                        id=request.frame_id,
                        enabled=request.enabled
                    )
                )

            return warden_pb2.UpdateFrameStatusResponse(
                success=False,
                error_message="Frame status update not available"
            )

        except Exception as e:
            logger.error("grpc_update_frame_error: %s", str(e))
            return warden_pb2.UpdateFrameStatusResponse(
                success=False,
                error_message=str(e)
            )
