"""
JSON-RPC 2.0 Protocol Implementation for IPC

Provides type-safe protocol layer for communication between Python backend and Ink CLI.
"""

from enum import IntEnum
from typing import Any, Optional, Dict, Union
from dataclasses import dataclass, field, asdict
import json


class ErrorCode(IntEnum):
    """JSON-RPC 2.0 Error Codes"""

    # Standard JSON-RPC errors
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603

    # Warden-specific errors (start at -32000)
    PIPELINE_EXECUTION_ERROR = -32000
    FILE_NOT_FOUND = -32001
    VALIDATION_ERROR = -32002
    CONFIGURATION_ERROR = -32003
    LLM_ERROR = -32004
    TIMEOUT_ERROR = -32005


class IPCError(Exception):
    """JSON-RPC 2.0 Error object (also an Exception for raising)"""

    def __init__(self, code: int, message: str, data: Optional[Dict[str, Any]] = None):
        """Initialize error with code, message, and optional data"""
        self.code = code
        self.message = message
        self.data = data
        super().__init__(message)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        result = {"code": self.code, "message": self.message}
        if self.data is not None:
            result["data"] = self.data
        return result

    @staticmethod
    def from_exception(exc: Exception, code: ErrorCode = ErrorCode.INTERNAL_ERROR) -> "IPCError":
        """Create error from exception"""
        return IPCError(
            code=code,
            message=str(exc),
            data={"type": type(exc).__name__, "traceback": None},  # Add traceback in debug mode
        )


@dataclass
class IPCRequest:
    """JSON-RPC 2.0 Request object"""

    jsonrpc: str = "2.0"
    method: str = ""
    params: Optional[Union[Dict[str, Any], list]] = None
    id: Optional[Union[str, int]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        result = {"jsonrpc": self.jsonrpc, "method": self.method}
        if self.params is not None:
            result["params"] = self.params
        if self.id is not None:
            result["id"] = self.id
        return result

    def to_json(self) -> str:
        """Convert to JSON string"""
        return json.dumps(self.to_dict())

    @staticmethod
    def from_json(data: str) -> "IPCRequest":
        """Parse from JSON string"""
        try:
            obj = json.loads(data)
            return IPCRequest(
                jsonrpc=obj.get("jsonrpc", "2.0"),
                method=obj.get("method", ""),
                params=obj.get("params"),
                id=obj.get("id"),
            )
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON: {e}")

    def validate(self) -> Optional[IPCError]:
        """
        Validate request according to JSON-RPC 2.0 spec

        Returns:
            IPCError if invalid, None if valid
        """
        if self.jsonrpc != "2.0":
            return IPCError(
                code=ErrorCode.INVALID_REQUEST, message="Invalid JSON-RPC version (must be 2.0)"
            )

        if not self.method or not isinstance(self.method, str):
            return IPCError(
                code=ErrorCode.INVALID_REQUEST, message="Method must be a non-empty string"
            )

        if self.params is not None and not isinstance(self.params, (dict, list)):
            return IPCError(
                code=ErrorCode.INVALID_PARAMS,
                message="Params must be an object or array",
            )

        return None


@dataclass
class IPCResponse:
    """JSON-RPC 2.0 Response object"""

    jsonrpc: str = "2.0"
    result: Optional[Any] = None
    error: Optional[IPCError] = None
    id: Optional[Union[str, int]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        obj = {"jsonrpc": self.jsonrpc}

        if self.error is not None:
            obj["error"] = self.error.to_dict()
        else:
            obj["result"] = self.result

        if self.id is not None:
            obj["id"] = self.id

        return obj

    def to_json(self) -> str:
        """Convert to JSON string"""
        return json.dumps(self.to_dict())

    @staticmethod
    def from_json(data: str) -> "IPCResponse":
        """Parse from JSON string"""
        try:
            obj = json.loads(data)
            error_data = obj.get("error")
            error = None
            if error_data:
                error = IPCError(
                    code=error_data["code"],
                    message=error_data["message"],
                    data=error_data.get("data"),
                )

            return IPCResponse(
                jsonrpc=obj.get("jsonrpc", "2.0"),
                result=obj.get("result"),
                error=error,
                id=obj.get("id"),
            )
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON: {e}")

    @staticmethod
    def create_success(result: Any, request_id: Optional[Union[str, int]] = None) -> "IPCResponse":
        """Create success response"""
        return IPCResponse(jsonrpc="2.0", result=result, id=request_id)

    @staticmethod
    def create_error(
        error_obj: IPCError, request_id: Optional[Union[str, int]] = None
    ) -> "IPCResponse":
        """Create error response"""
        return IPCResponse(jsonrpc="2.0", error=error_obj, id=request_id)


@dataclass
class StreamChunk:
    """Streaming data chunk for SSE-style responses"""

    event: str
    data: Any
    id: Optional[str] = None

    def to_sse(self) -> str:
        """Convert to Server-Sent Events format"""
        lines = []
        if self.id:
            lines.append(f"id: {self.id}")
        lines.append(f"event: {self.event}")
        lines.append(f"data: {json.dumps(self.data)}")
        lines.append("")  # Empty line to separate events
        return "\n".join(lines)

    def to_json_lines(self) -> str:
        """Convert to JSON Lines format (NDJSON)"""
        return json.dumps({"event": self.event, "data": self.data, "id": self.id})


def parse_message(data: str) -> Union[IPCRequest, IPCResponse]:
    """
    Parse JSON-RPC message (auto-detect request or response)

    Args:
        data: JSON string

    Returns:
        IPCRequest or IPCResponse

    Raises:
        ValueError: If invalid JSON or unrecognized message type
    """
    try:
        obj = json.loads(data)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}")

    # Detect message type
    if "method" in obj:
        return IPCRequest.from_json(data)
    elif "result" in obj or "error" in obj:
        return IPCResponse.from_json(data)
    else:
        raise ValueError("Invalid message: must contain 'method' (request) or 'result'/'error' (response)")
