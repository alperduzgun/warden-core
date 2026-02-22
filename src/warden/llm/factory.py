"""
LLM Client Factory

Functional factory for creating LLM clients with fallback support.
"""

import threading

import structlog as _structlog

from warden.shared.infrastructure.error_handler import async_error_handler

from .config import LlmConfiguration, ProviderConfig, load_llm_config
from .metrics import get_global_metrics_collector
from .providers.base import ILlmClient
from .registry import ProviderRegistry
from .types import LlmProvider

# CLI-tool providers that manage their own model selection.
# For these, the fast/smart tier distinction is meaningless — all requests
# route through the same tool (single-provider mode).
SINGLE_TIER_PROVIDERS: frozenset[LlmProvider] = frozenset(
    {
        LlmProvider.CLAUDE_CODE,
        LlmProvider.CODEX,
    }
)

_providers_lock = threading.Lock()
_providers_imported = False
_factory_logger = _structlog.get_logger(__name__)


def _ensure_providers_registered() -> None:
    """
    Lazy import all providers to trigger self-registration.

    Thread-safe: uses lock to prevent race conditions during concurrent access.
    Idempotent: only imports once.
    """
    global _providers_imported

    if _providers_imported:
        return

    with _providers_lock:
        if _providers_imported:
            return  # Double-check after acquiring lock

        provider_modules = [
            "warden.llm.providers.anthropic",
            "warden.llm.providers.deepseek",
            "warden.llm.providers.qwencode",
            "warden.llm.providers.openai",
            "warden.llm.providers.groq",
            "warden.llm.providers.ollama",
            "warden.llm.providers.gemini",
            "warden.llm.providers.claude_code",
            "warden.llm.providers.codex",
        ]

        import importlib

        for module_name in provider_modules:
            try:
                importlib.import_module(module_name)
            except ImportError as e:
                _factory_logger.debug("provider_module_unavailable", module=module_name, error=str(e))

        _providers_imported = True


def create_provider_client(provider: LlmProvider, config: ProviderConfig) -> ILlmClient:
    """
    Create a client for a specific provider configuration.

    Uses registry-based factory pattern to eliminate if/elif chains.
    Providers self-register on module import.

    Args:
        provider: The LLM provider to create
        config: Provider configuration

    Returns:
        Configured ILlmClient instance

    Raises:
        ValueError: If provider is not configured, enabled, or registered
    """
    # Validate configuration before creating client
    local_providers = {LlmProvider.OLLAMA, LlmProvider.CLAUDE_CODE, LlmProvider.CODEX}
    if provider not in local_providers:
        if not config.enabled or not config.api_key:
            raise ValueError(f"Provider {provider.value} is not configured or enabled")
    elif not config.enabled:
        raise ValueError(f"Provider {provider.value} is not enabled")

    # Ensure all providers are registered
    _ensure_providers_registered()

    # Use registry to create the client
    return ProviderRegistry.create(provider, config)


