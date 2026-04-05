"""
LLM Configuration

Supports multi-provider configuration with fallback chain.
Providers: DeepSeek, QwenCode, Anthropic, OpenAI, Azure OpenAI, Groq
"""

import contextlib
import ipaddress
import os
import urllib.parse
from dataclasses import dataclass, field

from .types import LlmProvider

# Providers that run locally or on a private LAN and do not require an API key.
# Used for both SSRF allow_lan and API-key-required logic.
_LOCAL_PROVIDERS: frozenset[str] = frozenset({"ollama", "claude_code", "codex", "qwencode", "qwen_cli"})

# Hostnames that resolve to loopback but aren't raw IP literals —
# `ipaddress.ip_address()` would raise ValueError for these, so we block them explicitly.
_LOOPBACK_HOSTNAMES: frozenset[str] = frozenset({"localhost", "ip6-localhost", "ip6-loopback"})


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
            if provider_name.lower() not in _LOCAL_PROVIDERS:
                errors.append(f"{provider_name}: API key is required but not configured")
        elif len(self.api_key) < 10 and provider_name.lower() not in _LOCAL_PROVIDERS:
            errors.append(f"{provider_name}: API key appears invalid (too short)")

        if not self.default_model:
            errors.append(f"{provider_name}: Default model is required but not configured")

        # Validate endpoint URL if provided — check protocol and SSRF safety (#640)
        # Local providers (Ollama, claude_code, etc.) may use LAN addresses.
        _is_local = provider_name.lower() in _LOCAL_PROVIDERS
        if self.endpoint:
            if not self.endpoint.startswith(("http://", "https://")):
                errors.append(f"{provider_name}: Endpoint must use HTTP or HTTPS protocol")
            elif not _is_safe_endpoint(self.endpoint, allow_lan=_is_local):
                errors.append(
                    f"{provider_name}: Endpoint targets a private/reserved address — "
                    "SSRF protection blocked this endpoint"
                )

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
    ollama: ProviderConfig = field(default_factory=ProviderConfig)
    claude_code: ProviderConfig = field(default_factory=ProviderConfig)  # Local Claude Code CLI/SDK
    codex: ProviderConfig = field(default_factory=ProviderConfig)  # Local Codex CLI

    # Model Tiering (Optional)
    smart_model: str | None = None  # High-reasoning model (e.g. gpt-4o)
    fast_model: str | None = None  # Fast/Cheap model (e.g. gpt-4o-mini)
    fast_tier_providers: list[LlmProvider] = field(default_factory=lambda: [LlmProvider.OLLAMA])
    smart_tier_provider: LlmProvider | None = None  # Route smart tier to a different provider (e.g. Groq)
    smart_tier_model: str | None = None  # Model for the smart tier provider override
    max_concurrency: int = 4  # Global max concurrent requests

    # Rate limits (used by LLMPhaseConfig in analysis/classification executors)
    tpm_limit: int = 1000  # Tokens per minute (free-tier default)
    rpm_limit: int = 6  # Requests per minute (free-tier default)

    # Per-provider rate limit overrides from config.yaml.
    # Keys: provider name (e.g. "openai", "groq") → {"tpm": int, "rpm": int}
    # Takes precedence over the hard-coded defaults in GlobalRateLimiter.
    provider_rate_limits: dict[str, dict[str, int]] | None = None

    # Centralized token budgets for all LLM consumers (triage-aware).
    # Keys: category name → {"deep": int, "fast": int}
    # Overrides built-in defaults in warden.shared.utils.llm_context.DEFAULT_TOKEN_BUDGETS.
    # Populated from config.yaml llm.token_budgets section.
    token_budgets: dict[str, dict[str, int]] = field(default_factory=dict)

    # Legacy per-frame fields (kept for backward-compat config.yaml parsing).
    security_token_budget: int = 2400
    security_token_budget_fast: int = 400
    resilience_token_budget: int = 3000
    resilience_token_budget_fast: int = 500

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
            LlmProvider.QWEN_CLI: self.qwencode,  # CLI shares DashScope config
            LlmProvider.ANTHROPIC: self.anthropic,
            LlmProvider.OPENAI: self.openai,
            LlmProvider.AZURE_OPENAI: self.azure_openai,
            LlmProvider.GROQ: self.groq,
            LlmProvider.OLLAMA: self.ollama,
            LlmProvider.CLAUDE_CODE: self.claude_code,
            LlmProvider.CODEX: self.codex,
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
    LlmProvider.GROQ: "llama-3.3-70b-versatile",
    LlmProvider.OLLAMA: "qwen2.5-coder:3b",
    LlmProvider.CLAUDE_CODE: "claude-code-default",  # Placeholder - actual model controlled by `claude config`
    LlmProvider.CODEX: "codex-local",  # Placeholder - actual model controlled by ~/.codex/config.toml
}

