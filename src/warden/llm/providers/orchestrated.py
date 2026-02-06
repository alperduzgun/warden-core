from typing import Optional, List
import asyncio
from ..types import LlmProvider, LlmRequest, LlmResponse
from .base import ILlmClient
from warden.shared.infrastructure.logging import get_logger
from warden.shared.infrastructure.resilience import resilient

logger = get_logger(__name__)


class OrchestratedLlmClient(ILlmClient):
    """
    Proxy client implementing tiered LLM execution.
    
    Routes:
    - use_fast_tier=True -> Routes to Fast Providers in priority order (e.g. [Ollama, Groq])
    - use_fast_tier=False -> Routes to Smart Provider (e.g. Azure/OpenAI)
    - Fallback -> If all fast providers fail, falls back to the smart tier.
    """

    def __init__(
        self, 
        smart_client: ILlmClient, 
        fast_clients: Optional[List[ILlmClient]] = None,
        smart_model: Optional[str] = None,
        fast_model: Optional[str] = None,
        metrics_collector = None
    ):
        self.smart_client = smart_client
        self.fast_clients = fast_clients or []
        self.smart_model = smart_model
        self.fast_model = fast_model
        
        # Initialize metrics collector
        if metrics_collector is None:
            from warden.llm.metrics import LLMMetricsCollector
            metrics_collector = LLMMetricsCollector()
        self.metrics = metrics_collector
        
        if not self.fast_clients:
            logger.warning("orchestrated_client_no_fast_tier", message="Running in Smart-Only mode (slower, higher cost)")
        else:
            fast_providers = [c.provider.value for c in self.fast_clients]
            logger.info(
                "orchestrated_client_initialized",
                mode="Hybrid Fast Tier",
                smart_tier=smart_client.provider.value,
                fast_tier_chain=" -> ".join(fast_providers),
                fast_providers=fast_providers,
                concurrency=self.metrics.max_concurrency if hasattr(self.metrics, 'max_concurrency') else "default"
            )

    @property
    def provider(self) -> LlmProvider:
        # Returns the default (smart) provider's type for external consistency
        return self.smart_client.provider

    @resilient(timeout_seconds=60, retry_max_attempts=3, circuit_breaker_enabled=True)
    async def send_async(self, request: LlmRequest) -> LlmResponse:
        """
        Routes request to the appropriate tier with hierarchical fallback.
        """
        import time
        
        # 1. Determine initial target tier
        if request.use_fast_tier and self.fast_clients:
            # PARALLEL Fast Tier Execution (Global Optimization)
            # All fast providers race - fastest successful response wins
            async def try_fast_provider(client: ILlmClient) -> tuple[ILlmClient, LlmResponse]:
                """Execute single fast provider with timing."""
                target_model = request.model or self.fast_model

                # Clone request to avoid mutation issues
                provider_request = LlmRequest(
                    system_prompt=request.system_prompt,
                    user_message=request.user_message,
                    model=target_model or self.fast_model,
                    max_tokens=request.max_tokens,
                    temperature=request.temperature,
                    timeout_seconds=request.timeout_seconds,
                    use_fast_tier=request.use_fast_tier,
                )

                start_time = time.time()
                response = await client.send_async(provider_request)
                duration_ms = int((time.time() - start_time) * 1000)

                # Record metrics
                self.metrics.record_request(
                    tier="fast",
                    provider=client.provider.value,
                    model=target_model or "default",
                    success=response.success,
                    duration_ms=duration_ms,
                    error=response.error_message
                )

                return client, response

            # Race all fast providers concurrently
            tasks = [try_fast_provider(client) for client in self.fast_clients]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Find first successful response
            successful_response = None
            failed_providers = []

            for result in results:
                if isinstance(result, Exception):
                    logger.error("fast_tier_provider_exception", error=str(result))
                    continue

                client, response = result
                if response.success:
                    if successful_response is None:
                        # First successful response wins
                        successful_response = response
                        logger.debug(
                            "fast_tier_winner",
                            provider=client.provider.value,
                            duration_ms=response.duration_ms
                        )
                else:
                    failed_providers.append((client.provider.value, response.error_message))

            # Log failed providers
            for provider, error in failed_providers:
                logger.warning(
                    "fast_tier_provider_failed",
                    provider=provider,
                    error=error
                )

            # Return successful response if any
            if successful_response:
                return successful_response

            # If we are here, all fast clients failed
            logger.warning("all_fast_tier_providers_failed_falling_back_to_smart")

        # 2. Smart Tier Execution (Final fallback or direct choice)
        target_model = request.model or self.smart_model

        # Silently route to smart tier (metrics recorded below)
        # Ensure model is set if we have a smart default
        if not request.model and self.smart_model:
            request.model = self.smart_model

        start_time = time.time()
        response = await self.smart_client.send_async(request)
        duration_ms = int((time.time() - start_time) * 1000)
        
        # Record metrics for smart tier
        self.metrics.record_request(
            tier="smart",
            provider=self.smart_client.provider.value,
            model=target_model or "default",
            success=response.success,
            duration_ms=duration_ms,
            error=response.error_message
        )

        return response

    async def is_available_async(self) -> bool:
        """
        Available if at least the smart client is available.
        """
        return await self.smart_client.is_available_async()
