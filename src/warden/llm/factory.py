"""
LLM Client Factory

Functional factory for creating LLM clients with fallback support.
"""

from typing import Optional, Union
from .config import LlmConfiguration, load_llm_config, ProviderConfig
from .types import LlmProvider
from .providers.base import ILlmClient
from .metrics import get_global_metrics_collector

def create_provider_client(provider: LlmProvider, config: ProviderConfig) -> ILlmClient:
    """Create a client for a specific provider configuration."""
    # Ollama doesn't require an API key (local deployment)
    if provider != LlmProvider.OLLAMA:
        if not config.enabled or not config.api_key:
            raise ValueError(f"Provider {provider.value} is not configured or enabled")
    elif not config.enabled:
        raise ValueError(f"Provider {provider.value} is not enabled")

    if provider == LlmProvider.ANTHROPIC:
        from .providers.anthropic import AnthropicClient
        return AnthropicClient(config)
    elif provider == LlmProvider.DEEPSEEK:
        from .providers.deepseek import DeepSeekClient
        return DeepSeekClient(config)
    elif provider == LlmProvider.QWENCODE:
        from .providers.qwencode import QwenCodeClient
        return QwenCodeClient(config)
    elif provider == LlmProvider.OPENAI:
        from .providers.openai import OpenAIClient
        return OpenAIClient(config, LlmProvider.OPENAI)
    elif provider == LlmProvider.AZURE_OPENAI:
        from .providers.openai import OpenAIClient
        return OpenAIClient(config, LlmProvider.AZURE_OPENAI)
    elif provider == LlmProvider.GROQ:
        from .providers.groq import GroqClient
        return GroqClient(config)
    elif provider == LlmProvider.OLLAMA:
        from .providers.ollama import OllamaClient
        return OllamaClient(config)
    elif provider == LlmProvider.GEMINI:
        from .providers.gemini import GeminiClient
        return GeminiClient(config)
    else:
        raise NotImplementedError(f"Provider {provider.value} not implemented")


def create_client(
    provider_or_config: Optional[Union[LlmProvider, LlmConfiguration, str]] = None
) -> ILlmClient:
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
    
    # Try to create local/fast clients if enabled in priority order
    fast_clients = []
    import structlog
    logger = structlog.get_logger(__name__)

    for fast_provider in getattr(config, 'fast_tier_providers', [LlmProvider.OLLAMA]):
        try:
            fast_cfg = config.get_provider_config(fast_provider)
            if fast_cfg and fast_cfg.enabled:
                client = create_provider_client(fast_provider, fast_cfg)
                fast_clients.append(client)
                logger.debug("fast_tier_client_added", provider=fast_provider.value)
        except Exception as e:
            # Log but don't fail - orchestration will work with whatever fast tier clients are available
            logger.warning("fast_tier_client_creation_failed", provider=fast_provider.value, error=str(e))
    
    # DEBUG: Diagnosing Hybrid Setup
    logger.warning("factory_client_status", 
                fast_providers_configured=[p.value for p in getattr(config, 'fast_tier_providers', [])],
                fast_clients_created=[c.provider for c in fast_clients])

    # Wrap in OrchestratedLlmClient for tiered execution support
    from .providers.orchestrated import OrchestratedLlmClient
    return OrchestratedLlmClient(
        smart_client=smart_client,
        fast_clients=fast_clients,
        smart_model=config.smart_model,
        fast_model=config.fast_model,
        metrics_collector=get_global_metrics_collector()
    )


async def create_client_with_fallback_async(config: Optional[LlmConfiguration] = None) -> ILlmClient:
    """
    Create client with automatic fallback chain.
    """
    if config is None:
        config = load_llm_config()

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
        except Exception:
            continue

    raise RuntimeError("No available LLM providers found.")

__all__ = [
    "create_client",
    "create_provider_client",
    "create_client_with_fallback_async",
    "get_global_metrics_collector"
]
