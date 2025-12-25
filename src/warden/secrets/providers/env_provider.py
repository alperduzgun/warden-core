"""Environment variable secret provider."""

import os
from datetime import datetime

from ..domain.enums import SecretSource
from ..domain.models import SecretValue
from .base import ISecretProvider


class EnvSecretProvider(ISecretProvider):
    """Reads secrets from environment variables.

    This covers:
    - Local environment variables
    - GitHub Actions secrets (exposed as env vars)
    - Any CI/CD system that uses env vars

    Example:
        provider = EnvSecretProvider()
        result = await provider.get_secret("AZURE_OPENAI_API_KEY")
        if result.found:
            print(f"API Key: {result.value}")
    """

    def __init__(self, priority: int = 1):
        """Initialize the provider.

        Args:
            priority: Provider priority (lower = tried first).
        """
        self._priority = priority

    @property
    def source(self) -> SecretSource:
        """Return ENVIRONMENT as the source."""
        return SecretSource.ENVIRONMENT

    @property
    def priority(self) -> int:
        """Return the configured priority."""
        return self._priority

    async def get_secret(self, key: str) -> SecretValue:
        """Get a secret from environment variables.

        Args:
            key: Environment variable name.

        Returns:
            SecretValue with value if found, NOT_FOUND otherwise.
        """
        value = os.environ.get(key)
        return SecretValue(
            key=key,
            value=value,
            source=SecretSource.ENVIRONMENT if value else SecretSource.NOT_FOUND,
            retrieved_at=datetime.now(),
        )

    async def is_available(self) -> bool:
        """Environment provider is always available.

        Returns:
            Always True.
        """
        return True
