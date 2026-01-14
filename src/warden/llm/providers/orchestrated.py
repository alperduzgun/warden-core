"""
Orchestrated LLM Client

A proxy client that intelligently routes requests between 
Smart (Cloud) and Fast (Local/Ollama) providers based on 
the LlmRequest configuration.
"""

from typing import Optional
from ..types import LlmProvider, LlmRequest, LlmResponse
from .base import ILlmClient
from warden.shared.infrastructure.logging import get_logger
from warden.shared.infrastructure.resilience import resilient

logger = get_logger(__name__)


class OrchestratedLlmClient(ILlmClient):
    """
    Proxy client implementing tiered LLM execution.
    
    Routes:
    - use_fast_tier=True -> Routes to Fast Provider (e.g. Ollama)
    - use_fast_tier=False -> Routes to Smart Provider (e.g. Azure/OpenAI)
    - Fallback -> If one tier is unavailable, falls back to the other.
    """

    def __init__(
        self, 
        smart_client: ILlmClient, 
        fast_client: Optional[ILlmClient] = None,
        smart_model: Optional[str] = None,
        fast_model: Optional[str] = None,
        metrics_collector = None
    ):
        self.smart_client = smart_client
        self.fast_client = fast_client
        self.smart_model = smart_model
        self.fast_model = fast_model
        
        # Initialize metrics collector
        if metrics_collector is None:
            from warden.llm.metrics import LLMMetricsCollector
            metrics_collector = LLMMetricsCollector()
        self.metrics = metrics_collector
        
        logger.debug(
            "orchestrated_llm_client_initialized",
            smart_provider=smart_client.provider,
            fast_provider=fast_client.provider if fast_client else "None",
            smart_model=smart_model,
            fast_model=fast_model
        )

    @property
    def provider(self) -> LlmProvider:
        # Returns the default (smart) provider's type for external consistency
        return self.smart_client.provider

    @resilient(timeout_seconds=60, retry_max_attempts=3, circuit_breaker_enabled=True)
    async def send_async(self, request: LlmRequest) -> LlmResponse:
        """
        Routes request to the appropriate tier.
        """
        import time
        
        # 1. Determine target client and model
        target_client = self.smart_client
        target_model = request.model or self.smart_model
        tier_label = "smart"

        if request.use_fast_tier and self.fast_client:
            target_client = self.fast_client
            target_model = request.model or self.fast_model
            tier_label = "fast"
            
            # Ensure model is set if we have a tiered default
            if not request.model and self.fast_model:
                request.model = self.fast_model

        logger.debug(
            "routing_llm_request",
            tier=tier_label,
            provider=target_client.provider,
            model=target_model or "default"
        )

        # 2. Execute request and track time
        start_time = time.time()
        response = await target_client.send_async(request)
        duration_ms = int((time.time() - start_time) * 1000)
        
        # Record metrics
        self.metrics.record_request(
            tier=tier_label,
            provider=target_client.provider.value,
            model=target_model or "default",
            success=response.success,
            duration_ms=duration_ms,
            error=response.error_message
        )

        # 3. Fallback logic: If fast tier fails, retry with smart tier
        if not response.success and tier_label == "fast" and self.smart_client:
            logger.warning(
                "fast_tier_failed_falling_back",
                error=response.error_message,
                provider=target_client.provider
            )
            # Reset model to smart default
            request.model = self.smart_model
            
            # Retry with smart tier and record metrics
            start_time = time.time()
            response = await self.smart_client.send_async(request)
            duration_ms = int((time.time() - start_time) * 1000)
            
            self.metrics.record_request(
                tier="smart",
                provider=self.smart_client.provider.value,
                model=self.smart_model or "default",
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
