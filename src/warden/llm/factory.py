"""
LLM Client Factory

Based on C# LlmClientFactory.cs
Creates LLM clients with automatic fallback support
"""

from typing import Optional
from .config import LlmConfiguration
from .types import LlmProvider
from .providers.base import ILlmClient
from .providers.anthropic import AnthropicClient
from .providers.deepseek import DeepSeekClient
from .providers.qwencode import QwenCodeClient
from .providers.openai import OpenAIClient
from .providers.groq import GroqClient


class LlmClientFactory:
    """
    Factory for creating LLM clients

    Matches C# LlmClientFactory with fallback chain support
    """

    def __init__(self, configuration: LlmConfiguration):
        """
        Initialize factory with configuration

        Args:
            configuration: LLM configuration with provider settings
        """
        self._config = configuration

    def create_client(self, provider: LlmProvider) -> ILlmClient:
        """
        Create client for specific provider

        Args:
            provider: LLM provider to create

        Returns:
            Configured LLM client

        Raises:
            ValueError: If provider not configured or enabled
            NotImplementedError: If provider not supported
        """
        config = self._config.get_provider_config(provider)

        if not config or not config.enabled or not config.api_key:
            raise ValueError(f"Provider {provider.value} is not configured or enabled")

        # Map providers to client classes
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

    def create_default_client(self) -> ILlmClient:
        """
        Create default client from configuration

        Returns:
            Default LLM client
        """
        return self.create_client(self._config.default_provider)

    async def create_client_with_fallback(self) -> ILlmClient:
        """
        Create client with automatic fallback

        Tries default provider first, then fallback providers in order
        until one is available

        Returns:
            First available LLM client

        Raises:
            RuntimeError: If no providers are available
        """
        providers = self._config.get_all_providers_chain()

        for provider in providers:
            try:
                client = self.create_client(provider)

                # Check if provider is actually available
                if await client.is_available_async():
                    return client

            except Exception:
                # Continue to next provider
                continue

        raise RuntimeError("No available LLM providers found. Check your configuration.")
