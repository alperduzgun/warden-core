"""
MCP Domain Models

Core entities and aggregates for the MCP server.
Pure domain logic without external dependencies.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from warden.mcp.domain.enums import ServerStatus, ResourceType, ToolCategory


@dataclass
class MCPSession:
    """
    MCP session entity - tracks connection lifecycle.

    Aggregate root for session state management.
    """
    session_id: str
    status: ServerStatus = ServerStatus.INITIALIZING
    initialized: bool = False
    started_at: Optional[datetime] = None
    client_info: Optional[Dict[str, Any]] = None

    def mark_initialized(self, client_info: Optional[Dict[str, Any]] = None) -> None:
        """Mark session as initialized after client handshake."""
        self.initialized = True
        self.client_info = client_info
        self.status = ServerStatus.READY

    def start(self) -> None:
        """Start session."""
        self.started_at = datetime.utcnow()
        self.status = ServerStatus.RUNNING

    def stop(self) -> None:
        """Stop session."""
        self.status = ServerStatus.STOPPED

    def set_error(self) -> None:
        """Mark session as errored."""
        self.status = ServerStatus.ERROR

    def is_ready(self) -> bool:
        """Check if session is ready for requests."""
        return self.status in (ServerStatus.READY, ServerStatus.RUNNING)


@dataclass
class MCPToolDefinition:
    """
    MCP tool definition entity.

    Defines a tool that can be invoked by the MCP client.
    """
    name: str
    description: str
    category: ToolCategory
    input_schema: Dict[str, Any] = field(default_factory=lambda: {
        "type": "object",
        "properties": {},
        "required": [],
    })
    requires_bridge: bool = False

    def to_mcp_format(self) -> Dict[str, Any]:
        """Convert to MCP protocol format."""
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


@dataclass
class MCPResourceDefinition:
    """
    MCP resource definition entity.

    Defines a resource that can be read by the MCP client.
    """
    uri: str
    name: str
    description: str
    resource_type: ResourceType
    mime_type: str
    file_path: str  # Relative to project root

    def to_mcp_format(self) -> Dict[str, Any]:
        """Convert to MCP protocol format."""
        result = {
            "uri": self.uri,
            "name": self.name,
            "mimeType": self.mime_type,
        }
        if self.description:
            result["description"] = self.description
        return result


@dataclass
class MCPToolResult:
    """
    MCP tool execution result value object.

    Encapsulates tool output in MCP-compatible format.
    """
    content: List[Dict[str, Any]]
    is_error: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to MCP protocol format."""
        return {
            "content": self.content,
            "isError": self.is_error,
        }

    @classmethod
    def success(cls, text: str) -> "MCPToolResult":
        """Create a successful text result."""
        return cls(content=[{"type": "text", "text": text}])

    @classmethod
    def error(cls, message: str) -> "MCPToolResult":
        """Create an error result."""
        return cls(content=[{"type": "text", "text": message}], is_error=True)

    @classmethod
    def json_result(cls, data: Any) -> "MCPToolResult":
        """Create a JSON result."""
        import json
        return cls(content=[{"type": "text", "text": json.dumps(data, indent=2, default=str)}])
