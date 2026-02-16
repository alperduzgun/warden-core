"""
Provider Registry for LLM clients.

Registry-based factory pattern to eliminate if/elif chains.
Providers self-register on module import.
"""

from collections.abc import Callable

from .config import ProviderConfig
from .providers.base import ILlmClient
from .types import LlmProvider


class ProviderRegistry:
    """Registry-based factory for LLM provider clients."""

    _providers: dict[LlmProvider, Callable[[ProviderConfig], ILlmClient]] = {}

    @classmethod
    def register(cls, provider: LlmProvider, factory: Callable[[ProviderConfig], ILlmClient]) -> None:
        """
        Register a provider factory function.

        Args:
            provider: The provider enum value
            factory: Factory function that takes ProviderConfig and returns ILlmClient

        Example:
            ProviderRegistry.register(LlmProvider.ANTHROPIC, AnthropicClient)
        """
        cls._providers[provider] = factory

    @classmethod
    def create(cls, provider: LlmProvider, config: ProviderConfig) -> ILlmClient:
        """
        Create a client instance using the registered factory.

        Args:
            provider: The provider to create
            config: Provider configuration

        Returns:
            Configured ILlmClient instance

        Raises:
            ValueError: If provider is not registered
        """
        if provider not in cls._providers:
            available = [p.value for p in cls.available()]
            raise ValueError(f"No provider registered for: {provider.value}. Available: {available}")

        factory = cls._providers[provider]
        return factory(config)

    @classmethod
    def available(cls) -> list[LlmProvider]:
        """
        Get list of registered providers.

        Returns:
            List of available LlmProvider enum values
        """
        return list(cls._providers.keys())

    @classmethod
    def is_registered(cls, provider: LlmProvider) -> bool:
        """
        Check if a provider is registered.

        Args:
            provider: Provider to check

        Returns:
            True if registered, False otherwise
        """
        return provider in cls._providers

    @classmethod
    def clear(cls) -> None:
        """Clear all registered providers (mainly for testing)."""
        cls._providers.clear()