# CLI-tool providers that manage their own model selection.
# Duplicated from factory.py to avoid circular imports (config ← types, factory ← config).
_SINGLE_TIER_PROVIDERS: frozenset[LlmProvider] = frozenset(
    {
        LlmProvider.CLAUDE_CODE,
        LlmProvider.CODEX,
    }
)


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


def _load_global_llm_config() -> dict | None:
    """Load LLM config from ~/.warden/config.yaml if it exists."""
    from pathlib import Path

    import yaml

    global_config_path = Path.home() / ".warden" / "config.yaml"
    if not global_config_path.exists():
        return None
    try:
        with open(global_config_path) as f:
            config = yaml.safe_load(f)
            return config.get("llm", {}) if config else None
    except Exception:
        return None


def load_llm_config(config_override: dict | None = None) -> LlmConfiguration:
    """
    Load LLM configuration using SecretManager.

    Args:
        config_override: Optional dictionary of overrides (e.g. from config.yaml)
    """
    import asyncio
    from pathlib import Path

    import yaml

    # Load global config from ~/.warden/config.yaml as lowest-priority base
    global_llm = _load_global_llm_config()

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

    # Merge: global is base, project overrides
    if global_llm:
        if config_override:
            config_override = {**global_llm, **config_override}
        else:
            config_override = global_llm

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


def _is_safe_endpoint(url: str, allow_lan: bool = False) -> bool:
    """Block SSRF targets for LLM provider endpoints. (#640)

    Uses the stdlib ``ipaddress`` module for accurate IP classification —
    immune to decimal/hex/octal IP encoding and IPv4-mapped IPv6 bypasses
    that fool naive ``startswith`` prefix checks.

    Args:
        url: Endpoint URL to validate.
        allow_lan: If True, RFC1918 private-LAN ranges are permitted (for
            local providers like Ollama that legitimately run on a home or
            office network). Loopback and link-local (metadata) services
            are always blocked regardless of this flag.

    Always blocked:
        loopback (127/8, ::1), link-local/metadata (169.254/16, fe80::/10),
        ULA (fc00::/7), unspecified (0.0.0.0/::), localhost by name.

    Blocked when allow_lan=False (cloud providers):
        RFC1918 (10/8, 172.16/12, 192.168/16).
    """
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        host = parsed.hostname or ""
        if not host:
            return False

        # Block well-known loopback hostnames that won't be caught by IP parsing.
        if host.lower() in _LOOPBACK_HOSTNAMES:
            return False

        # Parse as an IP address for accurate classification.
        # Raises ValueError for hostnames — handled below.
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            # Not a raw IP literal — it's a hostname.
            # We can't resolve DNS at config time; return True and let the
            # HTTP client enforce network-level restrictions at request time.
            return True

        # Always block: loopback, unspecified (0.0.0.0 / ::), link-local
        if ip.is_loopback or ip.is_unspecified or ip.is_link_local:
            return False

        # For IPv4-mapped IPv6 (::ffff:x.x.x.x) apply the same rules to the
        # mapped IPv4 address — prevents ::ffff:127.0.0.1 style bypasses.
        mapped: ipaddress.IPv4Address | None = getattr(ip, "ipv4_mapped", None)
        if mapped is not None:
            if mapped.is_loopback or mapped.is_unspecified or mapped.is_link_local:
                return False
            if not allow_lan and mapped.is_private:
                return False

        # RFC1918 — blocked for cloud providers, allowed for local providers
        if not allow_lan and ip.is_private:
            return False

        return True
    except Exception:
        return False


