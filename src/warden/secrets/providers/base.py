"""Base interface for secret providers."""

from abc import ABC, abstractmethod

from ..domain.enums import SecretSource
from ..domain.models import SecretValue


class ISecretProvider(ABC):
    """Interface for secret providers.

    All providers (Env, DotEnv, Azure Key Vault) must implement this.
    Pattern follows warden.llm.providers.base.ILlmClient.

    Example:
        class MyProvider(ISecretProvider):
            @property
            def source(self) -> SecretSource:
                return SecretSource.ENVIRONMENT

            @property
            def priority(self) -> int:
                return 1

            async def get_secret(self, key: str) -> SecretValue:
                value = os.environ.get(key)
                return SecretValue(key=key, value=value, source=self.source)

            async def is_available(self) -> bool:
                return True
    """

    @property
    @abstractmethod
    def source(self) -> SecretSource:
        """The source type this provider reads from.

        Returns:
            SecretSource enum value identifying this provider.
        """
        pass

    @property
    @abstractmethod
    def priority(self) -> int:
        """Provider priority (lower = tried first).

        Returns:
            Integer priority. 0 is highest priority.
        """
        pass

    @abstractmethod
    async def get_secret(self, key: str) -> SecretValue:
        """Retrieve a secret by key.

        Args:
            key: Secret key/name (e.g., "AZURE_OPENAI_API_KEY").

        Returns:
            SecretValue with value if found, or NOT_FOUND source if not.
        """
        pass

    @abstractmethod
    async def is_available(self) -> bool:
        """Check if this provider is configured and available.

        Returns:
            True if provider can attempt to retrieve secrets.
        """
        pass

    async def cleanup(self) -> None:  # noqa: B027
        """Optional cleanup (close connections, etc.).

        Override this method if your provider needs cleanup.
        This is intentionally not abstract - it's an optional hook.
        """
        pass
