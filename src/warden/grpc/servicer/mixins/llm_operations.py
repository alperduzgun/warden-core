"""
LLM Operations Mixin

Endpoints: AnalyzeWithLlm, ClassifyCode, TestLlmProvider, GetAvailableModels,
           ValidateLlmConfig
"""

import time

import grpc

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


class LlmOperationsMixin:
    """LLM operation endpoints (5 endpoints)."""

    async def AnalyzeWithLlm(self, request, context) -> "warden_pb2.LlmAnalyzeResult":
        """Analyze code with LLM."""
        logger.info("grpc_analyze_llm", provider=request.provider or "default")

        start_time = time.time()

        try:
            chunks = []
            provider_used = ""

            async for chunk in self.bridge.analyze_with_llm(
                code=request.code,
                prompt=request.prompt,
                provider=request.provider or None
            ):
                if chunk.get("type") == "chunk":
                    chunks.append(chunk.get("content", ""))
                elif chunk.get("type") == "complete":
                    provider_used = chunk.get("provider", "")

            duration_ms = int((time.time() - start_time) * 1000)

            return warden_pb2.LlmAnalyzeResult(
                success=True,
                response="".join(chunks),
                provider_used=provider_used,
                duration_ms=duration_ms
            )

        except Exception as e:
            logger.error("grpc_llm_error: %s", str(e))
            return warden_pb2.LlmAnalyzeResult(
                success=False,
                error=warden_pb2.LlmError(
                    code="LLM_ERROR",
                    message=str(e)
                )
            )

    async def ClassifyCode(self, request, context) -> "warden_pb2.ClassifyResult":
        """Classify code to determine recommended frames."""
        logger.info("grpc_classify_code")

        try:
            result = await self.bridge.classify_code(
                code=request.code,
                file_path=request.file_path or None
            )

            return warden_pb2.ClassifyResult(
                has_async_operations=result.get("has_async_operations", False),
                has_user_input=result.get("has_user_input", False),
                has_database_operations=result.get("has_database_operations", False),
                has_network_calls=result.get("has_network_calls", False),
                has_file_operations=result.get("has_file_operations", False),
                has_authentication=result.get("has_authentication", False),
                has_cryptography=result.get("has_cryptography", False),
                detected_frameworks=result.get("detected_frameworks", []),
                recommended_frames=result.get("recommended_frames", []),
                confidence=result.get("confidence", 0.0)
            )

        except Exception as e:
            logger.error("grpc_classify_error: %s", str(e))
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return warden_pb2.ClassifyResult()

    async def TestLlmProvider(self, request, context) -> "warden_pb2.TestProviderResponse":
        """Test LLM provider connectivity."""
        logger.info("grpc_test_llm_provider", provider=request.provider)

        try:
            start_time = time.time()

            if hasattr(self.bridge, 'test_provider'):
                result = await self.bridge.test_provider(
                    provider=request.provider,
                    prompt=request.prompt or "Hello, respond with OK"
                )

                return warden_pb2.TestProviderResponse(
                    success=result.get("success", False),
                    provider=request.provider,
                    model=result.get("model", ""),
                    latency_ms=int((time.time() - start_time) * 1000),
                    error_message=result.get("error", "")
                )

            async for chunk in self.bridge.analyze_with_llm(
                code="print('test')",
                prompt="Say OK",
                provider=request.provider
            ):
                if chunk.get("type") == "complete":
                    return warden_pb2.TestProviderResponse(
                        success=True,
                        provider=request.provider,
                        model=chunk.get("model", ""),
                        latency_ms=int((time.time() - start_time) * 1000)
                    )

            return warden_pb2.TestProviderResponse(
                success=False,
                provider=request.provider,
                error_message="No response from provider"
            )

        except Exception as e:
            logger.error("grpc_test_provider_error: %s", str(e))
            return warden_pb2.TestProviderResponse(
                success=False,
                provider=request.provider,
                error_message=str(e)
            )

    async def GetAvailableModels(
        self, request, context
    ) -> "warden_pb2.AvailableModelsResponse":
        """Get available models for a provider."""
        logger.info("grpc_get_available_models", provider=request.provider)

        try:
            if hasattr(self.bridge, 'get_available_models'):
                result = await self.bridge.get_available_models(provider=request.provider)

                response = warden_pb2.AvailableModelsResponse()
                for model in result.get("models", []):
                    response.models.append(warden_pb2.LlmModel(
                        id=model.get("id", ""),
                        name=model.get("name", ""),
                        provider=request.provider,
                        max_tokens=model.get("max_tokens", 0),
                        available=model.get("available", True)
                    ))

                return response

            response = warden_pb2.AvailableModelsResponse()

            if request.provider == "anthropic":
                response.models.append(warden_pb2.LlmModel(
                    id="claude-3-5-sonnet-20241022",
                    name="Claude 3.5 Sonnet",
                    provider="anthropic",
                    max_tokens=8192,
                    available=True
                ))
            elif request.provider == "openai":
                response.models.append(warden_pb2.LlmModel(
                    id="gpt-4-turbo",
                    name="GPT-4 Turbo",
                    provider="openai",
                    max_tokens=4096,
                    available=True
                ))

            return response

        except Exception as e:
            logger.error("grpc_get_models_error: %s", str(e))
            return warden_pb2.AvailableModelsResponse()

    async def ValidateLlmConfig(
        self, request, context
    ) -> "warden_pb2.ValidateLlmConfigResponse":
        """Validate LLM configuration."""
        logger.info("grpc_validate_llm_config", provider=request.provider)

        try:
            errors = []
            warnings = []

            if not request.provider:
                errors.append("Provider is required")

            config = dict(request.config)

            if request.provider == "anthropic":
                if "api_key" not in config and "ANTHROPIC_API_KEY" not in config:
                    warnings.append(
                        "API key not found in config (may be set via environment)"
                    )
            elif request.provider == "openai":
                if "api_key" not in config and "OPENAI_API_KEY" not in config:
                    warnings.append(
                        "API key not found in config (may be set via environment)"
                    )

            return warden_pb2.ValidateLlmConfigResponse(
                valid=len(errors) == 0,
                errors=errors,
                warnings=warnings
            )

        except Exception as e:
            logger.error("grpc_validate_config_error: %s", str(e))
            return warden_pb2.ValidateLlmConfigResponse(
                valid=False,
                errors=[str(e)]
            )
