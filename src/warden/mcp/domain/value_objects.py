"""
MCP Domain Value Objects

Immutable value objects for protocol values.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ProtocolVersion:
    """
    Immutable MCP protocol version.

    Represents the MCP specification version supported by the server.
    """
    version: str = "2024-11-05"

    def __str__(self) -> str:
        return self.version

    def is_compatible(self, client_version: str) -> bool:
        """Check if client version is compatible."""
        # For now, exact match required
        return self.version == client_version


@dataclass(frozen=True)
class ResourceUri:
    """
    Immutable resource URI with validation.

    Warden resources use the "warden://" scheme.
    """
    scheme: str  # "warden"
    path: str    # e.g., "reports/sarif"

    @classmethod
    def parse(cls, uri: str) -> "ResourceUri":
        """
        Parse URI string into ResourceUri.

        Args:
            uri: Full URI string (e.g., "warden://reports/sarif")

        Returns:
            Parsed ResourceUri

        Raises:
            ValueError: If URI format is invalid
        """
        if "://" not in uri:
            raise ValueError(f"Invalid URI format (missing scheme): {uri}")

        scheme, path = uri.split("://", 1)

        if not scheme:
            raise ValueError(f"Empty scheme in URI: {uri}")
        if not path:
            raise ValueError(f"Empty path in URI: {uri}")

        return cls(scheme=scheme, path=path)

    def __str__(self) -> str:
        return f"{self.scheme}://{self.path}"

    def is_warden_resource(self) -> bool:
        """Check if this is a Warden resource."""
        return self.scheme == "warden"


@dataclass(frozen=True)
class ServerInfo:
    """
    Immutable server information.

    Announced during MCP initialization.
    """
    name: str = "warden-mcp"
    version: str = "1.0.0"

    def to_dict(self) -> dict:
        """Convert to MCP format."""
        return {"name": self.name, "version": self.version}


@dataclass(frozen=True)
class ServerCapabilities:
    """
    Immutable server capabilities.

    Announced during MCP initialization.
    """
    resources: bool = True
    tools: bool = True
    prompts: bool = False
    logging: bool = False

    def to_dict(self) -> dict:
        """Convert to MCP format."""
        caps = {}
        if self.resources:
            caps["resources"] = {}
        if self.tools:
            caps["tools"] = {}
        if self.prompts:
            caps["prompts"] = {}
        if self.logging:
            caps["logging"] = {}
        return caps
