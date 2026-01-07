"""
Resource Provider Service

Application service for resource access.
"""

from pathlib import Path
from typing import Any, Dict, List

from warden.mcp.domain.models import MCPResourceDefinition
from warden.mcp.domain.errors import MCPResourceNotFoundError
from warden.mcp.infrastructure.file_resource_repo import FileResourceRepository


class ResourceProviderService:
    """
    Application service for resource provision.

    Wraps repository access with use case logic.
    """

    def __init__(self, project_root: Path) -> None:
        """
        Initialize resource provider.

        Args:
            project_root: Project root directory
        """
        self.project_root = project_root
        self._repository = FileResourceRepository(project_root)

    async def list_resources(self) -> List[MCPResourceDefinition]:
        """
        List all available resources.

        Returns:
            List of available resource definitions
        """
        return await self._repository.list_available()

    async def read_resource(self, uri: str) -> Dict[str, Any]:
        """
        Read resource content.

        Args:
            uri: Resource URI

        Returns:
            Resource content in MCP format

        Raises:
            MCPResourceNotFoundError: If resource not found
        """
        resource = self._repository.get_definition(uri)
        if not resource:
            raise MCPResourceNotFoundError(uri)

        content = await self._repository.get_content(uri)
        if content is None:
            raise MCPResourceNotFoundError(uri)

        return {
            "uri": uri,
            "mimeType": resource.mime_type,
            "text": content,
        }

    async def resource_exists(self, uri: str) -> bool:
        """
        Check if resource exists.

        Args:
            uri: Resource URI

        Returns:
            True if resource exists
        """
        return await self._repository.exists(uri)

    def list_all_reports(self) -> List[Dict[str, Any]]:
        """
        List all report files.

        Returns:
            List of report metadata
        """
        return self._repository.list_all_reports()