def create_client(provider_or_config: LlmProvider | LlmConfiguration | str | None = None) -> ILlmClient:
    """
    Create an LLM client based on input or default configuration.

    Args:
        provider_or_config:
            - None: Use default configuration
            - LlmProvider/str: Use default config for specific provider
            - LlmConfiguration: Use specific configuration
    """
    # Load default config if needed
    if isinstance(provider_or_config, LlmConfiguration):
        config = provider_or_config
        provider = config.default_provider
    else:
        config = load_llm_config()
        if isinstance(provider_or_config, LlmProvider):
            provider = provider_or_config
        elif isinstance(provider_or_config, str):
            provider = LlmProvider(provider_or_config)
        else:
            provider = config.default_provider

    provider_config = config.get_provider_config(provider)
    if not provider_config:
        raise ValueError(f"No configuration found for provider: {provider}")

    # Create primary (smart) client
    smart_client = create_provider_client(provider, provider_config)

    # Build fast-tier clients.
    # CLI-tool providers (Codex, Claude Code) manage their own model selection,
    # so the fast/smart distinction doesn't apply — use single-provider mode.
    fast_clients: list[ILlmClient] = []

    if provider in SINGLE_TIER_PROVIDERS:
        _factory_logger.info("single_provider_mode", provider=provider.value)
        # Probe for emergency fallback providers (e.g., Ollama).
        # Normal flow unchanged: all requests → smart client (Claude Code/Codex).
        # Fallback only activates when smart tier returns empty/error.
        for fast_provider in getattr(config, "fast_tier_providers", [LlmProvider.OLLAMA]):
            if fast_provider == provider:
                continue
            try:
                fast_cfg = config.get_provider_config(fast_provider)
                if fast_cfg and fast_cfg.enabled:
                    client = create_provider_client(fast_provider, fast_cfg)
                    fast_clients.append(client)
                    _factory_logger.info(
                        "emergency_fallback_added",
                        primary=provider.value,
                        fallback=fast_provider.value,
                    )
            except Exception as e:
                _factory_logger.debug(
                    "emergency_fallback_unavailable",
                    provider=fast_provider.value,
                    error=str(e),
                )
        if not fast_clients:
            _factory_logger.info(
                "no_emergency_fallback",
                provider=provider.value,
                message="No fallback providers available",
            )
    else:
        for fast_provider in getattr(config, "fast_tier_providers", [LlmProvider.OLLAMA]):
            if fast_provider == provider:
                # Primary provider is already the smart_client — skip to avoid
                # racing against itself in the fast tier.
                continue
            try:
                fast_cfg = config.get_provider_config(fast_provider)
                if fast_cfg and fast_cfg.enabled:
                    client = create_provider_client(fast_provider, fast_cfg)
                    fast_clients.append(client)
                    _factory_logger.debug("fast_tier_client_added", provider=fast_provider.value)
            except Exception as e:
                _factory_logger.warning(
                    "fast_tier_client_creation_failed",
                    provider=fast_provider.value,
                    error=str(e),
                )

    _factory_logger.debug(
        "factory_client_status",
        fast_providers_configured=[p.value for p in getattr(config, "fast_tier_providers", [])],
        fast_clients_created=[c.provider for c in fast_clients],
    )

    # Wrap in OrchestratedLlmClient for tiered execution support
    from .providers.orchestrated import OrchestratedLlmClient

    return OrchestratedLlmClient(
        smart_client=smart_client,
        fast_clients=fast_clients,
        smart_model=config.smart_model,
        fast_model=config.fast_model,
        metrics_collector=get_global_metrics_collector(),
    )


def _create_offline_client():
    """Safely create OfflineClient fallback."""
    from .providers.offline import OfflineClient

    return OfflineClient()


@async_error_handler(fallback_value=_create_offline_client, log_level="error", context_keys=["config"], reraise=False)
async def create_client_with_fallback_async(config: LlmConfiguration | None = None) -> ILlmClient:
    """
    Create client with automatic fallback chain.

    Uses centralized error handler to ensure failures always return OfflineClient
    and are properly logged.
    """
    import structlog

    _logger = structlog.get_logger(__name__)

    if config is None:
        config = load_llm_config()

    # Try configured providers
    providers = config.get_all_providers_chain()

    for provider in providers:
        try:
            provider_config = config.get_provider_config(provider)
            if not provider_config:
                continue

            client = create_provider_client(provider, provider_config)

            # Check if actually available
            if await client.is_available_async():
                return client
        except Exception as e:
            # Issue #20: Log provider fallback failures for visibility
            _logger.warning("provider_fallback_failed", provider=provider.value, error=str(e))
            continue

    # FALLBACK: Zombie Mode (Offline)
    # If no providers worked, return the OfflineClient
    from .providers.offline import OfflineClient

    return OfflineClient()


__all__ = [
    "create_client",
    "create_provider_client",
    "create_client_with_fallback_async",
    "get_global_metrics_collector",
    "ProviderRegistry",
    "SINGLE_TIER_PROVIDERS",
]
