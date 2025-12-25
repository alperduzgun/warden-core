"""Azure Key Vault secret provider."""

import contextlib
import os
from datetime import datetime
from typing import Any

import structlog

from ..domain.enums import SecretSource
from ..domain.models import SecretValue
from .base import ISecretProvider

logger = structlog.get_logger(__name__)


class AzureKeyVaultProvider(ISecretProvider):
    """Reads secrets from Azure Key Vault.

    Requires:
    - azure-identity package
    - azure-keyvault-secrets package
    - AZURE_KEY_VAULT_URL environment variable

    Authentication:
    - Uses DefaultAzureCredential (supports managed identity, CLI, env vars)

    Key Name Conversion:
    - Azure Key Vault uses hyphens, env vars use underscores
    - AZURE_OPENAI_API_KEY -> azure-openai-api-key

    Example:
        provider = AzureKeyVaultProvider()
        result = await provider.get_secret("AZURE_OPENAI_API_KEY")
        # Tries to get "azure-openai-api-key" from vault
    """

    def __init__(self, vault_url: str | None = None, priority: int = 0):
        """Initialize the provider.

        Args:
            vault_url: Azure Key Vault URL. If None, reads from AZURE_KEY_VAULT_URL.
            priority: Provider priority (lower = tried first).
        """
        self._priority = priority
        self._vault_url = vault_url
        self._client: Any = None
        self._available: bool | None = None
        self._sdk_available: bool | None = None

    @property
    def source(self) -> SecretSource:
        """Return AZURE_KEY_VAULT as the source."""
        return SecretSource.AZURE_KEY_VAULT

    @property
    def priority(self) -> int:
        """Return the configured priority."""
        return self._priority

    def _get_vault_url(self) -> str | None:
        """Get vault URL from config or environment.

        Returns:
            Vault URL or None if not configured.
        """
        return self._vault_url or os.environ.get("AZURE_KEY_VAULT_URL")

    def _check_sdk_available(self) -> bool:
        """Check if Azure SDK is installed.

        Returns:
            True if SDK is available.
        """
        if self._sdk_available is not None:
            return self._sdk_available

        try:
            from azure.identity import DefaultAzureCredential  # noqa: F401
            from azure.keyvault.secrets import SecretClient  # noqa: F401

            self._sdk_available = True
        except ImportError:
            logger.debug(
                "azure_keyvault_sdk_not_installed",
                message="Install azure-identity and azure-keyvault-secrets packages",
            )
            self._sdk_available = False

        return self._sdk_available

    def _get_client(self) -> Any:
        """Lazy initialization of Key Vault client.

        Returns:
            SecretClient instance or None if not available.
        """
        if self._client is not None:
            return self._client

        vault_url = self._get_vault_url()
        if not vault_url:
            return None

        if not self._check_sdk_available():
            return None

        try:
            from azure.identity import DefaultAzureCredential
            from azure.keyvault.secrets import SecretClient

            credential = DefaultAzureCredential()
            self._client = SecretClient(vault_url=vault_url, credential=credential)
            logger.info("azure_keyvault_client_initialized", vault_url=vault_url)
            return self._client
        except Exception as e:
            logger.error(
                "azure_keyvault_init_failed",
                vault_url=vault_url,
                error=str(e),
            )
            return None

    def _convert_key_to_vault_name(self, key: str) -> str:
        """Convert env var style key to Azure Key Vault name.

        Azure Key Vault uses hyphens and lowercase, while env vars
        typically use underscores and uppercase.

        Args:
            key: Environment variable style key (e.g., AZURE_OPENAI_API_KEY)

        Returns:
            Key Vault style name (e.g., azure-openai-api-key)
        """
        return key.replace("_", "-").lower()

    async def get_secret(self, key: str) -> SecretValue:
        """Get a secret from Azure Key Vault.

        Converts the key from env var format to vault format:
        AZURE_OPENAI_API_KEY -> azure-openai-api-key

        Args:
            key: Secret key in env var format.

        Returns:
            SecretValue with value if found, NOT_FOUND otherwise.
        """
        client = self._get_client()
        if not client:
            return SecretValue(
                key=key,
                value=None,
                source=SecretSource.NOT_FOUND,
                retrieved_at=datetime.now(),
            )

        try:
            # Convert key format
            secret_name = self._convert_key_to_vault_name(key)
            secret = client.get_secret(secret_name)

            logger.debug(
                "azure_keyvault_secret_retrieved",
                key=key,
                vault_name=secret_name,
            )

            return SecretValue(
                key=key,
                value=secret.value,
                source=SecretSource.AZURE_KEY_VAULT,
                retrieved_at=datetime.now(),
            )
        except Exception as e:
            logger.debug(
                "azure_keyvault_get_failed",
                key=key,
                error=str(e),
            )
            return SecretValue(
                key=key,
                value=None,
                source=SecretSource.NOT_FOUND,
                retrieved_at=datetime.now(),
            )

    async def is_available(self) -> bool:
        """Check if Azure Key Vault is configured and SDK is available.

        Returns:
            True if vault URL is set and SDK is installed.
        """
        if self._available is not None:
            return self._available

        vault_url = self._get_vault_url()
        if not vault_url:
            self._available = False
            return False

        self._available = self._check_sdk_available()
        return self._available

    async def cleanup(self) -> None:
        """Close the Key Vault client connection."""
        if self._client:
            with contextlib.suppress(Exception):
                self._client.close()
            self._client = None
