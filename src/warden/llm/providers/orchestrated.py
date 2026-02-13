import asyncio
from typing import List, Optional

from warden.shared.infrastructure.logging import get_logger
from warden.shared.infrastructure.resilience import resilient

from ..types import LlmProvider, LlmRequest, LlmResponse
from .base import ILlmClient

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
        fast_clients: list[ILlmClient] | None = None,
        smart_model: str | None = None,
        fast_model: str | None = None,
        metrics_collector=None,
    ):
        """
        Initialize orchestrated LLM client with tiered routing.

        Args:
            smart_client: Primary LLM client for complex queries (e.g., Azure/OpenAI)
            fast_clients: Optional list of fast tier clients (e.g., Ollama, Groq) for parallel racing
            smart_model: Default model name for smart tier
            fast_model: Default model name for fast tier
            metrics_collector: Optional metrics collector for tracking performance

        Note:
            When fast_clients is empty, operates in Smart-Only mode (slower, higher cost).
            When fast_clients are provided, they race in parallel for optimal latency.
        """
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
            logger.warning(
                "orchestrated_client_no_fast_tier", message="Running in Smart-Only mode (slower, higher cost)"
            )
        else:
            fast_providers = [c.provider.value for c in self.fast_clients]
            logger.info(
                "orchestrated_client_initialized",
                mode="Hybrid Fast Tier",
                smart_tier=smart_client.provider.value,
                fast_tier_chain=" -> ".join(fast_providers),
                fast_providers=fast_providers,
                concurrency=self.metrics.max_concurrency if hasattr(self.metrics, "max_concurrency") else "default",
            )

    @property
    def provider(self) -> LlmProvider:
        """
        Get the primary provider type.

        Returns:
            LlmProvider enum representing the smart client's provider

        Note:
            Returns smart provider for external consistency, even when fast tier is used.
        """
        return self.smart_client.provider

    @resilient(timeout_seconds=60, retry_max_attempts=3, circuit_breaker_enabled=True)
    async def send_async(self, request: LlmRequest) -> LlmResponse:
        """
        Routes request to the appropriate tier with hierarchical fallback.

        Resilience (Chaos Engineering):
            - Automatic retries: Up to 3 attempts on transient failures
            - Total timeout: 60 seconds per request (including retries)
            - Circuit breaker: Opens after consecutive failures to prevent cascade
            - Parallel racing: Fast providers race, first success wins, losers cancelled
            - Fallback chain: Fast tier → Smart tier → Failure

        Raises:
            TimeoutError: If request exceeds 60s timeout
            CircuitBreakerError: If circuit breaker is open (too many failures)

        Note:
            In Smart-Only mode (no fast_clients), routes directly to smart tier.
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

                # Extract token counts from response
                input_tokens = getattr(response, "prompt_tokens", 0) or 0
                output_tokens = getattr(response, "completion_tokens", 0) or 0

                # Record metrics with token information
                self.metrics.record_request(
                    tier="fast",
                    provider=client.provider.value,
                    model=target_model or "default",
                    success=response.success,
                    duration_ms=duration_ms,
                    error=response.error_message,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )

                return client, response

            # CHAOS ENGINEERING: Race providers with FIRST_COMPLETED pattern
            # This prevents slow providers from blocking fast ones
            # Max concurrency limit prevents resource exhaustion
            MAX_CONCURRENT_PROVIDERS = 3
            fast_timeout = 10  # seconds - fast tier should respond quickly

            # Create tasks for all providers
            tasks = [asyncio.create_task(try_fast_provider(client)) for client in self.fast_clients]

            # Wait for first completion or timeout
            try:
                done, pending = await asyncio.wait(tasks, timeout=fast_timeout, return_when=asyncio.FIRST_COMPLETED)
            except Exception as e:
                # Cancel all tasks on error
                for task in tasks:
                    task.cancel()
                logger.error("fast_tier_race_error", error=str(e))
                done, pending = set(), set(tasks)

            # Process completed tasks to find first success
            successful_response = None
            failed_providers = []

            for task in done:
                try:
                    client, response = task.result()
                    if response.success:
                        successful_response = response
                        logger.info(
                            "fast_tier_winner", provider=client.provider.value, duration_ms=response.duration_ms
                        )
                        break  # First success wins
                    else:
                        failed_providers.append((client.provider.value, response.error_message))
                except Exception as e:
                    logger.error("fast_tier_provider_exception", error=str(e))

            # Cancel remaining pending tasks (anti-fragility: resource cleanup)
            for task in pending:
                task.cancel()
                logger.debug(
                    "cancelled_slow_provider", task=task.get_name() if hasattr(task, "get_name") else "unknown"
                )

            # Log failed providers
            for provider, error in failed_providers:
                logger.warning("fast_tier_provider_failed", provider=provider, error=error)

            # Return successful response if any
            if successful_response:
                return successful_response

            # If we are here, all fast clients failed or timed out
            logger.warning(
                "all_fast_tier_providers_failed_falling_back_to_smart",
                completed=len(done),
                timeout=len(pending),
                total=len(self.fast_clients),
            )

            # Track fallback metric
            self.metrics.record_request(
                tier="fast",
                provider="fallback_to_smart",
                model="n/a",
                success=False,
                duration_ms=int(fast_timeout * 1000),
                error="all_fast_providers_failed",
            )

        # 2. Smart Tier Execution (Final fallback or direct choice)
        target_model = request.model or self.smart_model

        # IDEMPOTENCY: Clone request to prevent mutation (chaos engineering principle)
        # If we mutate the original request, reuse breaks idempotency
        smart_request = LlmRequest(
            system_prompt=request.system_prompt,
            user_message=request.user_message,
            model=target_model,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            timeout_seconds=request.timeout_seconds,
            use_fast_tier=False,  # Explicitly mark as smart tier
        )

        start_time = time.time()
        response = await self.smart_client.send_async(smart_request)
        duration_ms = int((time.time() - start_time) * 1000)

        # Extract token counts from response
        input_tokens = getattr(response, "prompt_tokens", 0) or 0
        output_tokens = getattr(response, "completion_tokens", 0) or 0

        # Record metrics for smart tier with token information
        self.metrics.record_request(
            tier="smart",
            provider=self.smart_client.provider.value,
            model=target_model or "default",
            success=response.success,
            duration_ms=duration_ms,
            error=response.error_message,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

        # CORE RESILIENCE: Raise exception on failure so Circuit Breaker can track it
        if not response.success:
            from warden.shared.infrastructure.exceptions import ExternalServiceError

            raise ExternalServiceError(f"Smart tier failed: {response.error_message}")

        return response

    async def is_available_async(self) -> bool:
        """
        Available if at least the smart client is available.
        """
        return await self.smart_client.is_available_async()
