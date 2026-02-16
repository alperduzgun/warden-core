"""
LLM Configuration

Supports multi-provider configuration with fallback chain.
Providers: DeepSeek, QwenCode, Anthropic, OpenAI, Azure OpenAI, Groq, OpenRouter
"""

import contextlib
from dataclasses import dataclass, field

from .types import LlmProvider


@dataclass
class ProviderConfig:
    """
    Configuration for a specific LLM provider

    Matches C# ProviderConfig
    Security: API keys should be loaded from environment variables
    """

    api_key: str | None = None
    endpoint: str | None = None
    default_model: str | None = None
    api_version: str | None = None  # For Azure OpenAI
    enabled: bool = True
    concurrency: int = 4  # Max concurrent requests for this provider

    def validate(self, provider_name: str) -> list[str]:
        """
        Validate provider configuration

        Returns:
            List of validation errors (empty if valid)
        """
        errors = []

        if not self.api_key:
            # Local providers don't require an API key
            local_providers = {"ollama", "claude_code"}
            if provider_name.lower() not in local_providers:
                errors.append(f"{provider_name}: API key is required but not configured")
        elif len(self.api_key) < 10 and provider_name.lower() not in {"ollama", "claude_code"}:
            errors.append(f"{provider_name}: API key appears invalid (too short)")

        if not self.default_model:
            errors.append(f"{provider_name}: Default model is required but not configured")

        # Validate endpoint URL if provided
        if self.endpoint and not self.endpoint.startswith(("http://", "https://")):
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
    ollama: ProviderConfig = field(default_factory=ProviderConfig)
    claude_code: ProviderConfig = field(default_factory=ProviderConfig)  # Local Claude Code CLI/SDK

    # Model Tiering (Optional)
    smart_model: str | None = None  # High-reasoning model (e.g. gpt-4o)
    fast_model: str | None = None  # Fast/Cheap model (e.g. gpt-4o-mini)
    fast_tier_providers: list[LlmProvider] = field(default_factory=lambda: [LlmProvider.OLLAMA])
    max_concurrency: int = 4  # Global max concurrent requests

    def get_provider_config(self, provider: LlmProvider) -> ProviderConfig | None:
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
            LlmProvider.OPENROUTER: self.openrouter,
            LlmProvider.OLLAMA: self.ollama,
            LlmProvider.CLAUDE_CODE: self.claude_code,
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
    LlmProvider.OPENROUTER: "anthropic/claude-3.5-sonnet",
    LlmProvider.OLLAMA: "qwen2.5-coder:0.5b",
    LlmProvider.CLAUDE_CODE: "claude-code-default",  # Placeholder - actual model controlled by `claude config`
}


def create_default_config() -> LlmConfiguration:
    """
    Create a default LLM configuration

    Note: API keys must be set from environment variables
    """
    config = LlmConfiguration(
        default_provider=LlmProvider.DEEPSEEK, fallback_providers=[LlmProvider.QWENCODE, LlmProvider.ANTHROPIC]
    )

    # Set default models
    for provider, model in DEFAULT_MODELS.items():
        provider_config = config.get_provider_config(provider)
        if provider_config:
            provider_config.default_model = model

    return config


def load_llm_config(config_override: dict | None = None) -> LlmConfiguration:
    """
    Load LLM configuration using SecretManager.

    Args:
        config_override: Optional dictionary of overrides (e.g. from config.yaml)
    """
    import asyncio
    from pathlib import Path

    import yaml

    # Auto-load from .warden/config.yaml if no override provided
    if config_override is None:
        config_yaml_path = Path.cwd() / ".warden" / "config.yaml"
        if config_yaml_path.exists():
            try:
                with open(config_yaml_path) as f:
                    project_config = yaml.safe_load(f)
                    config_override = project_config.get("llm", {})
            except Exception:
                pass  # Fall back to default behavior

    # Use async version internally
    try:
        asyncio.get_running_loop()
        # If we're already in an async context, we need to run in a new thread
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(asyncio.run, load_llm_config_async(config_override))
            return future.result()
    except RuntimeError:
        # No running loop - we can use asyncio.run directly
        return asyncio.run(load_llm_config_async(config_override))


async def _check_ollama_availability(endpoint: str) -> bool:
    """
    Fast check if Ollama is running using httpx.
    Fail-fast: very short timeout to avoid slowing down startup.
    """
    import httpx

    try:
        async with httpx.AsyncClient(timeout=0.5) as client:
            response = await client.get(endpoint)
            return response.status_code == 200
    except Exception:
        return False


