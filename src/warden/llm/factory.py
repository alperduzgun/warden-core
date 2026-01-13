"""
LLM Client Factory

Functional factory for creating LLM clients with fallback support.
"""

from typing import Optional, Union
from .config import LlmConfiguration, load_llm_config, ProviderConfig
from .types import LlmProvider
from .providers.base import ILlmClient
from .providers.anthropic import AnthropicClient
from .providers.deepseek import DeepSeekClient
from .providers.qwencode import QwenCodeClient
from .providers.openai import OpenAIClient
from .providers.groq import GroqClient


def create_provider_client(provider: LlmProvider, config: ProviderConfig) -> ILlmClient:
    """Create a client for a specific provider configuration."""
    if not config.enabled or not config.api_key:
        raise ValueError(f"Provider {provider.value} is not configured or enabled")

    if provider == LlmProvider.ANTHROPIC:
        return AnthropicClient(config)
    elif provider == LlmProvider.DEEPSEEK:
        return DeepSeekClient(config)
    elif provider == LlmProvider.QWENCODE:
        return QwenCodeClient(config)
    elif provider == LlmProvider.OPENAI:
        return OpenAIClient(config, LlmProvider.OPENAI)
    elif provider == LlmProvider.AZURE_OPENAI:
        return OpenAIClient(config, LlmProvider.AZURE_OPENAI)
    elif provider == LlmProvider.GROQ:
        return GroqClient(config)
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

    return create_provider_client(provider, provider_config)


async def create_client_with_fallback(config: Optional[LlmConfiguration] = None) -> ILlmClient:
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

