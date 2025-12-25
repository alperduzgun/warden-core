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
    Load LLM configuration using SecretManager.

    Supports multiple secret sources with auto-detection:
    - Local .env file (development)
    - Environment variables (GitHub Actions CI/CD)
    - Azure Key Vault (production)

    Returns:
        LlmConfiguration with configured providers based on available secrets

    Secret Sources (in priority order):
        1. Azure Key Vault (if AZURE_KEY_VAULT_URL is set)
        2. Environment variables (if GITHUB_ACTIONS=true)
        3. .env file (local development)
        4. Environment variables (fallback)

    Required Secrets for Azure OpenAI:
        - AZURE_OPENAI_API_KEY
        - AZURE_OPENAI_ENDPOINT
        - AZURE_OPENAI_DEPLOYMENT_NAME
        - AZURE_OPENAI_API_VERSION (optional, default: "2024-02-01")

    Other provider secrets (optional):
        - OPENAI_API_KEY
        - ANTHROPIC_API_KEY
        - DEEPSEEK_API_KEY
        - QWENCODE_API_KEY
        - GROQ_API_KEY
        - OPENROUTER_API_KEY
    """
    import asyncio

    # Use async version internally
    try:
        asyncio.get_running_loop()
        # If we're already in an async context, we need to run in a new thread
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(asyncio.run, load_llm_config_async())
            return future.result()
    except RuntimeError:
        # No running loop - we can use asyncio.run directly
        return asyncio.run(load_llm_config_async())


async def load_llm_config_async() -> LlmConfiguration:
    """
    Async version of load_llm_config using SecretManager.

    Use this in async contexts for better performance.
    """
    from warden.secrets import SecretManager

    manager = SecretManager()

    # Create base configuration
    config = LlmConfiguration(
        default_provider=LlmProvider.AZURE_OPENAI,
        fallback_providers=[]
    )

    # Set default models for all providers
    for provider, model in DEFAULT_MODELS.items():
        provider_config = config.get_provider_config(provider)
        if provider_config:
            provider_config.default_model = model

    # Track which providers are configured
    configured_providers: list[LlmProvider] = []

    # Get all secrets at once for efficiency
    secrets = await manager.get_secrets([
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_DEPLOYMENT_NAME",
        "AZURE_OPENAI_API_VERSION",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "DEEPSEEK_API_KEY",
        "QWENCODE_API_KEY",
        "GROQ_API_KEY",
        "OPENROUTER_API_KEY",
    ])

    # Configure Azure OpenAI (primary provider for Warden)
    azure_api_key = secrets["AZURE_OPENAI_API_KEY"]
    azure_endpoint = secrets["AZURE_OPENAI_ENDPOINT"]
    azure_deployment = secrets["AZURE_OPENAI_DEPLOYMENT_NAME"]
    azure_api_version = secrets["AZURE_OPENAI_API_VERSION"]

    if azure_api_key.found and azure_endpoint.found and azure_deployment.found:
        config.azure_openai.api_key = azure_api_key.value
        config.azure_openai.endpoint = azure_endpoint.value
        config.azure_openai.default_model = azure_deployment.value
        config.azure_openai.api_version = azure_api_version.value or "2024-02-01"
        config.azure_openai.enabled = True
        configured_providers.append(LlmProvider.AZURE_OPENAI)

    # Configure OpenAI
    openai_secret = secrets["OPENAI_API_KEY"]
    if openai_secret.found:
        config.openai.api_key = openai_secret.value
        config.openai.enabled = True
        configured_providers.append(LlmProvider.OPENAI)

    # Configure Anthropic
    anthropic_secret = secrets["ANTHROPIC_API_KEY"]
    if anthropic_secret.found:
        config.anthropic.api_key = anthropic_secret.value
        config.anthropic.enabled = True
        configured_providers.append(LlmProvider.ANTHROPIC)

    # Configure DeepSeek
    deepseek_secret = secrets["DEEPSEEK_API_KEY"]
    if deepseek_secret.found:
        config.deepseek.api_key = deepseek_secret.value
        config.deepseek.enabled = True
        configured_providers.append(LlmProvider.DEEPSEEK)

    # Configure QwenCode
    qwencode_secret = secrets["QWENCODE_API_KEY"]
    if qwencode_secret.found:
        config.qwencode.api_key = qwencode_secret.value
        config.qwencode.enabled = True
        configured_providers.append(LlmProvider.QWENCODE)

    # Configure Groq
    groq_secret = secrets["GROQ_API_KEY"]
    if groq_secret.found:
        config.groq.api_key = groq_secret.value
        config.groq.enabled = True
        configured_providers.append(LlmProvider.GROQ)

    # Configure OpenRouter
    openrouter_secret = secrets["OPENROUTER_API_KEY"]
    if openrouter_secret.found:
        config.openrouter.api_key = openrouter_secret.value
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
