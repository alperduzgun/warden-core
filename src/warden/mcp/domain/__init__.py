"""
MCP Domain Layer

Pure business logic and domain entities for the Model Context Protocol.
No external dependencies - only imports from this package.
"""

from warden.mcp.domain.enums import (
    MCPErrorCode,
    MessageType,
    ResourceType,
    ServerStatus,
    ToolCategory,
)
from warden.mcp.domain.errors import (
    MCPDomainError,
    MCPProtocolError,
    MCPResourceNotFoundError,
    MCPToolExecutionError,
    MCPToolNotFoundError,
    MCPTransportError,
)
from warden.mcp.domain.models import (
    MCPResourceDefinition,
    MCPSession,
    MCPToolDefinition,
)
from warden.mcp.domain.value_objects import (
    ProtocolVersion,
    ResourceUri,
)

__all__ = [
    # Enums
    "MCPErrorCode",
    "ServerStatus",
    "MessageType",
    "ResourceType",
    "ToolCategory",
    # Errors
    "MCPDomainError",
    "MCPTransportError",
    "MCPToolNotFoundError",
    "MCPToolExecutionError",
    "MCPResourceNotFoundError",
    "MCPProtocolError",
    # Models
    "MCPSession",
    "MCPToolDefinition",
    "MCPResourceDefinition",
    # Value Objects
    "ProtocolVersion",
    "ResourceUri",
]
