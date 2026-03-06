import asyncio
import os

from warden.shared.infrastructure.logging import get_logger

from ..circuit_breaker import ProviderCircuitBreaker
from ..types import LlmProvider, LlmRequest, LlmResponse
from .base import ILlmClient

logger = get_logger(__name__)

# CI detection for aggressive fail-fast
_IS_CI = os.environ.get("CI", "").lower() == "true" or os.environ.get("GITHUB_ACTIONS", "").lower() == "true"


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
        # Local providers (Ollama) recover quickly — use 30s window instead of 5min.
        if circuit_breaker is not None:
            self.circuit_breaker = circuit_breaker
        else:
            from datetime import timedelta

            _local = {LlmProvider.OLLAMA}
            _recovery = timedelta(seconds=30) if smart_client.provider in _local else timedelta(minutes=5)
            self.circuit_breaker = ProviderCircuitBreaker(open_duration=_recovery)

        # Initialize metrics collector
        if metrics_collector is None:
            from warden.llm.metrics import LLMMetricsCollector

            metrics_collector = LLMMetricsCollector()
        self.metrics = metrics_collector
        self._avail_cache: dict[str, tuple[bool, float]] = {}

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
                concurrency=getattr(self.metrics, "max_concurrency", "default"),
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

            done: set = set()
            pending: set = set()
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
                # In CI, we use a tighter timeout to fail fast.
                fast_timeout_limit = 20.0 if _IS_CI else 30.0
                fast_timeout = min(request.timeout_seconds / 3, fast_timeout_limit)

                # Create tasks for eligible providers only (circuit-open ones already filtered)
                tasks = [asyncio.create_task(try_fast_provider(client)) for client in eligible_clients]

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
                # Filter circuit-open providers (circuit breaker replaces per-client is_available_async check)
                eligible_fallback = [fc for fc in self.fast_clients if not cb.is_open(fc.provider)]

                if eligible_fallback:
                    # Race eligible fallback clients in parallel with a shared deadline
                    # Avoids sequential 10s+ is_available_async + full-timeout cascade
                    fallback_timeout = min(request.timeout_seconds * 0.5, 60.0)

                    async def _try_fallback(fast_client: ILlmClient) -> tuple[ILlmClient, LlmResponse]:
                        fb_request = LlmRequest(
                            system_prompt=request.system_prompt,
                            user_message=request.user_message,
                            model=self.fast_model,
                            max_tokens=request.max_tokens,
                            temperature=request.temperature,
                            timeout_seconds=fallback_timeout,
                            use_fast_tier=True,
                        )
                        fb_response = await asyncio.wait_for(
                            fast_client.send_async(fb_request),
                            timeout=fallback_timeout,
                        )
                        return fast_client, fb_response

                    fb_task_to_client: dict = {asyncio.create_task(_try_fallback(fc)): fc for fc in eligible_fallback}
                    fb_tasks = list(fb_task_to_client.keys())
                    fb_done: set = set()
                    fb_pending: set = set(fb_tasks)
                    try:
                        fb_done, fb_pending = await asyncio.wait(
                            fb_tasks, timeout=fallback_timeout, return_when=asyncio.FIRST_COMPLETED
                        )
                    except Exception:
                        fb_done, fb_pending = set(), set(fb_tasks)

                    # Record failures for timed-out tasks before cancelling (#309)
                    for fb_task in fb_pending:
                        pending_client = fb_task_to_client.get(fb_task)
                        if pending_client is not None:
                            cb.record_failure(pending_client.provider)
                        fb_task.cancel()

                    for fb_task in fb_done:
                        try:
                            fc, fb_response = fb_task.result()
                            if fb_response.success and fb_response.content:
                                cb.record_success(fc.provider)
                                logger.info("smart_tier_fallback_succeeded", provider=fc.provider.value)
                                return self._ensure_attribution(
                                    fb_response,
                                    fallback_provider=fc.provider,
                                    fallback_model=self.fast_model,
                                )
                            else:
                                cb.record_failure(fc.provider)
                        except Exception as fallback_err:
                            # Task raised (timeout or exception) — record failure for circuit breaker (#309)
                            fc = fb_task_to_client.get(fb_task)
                            if fc is not None:
                                cb.record_failure(fc.provider)
                            logger.debug("smart_tier_fallback_failed", error=str(fallback_err))

            raise ExternalServiceError(f"Smart tier failed: {response.error_message}")

        return self._ensure_attribution(
            response,
            fallback_provider=self.smart_client.provider,
            fallback_model=target_model,
        )

    # TTL cache for availability checks — avoids re-probing on every request.
    _AVAIL_TTL_S: float = 30.0

    async def is_available_async(self) -> bool:
        """
        Available if smart client OR any fast client is available.
        Checks all clients in parallel and caches results for 30 s.
        """
        import time as _time

        now = _time.monotonic()
        cache_key = id(self)
        cached = self._avail_cache.get(str(cache_key))
        if cached is not None:
            result, ts = cached
            if now - ts < self._AVAIL_TTL_S:
                return result

        all_clients = [self.smart_client, *self.fast_clients]

        async def _probe(client: ILlmClient) -> bool:
            try:
                return await client.is_available_async()
            except BaseException:
                return False

        results = await asyncio.gather(*[_probe(c) for c in all_clients], return_exceptions=True)
        results = [r if isinstance(r, bool) else False for r in results]
        available = any(results)
        self._avail_cache[str(cache_key)] = (available, now)
        return available