def _validate_ollama_endpoint(url: str) -> bool:
    """Block SSRF targets for Ollama endpoints. (#310)

    Ollama runs locally or on LAN — RFC1918 is permitted (allow_lan=True).
    Cloud metadata services (169.254.x.x) are always blocked.
    """
    return _is_safe_endpoint(url, allow_lan=True)


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


async def _check_codex_availability() -> bool:
    """
    Fast check if Codex CLI is installed and responsive.
    Mirrors the Claude Code check: require both PATH presence AND a working binary.
    """
    import asyncio
    import shutil

    if not shutil.which("codex"):
        return False

    try:
        process = await asyncio.create_subprocess_exec(
            "codex",
            "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(process.communicate(), timeout=2.0)
        return process.returncode == 0
    except (asyncio.TimeoutError, Exception):
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

    # Determine explicit provider override — env var takes precedence over config.yaml.
    # This allows CI to override local defaults (e.g. WARDEN_LLM_PROVIDER=groq in CI
    # while config.yaml has provider: claude_code for local development).
    # If running in CI and config.yaml has a llm.ci subsection, merge it so that
    # `warden config llm edit` CI tab settings take effect.
    is_ci = bool(os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"))
    if is_ci and config_override and "ci" in config_override:
        ci_overrides = config_override.get("ci", {})
        config_override = {k: v for k, v in config_override.items() if k != "ci"}
        config_override = {**config_override, **ci_overrides}

    explicit_provider_override = None
    _force_auto = False
    env_provider = os.environ.get("WARDEN_LLM_PROVIDER", "").strip().lower()
    if env_provider == "auto":
        _force_auto = True  # Env "auto" overrides config explicit provider too
    elif env_provider:
        with contextlib.suppress(ValueError):
            explicit_provider_override = LlmProvider(env_provider)
    elif config_override and ("provider" in config_override or "default_provider" in config_override):
        _provider_val = config_override.get("provider") or config_override.get("default_provider")
        if _provider_val and str(_provider_val).strip().lower() != "auto":
            with contextlib.suppress(ValueError):
                explicit_provider_override = LlmProvider(str(_provider_val).strip().lower())

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
            "WARDEN_SMART_MODEL",
            "WARDEN_FAST_MODEL",
            "WARDEN_LLM_CONCURRENCY",
            "WARDEN_FAST_TIER_PRIORITY",
            "WARDEN_LLM_PROVIDER",
            "WARDEN_SMART_TIER_PROVIDER",
            "WARDEN_SMART_TIER_MODEL",
            "WARDEN_BLOCKED_PROVIDERS",
            "OLLAMA_HOST",
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

    concurrency_secret = secrets.get("WARDEN_LLM_CONCURRENCY")
    if concurrency_secret and concurrency_secret.found:
        with contextlib.suppress(ValueError, TypeError):
            config.max_concurrency = int(concurrency_secret.value)

    # Smart Tier Provider Override (e.g. route smart calls to Groq while fast stays on Ollama)
    smart_tier_provider_secret = secrets.get("WARDEN_SMART_TIER_PROVIDER")
    if smart_tier_provider_secret and smart_tier_provider_secret.found:
        with contextlib.suppress(ValueError):
            config.smart_tier_provider = LlmProvider(smart_tier_provider_secret.value.strip().lower())
    smart_tier_model_secret = secrets.get("WARDEN_SMART_TIER_MODEL")
    if smart_tier_model_secret and smart_tier_model_secret.found:
        config.smart_tier_model = smart_tier_model_secret.value

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

    # Configure Ollama (Local)
    try:
        ollama_host_secret = secrets.get("OLLAMA_HOST")
    except Exception:
        ollama_host_secret = None

    ollama_endpoint = "http://localhost:11434"
    if ollama_host_secret and hasattr(ollama_host_secret, "found") and ollama_host_secret.found:
        candidate = ollama_host_secret.value or ollama_endpoint
        if _validate_ollama_endpoint(candidate):
            ollama_endpoint = candidate
        else:
            import structlog as _structlog

            _structlog.get_logger(__name__).warning(
                "ollama_endpoint_blocked_ssrf",
                endpoint=candidate,
                message="OLLAMA_HOST rejected — falling back to localhost",
            )

    config.ollama.endpoint = ollama_endpoint
    config.ollama.enabled = True  # Enabled by default for dual-tier fallback
    configured_providers.append(LlmProvider.OLLAMA)

    # Configure Claude Code (Local CLI/SDK) - auto-detect only
    if await _check_claude_code_availability():
        config.claude_code.enabled = True
        config.claude_code.endpoint = "cli"
        configured_providers.append(LlmProvider.CLAUDE_CODE)

    # Configure Codex (Local CLI) - auto-detect only (mirrors Claude Code check)
    if await _check_codex_availability():
        config.codex.enabled = True
        config.codex.endpoint = "cli"
        configured_providers.append(LlmProvider.CODEX)

    # Configure Qwen Code (Local CLI) - auto-detect
    import shutil as _shutil
    if _shutil.which("qwen"):
        config.qwencode.enabled = True
        config.qwencode.endpoint = "cli"
        configured_providers.append(LlmProvider.QWEN_CLI)

    # --- AUTO-DETECT LOGIC ---
    # Runs when NO explicit provider was configured (provider: auto or absent).
    if not explicit_provider_override or _force_auto:
        from warden.shared.utils.ci_detection import is_ci as _is_ci_check

        _in_ci = _is_ci_check()
        auto_provider: LlmProvider | None = None

        # Priority 1: qwen_cli (local, free) — skip in CI
        if not _in_ci and LlmProvider.QWEN_CLI in configured_providers:
            auto_provider = LlmProvider.QWEN_CLI
            logger.info("auto_detect_provider", provider="qwen_cli", reason="qwen binary found (non-CI)")

        # Priority 2: Groq (fast cloud, free tier)
        if not auto_provider and LlmProvider.GROQ in configured_providers:
            auto_provider = LlmProvider.GROQ
            logger.info("auto_detect_provider", provider="groq", reason="GROQ_API_KEY set")

        # Priority 3: Ollama (local, free) — only if running
        if not auto_provider and await _check_ollama_availability(ollama_endpoint):
            auto_provider = LlmProvider.OLLAMA
            logger.info("auto_detect_provider", provider="ollama", reason="ollama responding")

        # Priority 4: QwenCode API
        if not auto_provider and LlmProvider.QWENCODE in configured_providers:
            auto_provider = LlmProvider.QWENCODE
            logger.info("auto_detect_provider", provider="qwencode", reason="QWENCODE_API_KEY set")

        # Priority 5: Anthropic
        if not auto_provider and LlmProvider.ANTHROPIC in configured_providers:
            auto_provider = LlmProvider.ANTHROPIC
            logger.info("auto_detect_provider", provider="anthropic", reason="ANTHROPIC_API_KEY set")

        # Priority 6: OpenAI
        if not auto_provider and LlmProvider.OPENAI in configured_providers:
            auto_provider = LlmProvider.OPENAI
            logger.info("auto_detect_provider", provider="openai", reason="OPENAI_API_KEY set")

        # Priority 7: Claude Code (last resort)
        if not auto_provider and LlmProvider.CLAUDE_CODE in configured_providers:
            auto_provider = LlmProvider.CLAUDE_CODE
            logger.info("auto_detect_provider", provider="claude_code", reason="claude binary found")

        # Promote detected provider to front
        if auto_provider:
            if auto_provider in configured_providers:
                configured_providers.remove(auto_provider)
            configured_providers.insert(0, auto_provider)

        # Build fast tier
        detected_fast_tier: list[LlmProvider] = []
        if LlmProvider.GROQ in configured_providers:
            detected_fast_tier.append(LlmProvider.GROQ)
        if await _check_ollama_availability(ollama_endpoint):
            detected_fast_tier.append(LlmProvider.OLLAMA)
        if LlmProvider.CLAUDE_CODE in configured_providers:
            detected_fast_tier.append(LlmProvider.CLAUDE_CODE)

        if not config.fast_tier_providers or config.fast_tier_providers == [LlmProvider.OLLAMA]:
            if detected_fast_tier:
                config.fast_tier_providers = detected_fast_tier

        if not auto_provider and _in_ci:
            logger.warning("auto_detect_no_provider_ci", reason="No LLM available in CI, deterministic only")
    else:
        config.fast_tier_providers = [explicit_provider_override]
        logger.debug("fast_tier_restricted_explicit_provider", provider=explicit_provider_override.value)

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

    # Sync smart_model with provider override: if provider was explicitly changed
    # (e.g. WARDEN_LLM_PROVIDER=groq) but smart_model still belongs to a different
    # provider (e.g. claude-sonnet-*), reset it to the new provider's default.
    # config.yaml's smart_model is NOT considered "explicitly set" when provider
    # was env-var-overridden — the config.yaml model name likely belongs to the
    # old provider (e.g. claude-sonnet-* in config.yaml but WARDEN_LLM_PROVIDER=groq).
    # Only WARDEN_SMART_MODEL env var counts as an explicit user choice here.
    smart_model_explicitly_set = smart_model_secret and smart_model_secret.found
    if explicit_provider_override and not smart_model_explicitly_set:
        provider_default = DEFAULT_MODELS.get(explicit_provider_override)
        if provider_default and config.smart_model != provider_default:
            config.smart_model = provider_default

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
        ]:
            provider_config.enabled = False

    # Apply manual overrides if provided (from config.yaml)
    if config_override:
        if "fast_tier_providers" in config_override:
            providers = config_override["fast_tier_providers"]
            if isinstance(providers, list):
                config.fast_tier_providers = [LlmProvider(p.strip().lower()) for p in providers if isinstance(p, str)]

        # config.yaml model overrides only apply if provider wasn't changed by env var.
        # If provider was env-var-overridden, config.yaml models belong to the old provider.
        if "smart_model" in config_override and not env_provider:
            config.smart_model = config_override["smart_model"]
        elif "model" in config_override and "smart_model" not in config_override and not env_provider:
            # Alias: llm.model → smart_model (common user expectation)
            config.smart_model = config_override["model"]

        if "fast_model" in config_override and not env_provider:
            config.fast_model = config_override["fast_model"]

        # Smart tier provider routing from config.yaml
        if "smart_tier_provider" in config_override:
            with contextlib.suppress(ValueError):
                config.smart_tier_provider = LlmProvider(config_override["smart_tier_provider"].strip().lower())

        # Rate limits from config.yaml
        if "tpm_limit" in config_override:
            with contextlib.suppress(ValueError, TypeError):
                config.tpm_limit = int(config_override["tpm_limit"])
        if "rpm_limit" in config_override:
            with contextlib.suppress(ValueError, TypeError):
                config.rpm_limit = int(config_override["rpm_limit"])

        # Per-provider rate limit overrides from config.yaml
        if "provider_rate_limits" in config_override:
            raw_prl = config_override["provider_rate_limits"]
            if isinstance(raw_prl, dict):
                parsed_prl: dict[str, dict[str, int]] = {}
                for prov_key, limits in raw_prl.items():
                    if isinstance(limits, dict):
                        parsed_limits: dict[str, int] = {}
                        for limit_key in ("tpm", "rpm"):
                            if limit_key in limits:
                                with contextlib.suppress(ValueError, TypeError):
                                    parsed_limits[limit_key] = int(limits[limit_key])
                        if parsed_limits:
                            parsed_prl[prov_key] = parsed_limits
                if parsed_prl:
                    config.provider_rate_limits = parsed_prl

        # Smart tier provider override from config.yaml (env var takes precedence)
        if "smart_tier_provider" in config_override and not config.smart_tier_provider:
            with contextlib.suppress(ValueError):
                config.smart_tier_provider = LlmProvider(config_override["smart_tier_provider"].strip().lower())
        if "smart_tier_model" in config_override and not config.smart_tier_model:
            config.smart_tier_model = config_override["smart_tier_model"]

        # Centralized token budgets from config.yaml (new format)
        if "token_budgets" in config_override:
            raw_budgets = config_override["token_budgets"]
            if isinstance(raw_budgets, dict):
                for cat, entry in raw_budgets.items():
                    if isinstance(entry, dict):
                        parsed: dict[str, int] = {}
                        for tier_key in ("deep", "fast"):
                            if tier_key in entry:
                                with contextlib.suppress(ValueError, TypeError):
                                    parsed[tier_key] = int(entry[tier_key])
                        if parsed:
                            config.token_budgets[cat] = parsed

        # Legacy per-frame token budget overrides (backward compat) → migrate to new dict
        _LEGACY_MAP = {
            "security_token_budget": ("security", "deep"),
            "security_token_budget_fast": ("security", "fast"),
            "resilience_token_budget": ("resilience", "deep"),
            "resilience_token_budget_fast": ("resilience", "fast"),
        }
        for budget_key, (cat, tier) in _LEGACY_MAP.items():
            if budget_key in config_override:
                with contextlib.suppress(ValueError, TypeError):
                    val = int(config_override[budget_key])
                    setattr(config, budget_key, val)
                    config.token_budgets.setdefault(cat, {})[tier] = val

    # FINAL: Env var override for fast tier — always wins (analogous to WARDEN_LLM_PROVIDER handling)
    env_fast_tier = os.environ.get("WARDEN_FAST_TIER_PRIORITY", "").strip()
    if env_fast_tier:
        try:
            config.fast_tier_providers = [LlmProvider(p.strip().lower()) for p in env_fast_tier.split(",") if p.strip()]
        except ValueError as e:
            logger.warning("invalid_fast_tier_priority_env", value=env_fast_tier, error=str(e))

    # FINAL: Block specified providers from all tiers (e.g. WARDEN_BLOCKED_PROVIDERS=claude_code in CI)
    env_blocked = os.environ.get("WARDEN_BLOCKED_PROVIDERS", "").strip()
    if env_blocked:
        blocked: set[LlmProvider] = set()
        for p in env_blocked.split(","):
            p = p.strip().lower()
            if not p:
                continue
            with contextlib.suppress(ValueError):
                blocked.add(LlmProvider(p))

        if blocked:
            # Remove from fast tier
            config.fast_tier_providers = [p for p in config.fast_tier_providers if p not in blocked]

            # Remove from fallback chain; if default provider is blocked, promote first non-blocked fallback
            if config.default_provider in blocked:
                non_blocked = [p for p in config.fallback_providers if p not in blocked]
                if non_blocked:
                    config.default_provider = non_blocked[0]
                    config.fallback_providers = non_blocked[1:]
                else:
                    logger.warning("all_providers_blocked", blocked=[p.value for p in blocked])
            else:
                config.fallback_providers = [p for p in config.fallback_providers if p not in blocked]

            # Disable blocked provider configs
            for p in blocked:
                cfg = config.get_provider_config(p)
                if cfg:
                    cfg.enabled = False

            logger.debug("providers_blocked", blocked=[p.value for p in blocked])

    # FINAL: CLI-tool providers (Codex, Claude Code) are single-tier by design.
    # They manage model selection internally — fast_tier is irrelevant when they are primary.
    # Clearing here keeps config state consistent with factory.py's SINGLE_TIER_PROVIDERS logic.
    if config.default_provider in _SINGLE_TIER_PROVIDERS:
        config.fast_tier_providers = []
        logger.debug("fast_tier_cleared_single_provider_mode", provider=config.default_provider.value)

    # FINAL: Propagate project-level rate limits (tpm_limit/rpm_limit) to the
    # global rate limiter so that free-tier config.yaml settings take effect for
    # all providers that fall through to the "default" bucket. (#429)
    try:
        from warden.llm.global_rate_limiter import GlobalRateLimiter

        grl = await GlobalRateLimiter.get_instance()
        grl.configure_from_llm_config(config)
    except Exception as _rl_err:  # pragma: no cover — never crash config loading
        logger.debug("global_rate_limiter_configure_failed", error=str(_rl_err))

    return config