async def _check_claude_code_availability() -> bool:
    """
    Fast check if Claude Code CLI is installed and accessible.
    Fail-fast: very short timeout to avoid slowing down startup.
    """
    import asyncio
    import shutil

    # First check if claude command exists in PATH
    if not shutil.which("claude"):
        return False

    try:
        # Run claude --version to verify it's working
        process = await asyncio.create_subprocess_exec(  # warden-ignore
            "claude",
            "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(process.communicate(), timeout=2.0)
        return process.returncode == 0
    except (asyncio.TimeoutError, Exception):
        return False


async def load_llm_config_async(config_override: dict | None = None) -> LlmConfiguration:
    """
    Async version of load_llm_config using SecretManager.

    Use this in async contexts for better performance.
    """
    from warden.secrets import get_manager

    # Use singleton manager to avoid redundant provider initialization
    manager = get_manager()

    # Check if explicit provider override exists - we'll prioritize it
    explicit_provider_override = None
    if config_override and "provider" in config_override:
        with contextlib.suppress(ValueError):
            explicit_provider_override = LlmProvider(config_override["provider"])

    # Create base configuration
    config = LlmConfiguration(default_provider=LlmProvider.AZURE_OPENAI, fallback_providers=[])

    # Set default models for all providers
    for provider, model in DEFAULT_MODELS.items():
        provider_config = config.get_provider_config(provider)
        if provider_config:
            provider_config.default_model = model

    # Track which providers are configured
    configured_providers: list[LlmProvider] = []

    # Get all secrets at once for efficiency (uses SecretManager cache)
    secrets = await manager.get_secrets_async(
        [
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
            "WARDEN_SMART_MODEL",
            "WARDEN_FAST_MODEL",
            "WARDEN_LLM_CONCURRENCY",
            "WARDEN_FAST_TIER_PRIORITY",
            "OLLAMA_HOST",
            "CLAUDE_CODE_ENABLED",
            "CLAUDE_CODE_MODE",
        ]
    )

    # Summary log instead of individual secret_not_found logs
    found_keys = [k for k, v in secrets.items() if v.found]
    import structlog

    logger = structlog.get_logger(__name__)
    if found_keys:
        logger.debug("secrets_loaded", count=len(found_keys), keys=found_keys)

    # Model Tiering & Concurrency
    smart_model_secret = secrets.get("WARDEN_SMART_MODEL")
    if smart_model_secret:
        config.smart_model = smart_model_secret.value

    fast_model_secret = secrets.get("WARDEN_FAST_MODEL")
    if fast_model_secret:
        config.fast_model = fast_model_secret.value

    fast_tier_priority_secret = secrets.get("WARDEN_FAST_TIER_PRIORITY")
    if fast_tier_priority_secret and fast_tier_priority_secret.found:
        providers_str = fast_tier_priority_secret.value
        if providers_str:
            try:
                config.fast_tier_providers = [
                    LlmProvider(p.strip().lower()) for p in providers_str.split(",") if p.strip()
                ]
            except ValueError as e:
                import structlog

                logger = structlog.get_logger(__name__)
                logger.warning("invalid_fast_tier_priority", value=providers_str, error=str(e))

    concurrency_secret = secrets.get("WARDEN_LLM_CONCURRENCY")
    if concurrency_secret and concurrency_secret.found:
        with contextlib.suppress(ValueError, TypeError):
            config.max_concurrency = int(concurrency_secret.value)

    # Configure Azure OpenAI (primary provider for Warden)
    azure_api_key = secrets.get("AZURE_OPENAI_API_KEY")
    azure_endpoint = secrets.get("AZURE_OPENAI_ENDPOINT")
    azure_deployment = secrets.get("AZURE_OPENAI_DEPLOYMENT_NAME")
    azure_api_version = secrets.get("AZURE_OPENAI_API_VERSION")

    if (
        azure_api_key
        and azure_api_key.found
        and azure_endpoint
        and azure_endpoint.found
        and azure_deployment
        and azure_deployment.found
    ):
        config.azure_openai.api_key = azure_api_key.value
        config.azure_openai.endpoint = azure_endpoint.value
        config.azure_openai.default_model = azure_deployment.value
        config.azure_openai.api_version = (azure_api_version.value if azure_api_version else None) or "2024-02-01"
        config.azure_openai.enabled = True
        configured_providers.append(LlmProvider.AZURE_OPENAI)

    # Configure OpenAI
    openai_secret = secrets.get("OPENAI_API_KEY")
    if openai_secret and openai_secret.found:
        config.openai.api_key = openai_secret.value
        config.openai.enabled = True
        configured_providers.append(LlmProvider.OPENAI)

    # Configure Anthropic
    anthropic_secret = secrets.get("ANTHROPIC_API_KEY")
    if anthropic_secret and anthropic_secret.found:
        config.anthropic.api_key = anthropic_secret.value
        config.anthropic.enabled = True
        configured_providers.append(LlmProvider.ANTHROPIC)

    # Configure DeepSeek
    deepseek_secret = secrets.get("DEEPSEEK_API_KEY")
    if deepseek_secret and deepseek_secret.found:
        config.deepseek.api_key = deepseek_secret.value
        config.deepseek.enabled = True
        configured_providers.append(LlmProvider.DEEPSEEK)

    # Configure QwenCode
    qwencode_secret = secrets.get("QWENCODE_API_KEY")
    if qwencode_secret and qwencode_secret.found:
        config.qwencode.api_key = qwencode_secret.value
        config.qwencode.enabled = True
        configured_providers.append(LlmProvider.QWENCODE)

    # Configure Groq
    groq_secret = secrets.get("GROQ_API_KEY")
    if groq_secret and groq_secret.found:
        config.groq.api_key = groq_secret.value
        config.groq.enabled = True
        configured_providers.append(LlmProvider.GROQ)

    # Configure OpenRouter
    openrouter_secret = secrets.get("OPENROUTER_API_KEY")
    if openrouter_secret and openrouter_secret.found:
        config.openrouter.api_key = openrouter_secret.value
        config.openrouter.enabled = True
        configured_providers.append(LlmProvider.OPENROUTER)

    # Configure Ollama (Local)
    try:
        ollama_host_secret = secrets.get("OLLAMA_HOST")
    except Exception:
        ollama_host_secret = None

    ollama_endpoint = "http://localhost:11434"
    if ollama_host_secret and hasattr(ollama_host_secret, "found") and ollama_host_secret.found:
        ollama_endpoint = ollama_host_secret.value or ollama_endpoint

    config.ollama.endpoint = ollama_endpoint
    config.ollama.enabled = True  # Enabled by default for dual-tier fallback
    configured_providers.append(LlmProvider.OLLAMA)

    # Configure Claude Code (Local CLI/SDK)
    # Check if CLAUDE_CODE_ENABLED is set, or auto-detect if claude CLI is available
    # Valid modes: cli (default), sdk
    _valid_claude_modes = {"cli", "sdk"}
    claude_code_enabled = secrets.get("CLAUDE_CODE_ENABLED")
    if claude_code_enabled and claude_code_enabled.found and claude_code_enabled.value.lower() in ("true", "1", "yes"):
        config.claude_code.enabled = True
        claude_code_mode = secrets.get("CLAUDE_CODE_MODE")
        if claude_code_mode and claude_code_mode.found:
            mode = claude_code_mode.value.lower().strip()
            # Validate mode (fail-fast)
            if mode not in _valid_claude_modes:
                import structlog

                _logger = structlog.get_logger(__name__)
                _logger.warning(
                    "invalid_claude_code_mode",
                    mode=mode,
                    valid_modes=list(_valid_claude_modes),
                    fallback="cli",
                )
                mode = "cli"
            config.claude_code.endpoint = mode
        else:
            config.claude_code.endpoint = "cli"
        configured_providers.append(LlmProvider.CLAUDE_CODE)
    elif await _check_claude_code_availability():
        # Auto-detected: Claude Code CLI is installed
        config.claude_code.enabled = True
        config.claude_code.endpoint = "cli"
        configured_providers.append(LlmProvider.CLAUDE_CODE)

    # --- AUTO-PILOT LOGIC ---
    # Determine Fast Tier Chain based on available credentials and service health

    detected_fast_tier = []

    # Priority 1: Groq (Cloud Speed)
    if LlmProvider.GROQ in configured_providers:
        detected_fast_tier.append(LlmProvider.GROQ)

    # Priority 2: Ollama (Local/Free) - Only if service is actually running
    # This fail-fast check prevents adding a dead service to the chain
    if await _check_ollama_availability(ollama_endpoint):
        detected_fast_tier.append(LlmProvider.OLLAMA)

    # Apply Auto-Detected chain if no manual override exists
    # If WARDEN_FAST_TIER_PRIORITY was set earlier, we honor it.
    # Otherwise, we use our smart auto-detected list.
    if not config.fast_tier_providers or config.fast_tier_providers == [LlmProvider.OLLAMA]:
        # If default, replace with auto-detected if we found anything good
        if detected_fast_tier:
            config.fast_tier_providers = detected_fast_tier

    # Prioritize explicit provider override from config.yaml
    if explicit_provider_override:
        # Ensure the explicit provider is enabled
        provider_cfg = config.get_provider_config(explicit_provider_override)
        if provider_cfg and not provider_cfg.enabled:
            provider_cfg.enabled = True

        # Remove from configured_providers if already there (to avoid duplicates)
        if explicit_provider_override in configured_providers:
            configured_providers.remove(explicit_provider_override)

        # Add to the front of the list
        configured_providers.insert(0, explicit_provider_override)

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

    # Apply manual overrides if provided (from config.yaml)
    if config_override:
        if "fast_tier_providers" in config_override:
            providers = config_override["fast_tier_providers"]
            if isinstance(providers, list):
                config.fast_tier_providers = [LlmProvider(p.strip().lower()) for p in providers if isinstance(p, str)]

        if "smart_model" in config_override:
            config.smart_model = config_override["smart_model"]

        if "fast_model" in config_override:
            config.fast_model = config_override["fast_model"]

    return config
