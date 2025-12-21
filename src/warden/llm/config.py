"""
LLM Configuration

Supports multi-provider configuration with fallback chain.
Providers: DeepSeek, QwenCode, Anthropic, OpenAI, Azure OpenAI, Groq, OpenRouter
"""

from dataclasses import dataclass, field
from typing import Optional
from .types import LlmProvider


@dataclass
class ProviderConfig:
    """
    Configuration for a specific LLM provider

    Matches C# ProviderConfig
    Security: API keys should be loaded from environment variables
    """
    api_key: Optional[str] = None
    endpoint: Optional[str] = None
    default_model: Optional[str] = None
    api_version: Optional[str] = None  # For Azure OpenAI
    enabled: bool = True

    def validate(self, provider_name: str) -> list[str]:
        """
        Validate provider configuration

        Returns:
            List of validation errors (empty if valid)
        """
        errors = []

        if not self.api_key:
            errors.append(f"{provider_name}: API key is required but not configured")
        elif len(self.api_key) < 10:
            errors.append(f"{provider_name}: API key appears invalid (too short)")

        if not self.default_model:
            errors.append(f"{provider_name}: Default model is required but not configured")

        # Validate endpoint URL if provided
        if self.endpoint:
            if not self.endpoint.startswith(("http://", "https://")):
                errors.append(f"{provider_name}: Endpoint must use HTTP or HTTPS protocol")

        return errors

    def __str__(self) -> str:
        """Safe string representation without exposing API key"""
        api_key_mask = "not set" if not self.api_key else f"***{self.api_key[-4:]}"
        return (
            f"Enabled={self.enabled}, "
            f"ApiKey={api_key_mask}, "
            f"Endpoint={self.endpoint or 'default'}, "
            f"Model={self.default_model or 'not set'}"
        )


@dataclass
class LlmConfiguration:
    """
    Main LLM configuration with multi-provider support

    Matches C# LlmConfiguration.cs

    Example usage:
        config = LlmConfiguration(
            default_provider=LlmProvider.DEEPSEEK,
            fallback_providers=[LlmProvider.QWENCODE, LlmProvider.ANTHROPIC]
        )

        # Configure providers
        config.deepseek.api_key = os.getenv("DEEPSEEK_API_KEY")
        config.deepseek.default_model = "deepseek-coder"
    """
    default_provider: LlmProvider = LlmProvider.DEEPSEEK
    fallback_providers: list[LlmProvider] = field(default_factory=list)

    # Provider configurations
    deepseek: ProviderConfig = field(default_factory=ProviderConfig)
    qwencode: ProviderConfig = field(default_factory=ProviderConfig)
    anthropic: ProviderConfig = field(default_factory=ProviderConfig)
    openai: ProviderConfig = field(default_factory=ProviderConfig)
    azure_openai: ProviderConfig = field(default_factory=ProviderConfig)
    groq: ProviderConfig = field(default_factory=ProviderConfig)
    openrouter: ProviderConfig = field(default_factory=ProviderConfig)

    def get_provider_config(self, provider: LlmProvider) -> Optional[ProviderConfig]:
        """
        Get configuration for a specific provider

        Args:
            provider: The LLM provider

        Returns:
            Provider configuration or None if not found
        """
        mapping = {
            LlmProvider.DEEPSEEK: self.deepseek,
            LlmProvider.QWENCODE: self.qwencode,
            LlmProvider.ANTHROPIC: self.anthropic,
            LlmProvider.OPENAI: self.openai,
            LlmProvider.AZURE_OPENAI: self.azure_openai,
            LlmProvider.GROQ: self.groq,
            LlmProvider.OPENROUTER: self.openrouter
        }
        return mapping.get(provider)

    def validate(self) -> list[str]:
        """
        Validate all enabled provider configurations

        Returns:
            List of validation errors (empty if all valid)
        """
        errors = []

        # Validate default provider
        default_config = self.get_provider_config(self.default_provider)
        if default_config and default_config.enabled:
            errors.extend(default_config.validate(self.default_provider.value))

        # Validate fallback providers
        for provider in self.fallback_providers:
            config = self.get_provider_config(provider)
            if config and config.enabled:
                errors.extend(config.validate(provider.value))

        return errors

    def get_all_providers_chain(self) -> list[LlmProvider]:
        """
        Get full provider chain (default + fallbacks)

        Returns:
            List of providers in order of preference
        """
        return [self.default_provider] + self.fallback_providers


# Default provider models (based on C# defaults)
DEFAULT_MODELS = {
    LlmProvider.DEEPSEEK: "deepseek-coder",
    LlmProvider.QWENCODE: "qwen2.5-coder-32b-instruct",
    LlmProvider.ANTHROPIC: "claude-3-5-sonnet-20241022",
    LlmProvider.OPENAI: "gpt-4o",
    LlmProvider.AZURE_OPENAI: "gpt-4o",
    LlmProvider.GROQ: "llama-3.1-70b-versatile",
    LlmProvider.OPENROUTER: "anthropic/claude-3.5-sonnet"
}


def create_default_config() -> LlmConfiguration:
    """
    Create a default LLM configuration

    Note: API keys must be set from environment variables
    """
    config = LlmConfiguration(
        default_provider=LlmProvider.DEEPSEEK,
        fallback_providers=[LlmProvider.QWENCODE, LlmProvider.ANTHROPIC]
    )

    # Set default models
    for provider, model in DEFAULT_MODELS.items():
        provider_config = config.get_provider_config(provider)
        if provider_config:
            provider_config.default_model = model

    return config
