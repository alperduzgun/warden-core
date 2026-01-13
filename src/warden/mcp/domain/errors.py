"""
MCP Domain Errors

DDD-compliant exception hierarchy for MCP operations.
All domain errors inherit from MCPDomainError.
"""

from typing import Any, Dict, Optional

from warden.mcp.domain.enums import MCPErrorCode


class MCPDomainError(Exception):
    """
    Base exception for all MCP domain errors.

    Provides structured error information compatible with JSON-RPC 2.0.
    """

    def __init__(
        self,
        message: str,
        code: MCPErrorCode = MCPErrorCode.INTERNAL_ERROR,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-RPC error format."""
        result = {
            "code": int(self.code),
            "message": self.message,
        }
        if self.details:
            result["data"] = self.details
        return result


class MCPTransportError(MCPDomainError):
    """Raised when transport layer operations fail."""

    def __init__(self, message: str, cause: Optional[str] = None) -> None:
        super().__init__(
            message=message,
            code=MCPErrorCode.TRANSPORT_ERROR,
            details={"cause": cause} if cause else None,
        )


class MCPToolNotFoundError(MCPDomainError):
    """Raised when requested tool does not exist."""

    def __init__(self, tool_name: str) -> None:
        super().__init__(
            message=f"Tool not found: {tool_name}",
            code=MCPErrorCode.TOOL_NOT_FOUND,
            details={"tool_name": tool_name},
        )
        self.tool_name = tool_name


class MCPToolExecutionError(MCPDomainError):
    """Raised when tool execution fails."""

    def __init__(self, tool_name: str, cause: str) -> None:
        super().__init__(
            message=f"Tool execution failed: {tool_name} - {cause}",
            code=MCPErrorCode.TOOL_EXECUTION_ERROR,
            details={"tool_name": tool_name, "cause": cause},
        )
        self.tool_name = tool_name
        self.cause = cause


class MCPResourceNotFoundError(MCPDomainError):
    """Raised when requested resource does not exist."""

    def __init__(self, uri: str) -> None:
        super().__init__(
            message=f"Resource not found: {uri}",
            code=MCPErrorCode.RESOURCE_NOT_FOUND,
            details={"uri": uri},
        )
        self.uri = uri


class MCPProtocolError(MCPDomainError):
    """Raised for MCP protocol violations."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            message=message,
            code=MCPErrorCode.INVALID_REQUEST,
            details=details,
        )


class MCPSessionError(MCPDomainError):
    """Raised for session-related errors."""

    def __init__(self, message: str) -> None:
        super().__init__(
            message=message,
            code=MCPErrorCode.SESSION_NOT_INITIALIZED,
        )
