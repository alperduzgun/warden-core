"""Secret manager - chain of responsibility orchestrator."""

import os
from datetime import datetime

import structlog

from ..domain.enums import SecretSource
from ..domain.models import SecretValue
from ..providers.azure_keyvault_provider import AzureKeyVaultProvider
from ..providers.base import ISecretProvider
from ..providers.dotenv_provider import DotEnvSecretProvider
from ..providers.env_provider import EnvSecretProvider

logger = structlog.get_logger(__name__)


class SecretManager:
    """Manages secret retrieval from multiple sources.

    Uses chain of responsibility pattern - tries each provider in priority order.

    Auto-detection:
    - If AZURE_KEY_VAULT_URL is set -> Azure Key Vault first
    - If GITHUB_ACTIONS=true -> Env vars only (secrets already exposed)
    - Otherwise -> DotEnv first, then Env

    Example:
        # Auto-configured based on environment
        manager = SecretManager()
        result = await manager.get_secret("AZURE_OPENAI_API_KEY")

        if result.found:
            print(f"Value from {result.source.value}")

        # Custom provider chain
        manager = SecretManager(providers=[
            EnvSecretProvider(priority=1),
            DotEnvSecretProvider(priority=2),
        ])
    """

    def __init__(
        self,
        providers: list[ISecretProvider] | None = None,
        cache_enabled: bool = True,
    ):
        """Initialize the secret manager.

        Args:
            providers: Custom list of providers. If None, auto-configures.
            cache_enabled: Whether to cache secret values.
        """
        self._cache: dict[str, SecretValue] = {}
        self._cache_enabled = cache_enabled

        if providers:
            self._providers = sorted(providers, key=lambda p: p.priority)
        else:
            self._providers = self._auto_configure_providers()

    def _auto_configure_providers(self) -> list[ISecretProvider]:
        """Auto-configure providers based on environment.

        Detection logic:
        1. If AZURE_KEY_VAULT_URL is set -> Add Azure Key Vault (priority 0)
        2. If GITHUB_ACTIONS=true -> Only use env vars (secrets exposed by GH)
        3. Otherwise -> DotEnv first (priority 1), then Env (priority 2)

        Returns:
            List of providers sorted by priority.
        """
        providers: list[ISecretProvider] = []

        # Check for Azure Key Vault
        if os.environ.get("AZURE_KEY_VAULT_URL"):
            providers.append(AzureKeyVaultProvider(priority=0))
            logger.info("secret_provider_enabled", provider="azure_keyvault")

        # Check for GitHub Actions
        is_github_actions = os.environ.get("GITHUB_ACTIONS") == "true"

        if is_github_actions:
            # In GitHub Actions, secrets are already in env
            providers.append(EnvSecretProvider(priority=1))
            logger.info("secret_provider_mode", mode="github_actions")
        else:
            # Local development - try .env first, then env
            providers.append(DotEnvSecretProvider(priority=1))
            providers.append(EnvSecretProvider(priority=2))
            logger.info("secret_provider_mode", mode="local_development")

        return sorted(providers, key=lambda p: p.priority)

    async def get_secret(self, key: str) -> SecretValue:
        """Get a secret by key, trying all providers in order.

        Args:
            key: Secret key (e.g., "AZURE_OPENAI_API_KEY")

        Returns:
            SecretValue with value and source, or NOT_FOUND.
        """
        # Check cache first
        if self._cache_enabled and key in self._cache:
            cached = self._cache[key]
            return SecretValue(
                key=cached.key,
                value=cached.value,
                source=cached.source,
                retrieved_at=datetime.now(),
                cached=True,
            )

        # Try each provider in priority order
        for provider in self._providers:
            if not await provider.is_available():
                continue

            result = await provider.get_secret(key)
            if result.found:
                logger.debug(
                    "secret_retrieved",
                    key=key,
                    source=result.source.value,
                )
                if self._cache_enabled:
                    self._cache[key] = result
                return result

        logger.debug("secret_not_found", key=key)
        return SecretValue(
            key=key,
            value=None,
            source=SecretSource.NOT_FOUND,
            retrieved_at=datetime.now(),
        )

    async def get_secrets(self, keys: list[str]) -> dict[str, SecretValue]:
        """Get multiple secrets at once.

        Args:
            keys: List of secret keys.

        Returns:
            Dict mapping key to SecretValue.
        """
        results = {}
        for key in keys:
            results[key] = await self.get_secret(key)
        return results

    def clear_cache(self) -> None:
        """Clear the secret cache."""
        self._cache.clear()

    async def cleanup(self) -> None:
        """Cleanup all providers."""
        for provider in self._providers:
            await provider.cleanup()

    @property
    def providers(self) -> list[ISecretProvider]:
        """Get the list of configured providers.

        Returns:
            List of providers in priority order.
        """
        return self._providers.copy()


# Module-level singleton and convenience function
_manager: SecretManager | None = None


async def get_secret(key: str) -> str | None:
    """Get a secret value (convenience function).

    Uses a module-level SecretManager singleton.

    Args:
        key: Secret key.

    Returns:
        Secret value or None if not found.

    Example:
        api_key = await get_secret("AZURE_OPENAI_API_KEY")
        if api_key:
            # Use the API key
            pass
    """
    global _manager
    if _manager is None:
        _manager = SecretManager()

    result = await _manager.get_secret(key)
    return result.value if result.found else None


def get_manager() -> SecretManager:
    """Get or create the module-level SecretManager.

    Returns:
        The singleton SecretManager instance.
    """
    global _manager
    if _manager is None:
        _manager = SecretManager()
    return _manager


def reset_manager() -> None:
    """Reset the module-level SecretManager.

    Useful for testing or reconfiguration.
    """
    global _manager
    _manager = None
