"""
Unit tests for IPC protocol (JSON-RPC 2.0)
"""

import json
import pytest

from warden.cli_bridge.protocol import (
    IPCRequest,
    IPCResponse,
    IPCError,
    ErrorCode,
    StreamChunk,
    parse_message,
)


class TestIPCError:
    """Test IPCError class"""

    def test_create_error(self):
        """Test creating an error"""
        error = IPCError(
            code=ErrorCode.INVALID_REQUEST,
            message="Invalid request",
            data={"detail": "Missing method"},
        )

        assert error.code == ErrorCode.INVALID_REQUEST
        assert error.message == "Invalid request"
        assert error.data == {"detail": "Missing method"}

    def test_to_dict(self):
        """Test converting error to dict"""
        error = IPCError(code=ErrorCode.METHOD_NOT_FOUND, message="Method not found")

        result = error.to_dict()

        assert result["code"] == ErrorCode.METHOD_NOT_FOUND
        assert result["message"] == "Method not found"
        assert "data" not in result

    def test_to_dict_with_data(self):
        """Test converting error with data to dict"""
        error = IPCError(
            code=ErrorCode.INTERNAL_ERROR,
            message="Internal error",
            data={"type": "ValueError"},
        )

        result = error.to_dict()

        assert result["code"] == ErrorCode.INTERNAL_ERROR
        assert result["data"]["type"] == "ValueError"

    def test_from_exception(self):
        """Test creating error from exception"""
        exc = ValueError("Something went wrong")
        error = IPCError.from_exception(exc, ErrorCode.VALIDATION_ERROR)

        assert error.code == ErrorCode.VALIDATION_ERROR
        assert "Something went wrong" in error.message
        assert error.data["type"] == "ValueError"


class TestIPCRequest:
    """Test IPCRequest class"""

    def test_create_request(self):
        """Test creating a request"""
        req = IPCRequest(
            method="execute_pipeline",
            params={"file_path": "/path/to/file.py"},
            id=1,
        )

        assert req.jsonrpc == "2.0"
        assert req.method == "execute_pipeline"
        assert req.params["file_path"] == "/path/to/file.py"
        assert req.id == 1

    def test_to_dict(self):
        """Test converting request to dict"""
        req = IPCRequest(method="ping", id="req-1")

        result = req.to_dict()

        assert result["jsonrpc"] == "2.0"
        assert result["method"] == "ping"
        assert result["id"] == "req-1"

    def test_to_json(self):
        """Test converting request to JSON"""
        req = IPCRequest(
            method="get_config",
            params={"verbose": True},
            id=2,
        )

        json_str = req.to_json()
        parsed = json.loads(json_str)

        assert parsed["method"] == "get_config"
        assert parsed["params"]["verbose"] is True

    def test_from_json(self):
        """Test parsing request from JSON"""
        json_str = json.dumps({
            "jsonrpc": "2.0",
            "method": "execute_pipeline",
            "params": {"file_path": "/test.py"},
            "id": 1,
        })

        req = IPCRequest.from_json(json_str)

        assert req.method == "execute_pipeline"
        assert req.params["file_path"] == "/test.py"
        assert req.id == 1

    def test_from_json_invalid(self):
        """Test parsing invalid JSON"""
        with pytest.raises(ValueError, match="Invalid JSON"):
            IPCRequest.from_json("not valid json")

    def test_validate_success(self):
        """Test validating valid request"""
        req = IPCRequest(method="ping", id=1)

        error = req.validate()

        assert error is None

    def test_validate_invalid_version(self):
        """Test validating request with invalid version"""
        req = IPCRequest(jsonrpc="1.0", method="ping", id=1)

        error = req.validate()

        assert error is not None
        assert error.code == ErrorCode.INVALID_REQUEST
        assert "version" in error.message.lower()

    def test_validate_missing_method(self):
        """Test validating request without method"""
        req = IPCRequest(method="", id=1)

        error = req.validate()

        assert error is not None
        assert error.code == ErrorCode.INVALID_REQUEST

    def test_validate_invalid_params(self):
        """Test validating request with invalid params"""
        req = IPCRequest(method="test", params="invalid", id=1)

        error = req.validate()

        assert error is not None
        assert error.code == ErrorCode.INVALID_PARAMS


