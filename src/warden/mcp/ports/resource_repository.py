"""
Resource Repository Port

Abstract interface for resource access.
Following project's IRepository pattern from shared/domain/repository.py
"""

from abc import ABC, abstractmethod
from typing import List, Optional

from warden.mcp.domain.models import MCPResourceDefinition


class IResourceRepository(ABC):
    """
    Abstract resource repository interface.

    Defines the contract for resource discovery and retrieval.
    Implementations handle actual storage (filesystem, remote, etc.).
    """

    @abstractmethod
    async def list_available(self) -> List[MCPResourceDefinition]:
        """
        List all available (existing) resources.

        Only returns resources that actually exist and are readable.

        Returns:
            List of available resource definitions
        """
        ...

    @abstractmethod
    async def get_content(self, uri: str) -> Optional[str]:
        """
        Get resource content by URI.

        Args:
            uri: Resource URI (e.g., "warden://reports/sarif")

        Returns:
            Resource content as string, or None if not found

        Raises:
            MCPResourceNotFoundError: If resource doesn't exist
        """
        ...

    @abstractmethod
    async def exists(self, uri: str) -> bool:
        """
        Check if resource exists.

        Args:
            uri: Resource URI to check

        Returns:
            True if resource exists and is accessible
        """
        ...

    @abstractmethod
    def get_definition(self, uri: str) -> Optional[MCPResourceDefinition]:
        """
        Get resource definition by URI (without checking existence).

        Args:
            uri: Resource URI

        Returns:
            Resource definition if URI is known, None otherwise
        """
        ...
