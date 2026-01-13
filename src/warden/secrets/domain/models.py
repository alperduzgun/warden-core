"""Secret domain models."""

from dataclasses import dataclass, field
from datetime import datetime

from .enums import SecretSource


@dataclass
class SecretValue:
    """Represents a retrieved secret with metadata.

    Attributes:
        key: The secret key/name that was requested.
        value: The secret value, or None if not found.
        source: Where the secret was retrieved from.
        retrieved_at: When the secret was retrieved.
        cached: Whether this value came from cache.
    """

    key: str
    value: str | None
    source: SecretSource
    retrieved_at: datetime = field(default_factory=datetime.now)
    cached: bool = False

    @property
    def found(self) -> bool:
        """Check if the secret was found.

        Returns:
            True if secret has a value and source is not NOT_FOUND.
        """
        return self.value is not None and self.source != SecretSource.NOT_FOUND

    def __str__(self) -> str:
        """Safe string representation without exposing value."""
        return f"SecretValue(key={self.key}, source={self.source.value}, found={self.found})"

    def __repr__(self) -> str:
        """Safe repr without exposing value."""
        return self.__str__()


@dataclass
class SecretProviderConfig:
    """Configuration for a secret provider.

    Attributes:
        enabled: Whether this provider is enabled.
        priority: Provider priority (lower = tried first).
        cache_ttl_seconds: How long to cache secrets.
    """

    enabled: bool = True
    priority: int = 0  # Lower = higher priority
    cache_ttl_seconds: int = 300  # 5 minutes default
