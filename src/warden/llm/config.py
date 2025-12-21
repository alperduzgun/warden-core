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


def load_llm_config() -> LlmConfiguration:
    """
    Load LLM configuration from environment variables and config files.

    Supports multiple providers with automatic configuration from environment:
    - Azure OpenAI: AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT, etc.
    - OpenAI: OPENAI_API_KEY
    - Anthropic: ANTHROPIC_API_KEY
    - DeepSeek: DEEPSEEK_API_KEY
    - And more...

    Returns:
        LlmConfiguration with configured providers based on available env vars

    Environment Variables:
        Azure OpenAI:
            - AZURE_OPENAI_API_KEY (required)
            - AZURE_OPENAI_ENDPOINT (required)
            - AZURE_OPENAI_DEPLOYMENT_NAME (required)
            - AZURE_OPENAI_API_VERSION (optional, default: "2024-02-01")

        Other providers (optional):
            - OPENAI_API_KEY
            - ANTHROPIC_API_KEY
            - DEEPSEEK_API_KEY
            - QWENCODE_API_KEY
            - GROQ_API_KEY
            - OPENROUTER_API_KEY
    """
    import os

    # Create base configuration (without default provider chain)
    config = LlmConfiguration(
        default_provider=LlmProvider.AZURE_OPENAI,  # Will be updated if not configured
        fallback_providers=[]  # Build dynamically based on available keys
    )

    # Set default models for all providers
    for provider, model in DEFAULT_MODELS.items():
        provider_config = config.get_provider_config(provider)
        if provider_config:
            provider_config.default_model = model

    # Track which providers are configured
    configured_providers = []

    # Configure Azure OpenAI (primary provider for Warden)
    azure_api_key = os.getenv("AZURE_OPENAI_API_KEY")
    azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    azure_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")
    azure_api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01")

    if azure_api_key and azure_endpoint and azure_deployment:
        config.azure_openai.api_key = azure_api_key
        config.azure_openai.endpoint = azure_endpoint
        config.azure_openai.default_model = azure_deployment
        config.azure_openai.api_version = azure_api_version
        config.azure_openai.enabled = True
        configured_providers.append(LlmProvider.AZURE_OPENAI)

    # Configure OpenAI
    openai_api_key = os.getenv("OPENAI_API_KEY")
    if openai_api_key:
        config.openai.api_key = openai_api_key
        config.openai.enabled = True
        configured_providers.append(LlmProvider.OPENAI)

    # Configure Anthropic
    anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")
    if anthropic_api_key:
        config.anthropic.api_key = anthropic_api_key
        config.anthropic.enabled = True
        configured_providers.append(LlmProvider.ANTHROPIC)

    # Configure DeepSeek
    deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")
    if deepseek_api_key:
        config.deepseek.api_key = deepseek_api_key
        config.deepseek.enabled = True
        configured_providers.append(LlmProvider.DEEPSEEK)

    # Configure QwenCode
    qwencode_api_key = os.getenv("QWENCODE_API_KEY")
    if qwencode_api_key:
        config.qwencode.api_key = qwencode_api_key
        config.qwencode.enabled = True
        configured_providers.append(LlmProvider.QWENCODE)

    # Configure Groq
    groq_api_key = os.getenv("GROQ_API_KEY")
    if groq_api_key:
        config.groq.api_key = groq_api_key
        config.groq.enabled = True
        configured_providers.append(LlmProvider.GROQ)

    # Configure OpenRouter
    openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
    if openrouter_api_key:
        config.openrouter.api_key = openrouter_api_key
        config.openrouter.enabled = True
        configured_providers.append(LlmProvider.OPENROUTER)

    # Set default provider and fallback chain based on what's configured
    if configured_providers:
        config.default_provider = configured_providers[0]
        config.fallback_providers = configured_providers[1:] if len(configured_providers) > 1 else []
    else:
        # No providers configured - disable all
        for provider_config in [
            config.azure_openai,
            config.openai,
            config.anthropic,
            config.deepseek,
            config.qwencode,
            config.groq,
            config.openrouter,
        ]:
            provider_config.enabled = False

    return config
