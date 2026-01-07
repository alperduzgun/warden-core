"""
MCP Protocol Handler

Implements Model Context Protocol (MCP) message handling over JSON-RPC 2.0.
Based on the MCP specification for AI assistant tool/resource integration.
"""

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Callable, Awaitable
from enum import IntEnum


class MCPErrorCode(IntEnum):
    """MCP-specific error codes (JSON-RPC 2.0 compatible)."""
    # Standard JSON-RPC errors
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603

    # MCP-specific errors
    RESOURCE_NOT_FOUND = -32001
    TOOL_NOT_FOUND = -32002
    TOOL_EXECUTION_ERROR = -32003


@dataclass
class MCPError:
    """MCP error response."""
    code: int
    message: str
    data: Optional[Any] = None

    def to_dict(self) -> Dict[str, Any]:
        result = {"code": self.code, "message": self.message}
        if self.data is not None:
            result["data"] = self.data
        return result


@dataclass
class MCPRequest:
    """MCP JSON-RPC request."""
    jsonrpc: str
    method: str
    id: Optional[int | str] = None
    params: Optional[Dict[str, Any]] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MCPRequest":
        return cls(
            jsonrpc=data.get("jsonrpc", "2.0"),
            method=data["method"],
            id=data.get("id"),
            params=data.get("params"),
        )

    def is_notification(self) -> bool:
        """Notifications have no id and expect no response."""
        return self.id is None


@dataclass
class MCPResponse:
    """MCP JSON-RPC response."""
    jsonrpc: str = "2.0"
    id: Optional[int | str] = None
    result: Optional[Any] = None
    error: Optional[MCPError] = None

    def to_dict(self) -> Dict[str, Any]:
        response = {"jsonrpc": self.jsonrpc}
        if self.id is not None:
            response["id"] = self.id
        if self.error is not None:
            response["error"] = self.error.to_dict()
        else:
            response["result"] = self.result
        return response

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


@dataclass
class MCPServerCapabilities:
    """MCP server capabilities announcement."""
    resources: bool = True
    tools: bool = True
    prompts: bool = False
    logging: bool = False

    def to_dict(self) -> Dict[str, Any]:
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


@dataclass
class MCPServerInfo:
    """MCP server information."""
    name: str = "warden-mcp"
    version: str = "1.0.0"

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "version": self.version}


@dataclass
class MCPResource:
    """MCP resource definition."""
    uri: str
    name: str
    description: Optional[str] = None
    mime_type: str = "application/json"

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "uri": self.uri,
            "name": self.name,
            "mimeType": self.mime_type,
        }
        if self.description:
            result["description"] = self.description
        return result


@dataclass
class MCPResourceContent:
    """MCP resource content."""
    uri: str
    mime_type: str
    text: Optional[str] = None
    blob: Optional[str] = None  # base64 encoded

    def to_dict(self) -> Dict[str, Any]:
        result = {"uri": self.uri, "mimeType": self.mime_type}
        if self.text is not None:
            result["text"] = self.text
        if self.blob is not None:
            result["blob"] = self.blob
        return result


@dataclass
class MCPTool:
    """MCP tool definition."""
    name: str
    description: str
    input_schema: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


@dataclass
class MCPToolResult:
    """MCP tool execution result."""
    content: List[Dict[str, Any]]
    is_error: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "content": self.content,
            "isError": self.is_error,
        }


# Type alias for method handlers
MethodHandler = Callable[[Optional[Dict[str, Any]]], Awaitable[Any]]


class MCPProtocol:
    """
    MCP Protocol handler.

    Routes JSON-RPC messages to appropriate handlers and
    formats responses according to MCP specification.
    """

    def __init__(self):
        self._handlers: Dict[str, MethodHandler] = {}
        self.server_info = MCPServerInfo()
        self.capabilities = MCPServerCapabilities()

    def register_handler(self, method: str, handler: MethodHandler) -> None:
        """Register a handler for an MCP method."""
        self._handlers[method] = handler

    async def handle_message(self, raw_message: str) -> Optional[str]:
        """
        Handle incoming MCP message.

        Args:
            raw_message: JSON-RPC message string

        Returns:
            JSON response string, or None for notifications
        """
        try:
            data = json.loads(raw_message)
        except json.JSONDecodeError as e:
            error = MCPError(
                code=MCPErrorCode.PARSE_ERROR,
                message=f"Parse error: {e}",
            )
            return MCPResponse(error=error).to_json()

        try:
            request = MCPRequest.from_dict(data)
        except (KeyError, TypeError) as e:
            error = MCPError(
                code=MCPErrorCode.INVALID_REQUEST,
                message=f"Invalid request: {e}",
            )
            return MCPResponse(error=error).to_json()

        # Handle the request
        response = await self._dispatch(request)

        # Notifications don't get responses
        if request.is_notification():
            return None

        return response.to_json()

    async def _dispatch(self, request: MCPRequest) -> MCPResponse:
        """Dispatch request to appropriate handler."""
        handler = self._handlers.get(request.method)

        if handler is None:
            return MCPResponse(
                id=request.id,
                error=MCPError(
                    code=MCPErrorCode.METHOD_NOT_FOUND,
                    message=f"Method not found: {request.method}",
                ),
            )

        try:
            result = await handler(request.params)
            return MCPResponse(id=request.id, result=result)
        except Exception as e:
            return MCPResponse(
                id=request.id,
                error=MCPError(
                    code=MCPErrorCode.INTERNAL_ERROR,
                    message=str(e),
                ),
            )

    def create_error_response(
        self,
        request_id: Optional[int | str],
        code: MCPErrorCode,
        message: str,
        data: Optional[Any] = None,
    ) -> MCPResponse:
        """Create an error response."""
        return MCPResponse(
            id=request_id,
            error=MCPError(code=code, message=message, data=data),
        )