class TestIPCResponse:
    """Test IPCResponse class"""

    def test_create_success_response(self):
        """Test creating success response"""
        resp = IPCResponse(result={"status": "ok"}, id=1)

        assert resp.jsonrpc == "2.0"
        assert resp.result["status"] == "ok"
        assert resp.error is None
        assert resp.id == 1

    def test_create_error_response(self):
        """Test creating error response"""
        error = IPCError(code=ErrorCode.INTERNAL_ERROR, message="Error")
        resp = IPCResponse(error=error, id=1)

        assert resp.error is not None
        assert resp.error.code == ErrorCode.INTERNAL_ERROR
        assert resp.result is None

    def test_to_dict_success(self):
        """Test converting success response to dict"""
        resp = IPCResponse(result={"data": "test"}, id=1)

        result = resp.to_dict()

        assert result["jsonrpc"] == "2.0"
        assert result["result"]["data"] == "test"
        assert "error" not in result

    def test_to_dict_error(self):
        """Test converting error response to dict"""
        error = IPCError(code=ErrorCode.METHOD_NOT_FOUND, message="Not found")
        resp = IPCResponse(error=error, id=1)

        result = resp.to_dict()

        assert result["jsonrpc"] == "2.0"
        assert result["error"]["code"] == ErrorCode.METHOD_NOT_FOUND
        assert "result" not in result

    def test_to_json(self):
        """Test converting response to JSON"""
        resp = IPCResponse(result={"status": "ok"}, id=1)

        json_str = resp.to_json()
        parsed = json.loads(json_str)

        assert parsed["result"]["status"] == "ok"

    def test_from_json(self):
        """Test parsing response from JSON"""
        json_str = json.dumps({
            "jsonrpc": "2.0",
            "result": {"status": "ok"},
            "id": 1,
        })

        resp = IPCResponse.from_json(json_str)

        assert resp.result["status"] == "ok"
        assert resp.error is None

    def test_from_json_error(self):
        """Test parsing error response from JSON"""
        json_str = json.dumps({
            "jsonrpc": "2.0",
            "error": {
                "code": -32601,
                "message": "Method not found",
            },
            "id": 1,
        })

        resp = IPCResponse.from_json(json_str)

        assert resp.error is not None
        assert resp.error.code == ErrorCode.METHOD_NOT_FOUND
        assert resp.result is None

    def test_success_helper(self):
        """Test success helper method"""
        resp = IPCResponse.success({"data": "test"}, request_id=1)

        assert resp.result["data"] == "test"
        assert resp.error is None
        assert resp.id == 1

    def test_error_helper(self):
        """Test error helper method"""
        error = IPCError(code=ErrorCode.INTERNAL_ERROR, message="Error")
        resp = IPCResponse.error(error, request_id=1)

        assert resp.error is not None
        assert resp.result is None
        assert resp.id == 1


class TestStreamChunk:
    """Test StreamChunk class"""

    def test_create_chunk(self):
        """Test creating stream chunk"""
        chunk = StreamChunk(
            event="message",
            data={"text": "Hello"},
            id="chunk-1",
        )

        assert chunk.event == "message"
        assert chunk.data["text"] == "Hello"
        assert chunk.id == "chunk-1"

    def test_to_sse(self):
        """Test converting chunk to SSE format"""
        chunk = StreamChunk(
            event="data",
            data={"content": "test"},
            id="1",
        )

        sse = chunk.to_sse()

        assert "id: 1" in sse
        assert "event: data" in sse
        assert "data: {" in sse
        assert sse.endswith("\n")

    def test_to_json_lines(self):
        """Test converting chunk to JSON Lines format"""
        chunk = StreamChunk(
            event="update",
            data={"progress": 50},
        )

        json_line = chunk.to_json_lines()
        parsed = json.loads(json_line)

        assert parsed["event"] == "update"
        assert parsed["data"]["progress"] == 50


class TestParseMessage:
    """Test parse_message function"""

    def test_parse_request(self):
        """Test parsing request message"""
        json_str = json.dumps({
            "jsonrpc": "2.0",
            "method": "test",
            "id": 1,
        })

        msg = parse_message(json_str)

        assert isinstance(msg, IPCRequest)
        assert msg.method == "test"

    def test_parse_response(self):
        """Test parsing response message"""
        json_str = json.dumps({
            "jsonrpc": "2.0",
            "result": {"status": "ok"},
            "id": 1,
        })

        msg = parse_message(json_str)

        assert isinstance(msg, IPCResponse)
        assert msg.result["status"] == "ok"

    def test_parse_invalid_json(self):
        """Test parsing invalid JSON"""
        with pytest.raises(ValueError, match="Invalid JSON"):
            parse_message("not json")

    def test_parse_unknown_message(self):
        """Test parsing unknown message type"""
        json_str = json.dumps({
            "jsonrpc": "2.0",
            "unknown": "field",
        })

        with pytest.raises(ValueError, match="Invalid message"):
            parse_message(json_str)


class TestErrorCodes:
    """Test ErrorCode enum"""

    def test_standard_error_codes(self):
        """Test standard JSON-RPC error codes"""
        assert ErrorCode.PARSE_ERROR == -32700
        assert ErrorCode.INVALID_REQUEST == -32600
        assert ErrorCode.METHOD_NOT_FOUND == -32601
        assert ErrorCode.INVALID_PARAMS == -32602
        assert ErrorCode.INTERNAL_ERROR == -32603

    def test_warden_error_codes(self):
        """Test Warden-specific error codes"""
        assert ErrorCode.PIPELINE_EXECUTION_ERROR == -32000
        assert ErrorCode.FILE_NOT_FOUND == -32001
        assert ErrorCode.VALIDATION_ERROR == -32002
        assert ErrorCode.CONFIGURATION_ERROR == -32003
        assert ErrorCode.LLM_ERROR == -32004
        assert ErrorCode.TIMEOUT_ERROR == -32005
