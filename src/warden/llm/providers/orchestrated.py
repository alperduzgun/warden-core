import asyncio

from warden.shared.infrastructure.logging import get_logger

from ..circuit_breaker import ProviderCircuitBreaker
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

    Circuit Breaker:
    - Each provider is tracked independently by a ProviderCircuitBreaker.
    - Providers whose circuit is OPEN are skipped immediately (no timeout wait).
    - Successes and failures are recorded after each provider attempt.
    """

    def __init__(
        self,
        smart_client: ILlmClient,
        fast_clients: list[ILlmClient] | None = None,
        smart_model: str | None = None,
        fast_model: str | None = None,
        metrics_collector=None,
        circuit_breaker: ProviderCircuitBreaker | None = None,
    ):
        """
        Initialize orchestrated LLM client with tiered routing.

        Args:
            smart_client: Primary LLM client for complex queries (e.g., Azure/OpenAI)
            fast_clients: Optional list of fast tier clients (e.g., Ollama, Groq) for parallel racing
            smart_model: Default model name for smart tier
            fast_model: Default model name for fast tier
            metrics_collector: Optional metrics collector for tracking performance
            circuit_breaker: Optional provider-level circuit breaker instance.
                             If None, a default one is created automatically.

        Note:
            When fast_clients is empty, operates in Smart-Only mode (slower, higher cost).
            When fast_clients are provided, they race in parallel for optimal latency.
        """
        self.smart_client = smart_client
        self.fast_clients = fast_clients or []
        self.smart_model = smart_model
        self.fast_model = fast_model

        # Provider-level circuit breaker (issue #127)
        self.circuit_breaker = circuit_breaker or ProviderCircuitBreaker()

        # Initialize metrics collector
        if metrics_collector is None:
            from warden.llm.metrics import LLMMetricsCollector

            metrics_collector = LLMMetricsCollector()
        self.metrics = metrics_collector

        if not self.fast_clients:
            # CLI-tool providers (Codex, Claude Code) are intentionally single-tier:
            # they manage model selection internally so no fast/smart split is needed.
            # Avoid misleading "slower, higher cost" log for these providers.
            _single_tier = {LlmProvider.CLAUDE_CODE, LlmProvider.CODEX}
            if smart_client.provider in _single_tier:
                logger.info(
                    "orchestrated_client_single_provider_mode",
                    provider=smart_client.provider.value,
                    message="CLI tool manages its own model — all requests route through one provider",
                )
            else:
                logger.info(
                    "orchestrated_client_no_fast_tier",
                    message="Running in Smart-Only mode (no fast tier configured)",
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

    @staticmethod
    def _ensure_attribution(
        response: LlmResponse,
        fallback_provider: LlmProvider | None,
        fallback_model: str | None,
    ) -> LlmResponse:
        """Ensure response has model and provider attribution.

        Providers should always set these fields, but as a defense-in-depth
        measure the orchestrator fills in any gaps so that downstream
        findings always carry complete LLM attribution.

        Args:
            response: The LlmResponse to check.
            fallback_provider: Provider to use if response.provider is None.
            fallback_model: Model name to use if response.model is None.

        Returns:
            The same response object (mutated in-place for efficiency).
        """
        if not response.provider and fallback_provider:
            response.provider = fallback_provider
        if not response.model and fallback_model:
            response.model = fallback_model
        return response

    async def send_async(self, request: LlmRequest) -> LlmResponse:
        """
        Routes request to the appropriate tier with hierarchical fallback.

        Resilience is handled per-provider (each provider has its own @resilient
        decorator with circuit breaker). Additionally, the orchestrator-level
        ProviderCircuitBreaker skips providers whose circuit is OPEN, preventing
        cascading timeouts when a provider is down (issue #127).

        Flow:
            - Circuit check: Skip providers with open circuits immediately
            - Parallel racing: Eligible fast providers race, first success wins, losers cancelled
            - Fallback chain: Fast tier -> Smart tier -> Failure

        Note:
            In Smart-Only mode (no fast_clients), routes directly to smart tier.
        """
        import time

        cb = self.circuit_breaker

        # 1. Determine initial target tier
        if request.use_fast_tier and self.fast_clients:
            # Filter out providers with open circuits before racing
            eligible_clients = []
            skipped_providers = []
            for client in self.fast_clients:
                if cb.is_open(client.provider):
                    skipped_providers.append(client.provider.value)
                else:
                    eligible_clients.append(client)

            if skipped_providers:
                logger.info(
                    "fast_tier_circuit_breaker_skip",
                    skipped_providers=skipped_providers,
                    eligible_count=len(eligible_clients),
                    message="Skipped providers with open circuits",
                )

            if eligible_clients:
                # PARALLEL Fast Tier Execution (Global Optimization)
                # All eligible fast providers race - fastest successful response wins
                async def try_fast_provider(client: ILlmClient) -> tuple[ILlmClient, LlmResponse]:
                    """Execute single fast provider with timing and circuit breaker recording."""
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

                    # Record circuit breaker state based on response
                    if response.success:
                        cb.record_success(client.provider)
                    else:
                        cb.record_failure(client.provider)

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
                # Timeout derived from request budget: 1/3 gives fast tier priority
                # without starving it — 3b Ollama on CI needs ~15-20s for warm inference.
                fast_timeout = min(request.timeout_seconds / 3, 30.0)

                # Create tasks for eligible providers only (circuit-open ones already filtered)
                tasks = [asyncio.create_task(try_fast_provider(client)) for client in eligible_clients]

                # Wait for first completion or timeout
                try:
                    done, pending = await asyncio.wait(
                        tasks, timeout=fast_timeout, return_when=asyncio.FIRST_COMPLETED
                    )
                except Exception as e:
                    # Cancel all tasks on error
                    for task in tasks:
                        task.cancel()
                    logger.error("fast_tier_race_error", error=str(e))
                    done, pending = set(), set(tasks)

                # Process completed tasks to find first success
                successful_response = None
                winning_client = None
                failed_providers = []

                for task in done:
                    try:
                        client, response = task.result()
                        if response.success:
                            successful_response = response
                            winning_client = client
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
                for provider_name, error in failed_providers:
                    logger.warning("fast_tier_provider_failed", provider=provider_name, error=error)

                # Return successful response if any
                if successful_response:
                    return self._ensure_attribution(
                        successful_response,
                        fallback_provider=winning_client.provider if winning_client else None,
                        fallback_model=request.model or self.fast_model,
                    )

            # If we are here, all fast clients failed, timed out, or were circuit-broken
            logger.warning(
                "all_fast_tier_providers_failed_falling_back_to_smart",
                completed=len(done) if eligible_clients else 0,
                timeout=len(pending) if eligible_clients else 0,
                total=len(self.fast_clients),
                circuit_open=len(skipped_providers),
            )

            # Track fallback metric
            fast_timeout_val = min(request.timeout_seconds / 3, 30.0) if eligible_clients else 0
            self.metrics.record_request(
                tier="fast",
                provider="fallback_to_smart",
                model="n/a",
                success=False,
                duration_ms=int(fast_timeout_val * 1000),
                error="all_fast_providers_failed",
            )

        # 2. Smart Tier Execution (Final fallback or direct choice)
        # Check smart tier circuit breaker -- but since it is the last resort,
        # we only log a warning and still attempt (better to try than to give up)
        if cb.is_open(self.smart_client.provider):
            logger.warning(
                "smart_tier_circuit_open_but_attempting",
                provider=self.smart_client.provider.value,
                message="Smart tier circuit is open but attempting as last resort",
            )

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

        # Record circuit breaker state for smart tier
        if response.success:
            cb.record_success(self.smart_client.provider)
        else:
            cb.record_failure(self.smart_client.provider)

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

        # CORE RESILIENCE: If smart tier fails, try fast clients as degraded fallback
        if not response.success:
            from warden.shared.infrastructure.exceptions import ExternalServiceError

            if self.fast_clients:
                logger.warning(
                    "smart_tier_failed_trying_fallback",
                    error=response.error_message,
                    fast_clients_available=len(self.fast_clients),
                )
                for fast_client in self.fast_clients:
                    # Skip providers with open circuits in fallback path too
                    if cb.is_open(fast_client.provider):
                        logger.debug(
                            "smart_fallback_circuit_open_skip",
                            provider=fast_client.provider.value,
                        )
                        continue
                    try:
                        if not await fast_client.is_available_async():
                            continue
                        fallback_request = LlmRequest(
                            system_prompt=request.system_prompt,
                            user_message=request.user_message,
                            model=self.fast_model,
                            max_tokens=request.max_tokens,
                            temperature=request.temperature,
                            timeout_seconds=request.timeout_seconds,
                            use_fast_tier=True,
                        )
                        # Bound fallback — @resilient retry (2x120s) would block 4min otherwise.
                        fallback_response = await asyncio.wait_for(
                            fast_client.send_async(fallback_request),
                            timeout=request.timeout_seconds,
                        )
                        if fallback_response.success and fallback_response.content:
                            cb.record_success(fast_client.provider)
                            logger.info(
                                "smart_tier_fallback_succeeded",
                                provider=fast_client.provider.value,
                            )
                            return self._ensure_attribution(
                                fallback_response,
                                fallback_provider=fast_client.provider,
                                fallback_model=self.fast_model,
                            )
                        else:
                            cb.record_failure(fast_client.provider)
                    except Exception as fallback_err:
                        cb.record_failure(fast_client.provider)
                        logger.debug(
                            "smart_tier_fallback_failed",
                            provider=fast_client.provider.value,
                            error=str(fallback_err),
                        )
                        continue

            raise ExternalServiceError(f"Smart tier failed: {response.error_message}")

        return self._ensure_attribution(
            response,
            fallback_provider=self.smart_client.provider,
            fallback_model=target_model,
        )

    async def is_available_async(self) -> bool:
        """
        Available if smart client OR any fast client is available.
        """
        if await self.smart_client.is_available_async():
            return True
        for client in self.fast_clients:
            try:
                if await client.is_available_async():
                    return True
            except Exception:
                continue
        return False
