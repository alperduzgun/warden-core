"""
Unit tests for IPC Server
"""

import pytest
import asyncio
import json
from unittest.mock import Mock, AsyncMock, patch, MagicMock

from warden.cli_bridge.server import IPCServer
from warden.cli_bridge.bridge import WardenBridge
from warden.cli_bridge.protocol import IPCRequest, IPCResponse, IPCError, ErrorCode


@pytest.fixture
def mock_bridge():
    """Create a mock Warden Bridge"""
    bridge = Mock(spec=WardenBridge)
    bridge.ping = AsyncMock(return_value={"status": "ok", "message": "pong"})
    bridge.execute_pipeline = AsyncMock(
        return_value={"pipeline_id": "test", "status": "completed"}
    )
    bridge.get_config = AsyncMock(
        return_value={"version": "0.1.0", "providers": []}
    )
    bridge.get_available_frames = AsyncMock(return_value=[])
    return bridge


@pytest.fixture
def server(mock_bridge):
    """Create an IPC server instance"""
    return IPCServer(bridge=mock_bridge, transport="stdio")


class TestIPCServer:
    """Test IPCServer class"""

    def test_server_initialization(self, server):
        """Test server initialization"""
        assert server.transport == "stdio"
        assert server.running is False
        assert "ping" in server.methods
        assert "execute_pipeline" in server.methods
        assert "get_config" in server.methods

    def test_server_initialization_socket(self):
        """Test server initialization with socket transport"""
        server = IPCServer(transport="socket", socket_path="/tmp/test.sock")
        assert server.transport == "socket"
        assert server.socket_path == "/tmp/test.sock"

    def test_server_initialization_invalid_transport(self):
        """Test server initialization with invalid transport"""
        server = IPCServer(transport="invalid")
        with pytest.raises(ValueError, match="Invalid transport"):
            asyncio.run(server.start())

    @pytest.mark.asyncio
    async def test_handle_request_ping(self, server):
        """Test handling ping request"""
        request_json = json.dumps({
            "jsonrpc": "2.0",
            "method": "ping",
            "id": 1,
        })

        response = await server._handle_request(request_json)

        assert response.id == 1
        assert response.error is None
        assert response.result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_handle_request_with_params_dict(self, server):
        """Test handling request with dict params"""
        request_json = json.dumps({
            "jsonrpc": "2.0",
            "method": "execute_pipeline",
            "params": {"file_path": "/test.py"},
            "id": 2,
        })

        response = await server._handle_request(request_json)

        assert response.id == 2
        assert response.error is None
        assert response.result["pipeline_id"] == "test"

    @pytest.mark.asyncio
    async def test_handle_request_with_params_list(self, server, mock_bridge):
        """Test handling request with list params"""
        # Need to modify mock to accept positional args
        mock_bridge.ping = AsyncMock(return_value={"status": "ok"})

        request_json = json.dumps({
            "jsonrpc": "2.0",
            "method": "ping",
            "params": [],
            "id": 3,
        })

        response = await server._handle_request(request_json)

        assert response.id == 3
        assert response.error is None

    @pytest.mark.asyncio
    async def test_handle_request_no_params(self, server):
        """Test handling request without params"""
        request_json = json.dumps({
            "jsonrpc": "2.0",
            "method": "ping",
            "id": 4,
        })

        response = await server._handle_request(request_json)

        assert response.id == 4
        assert response.error is None

    @pytest.mark.asyncio
    async def test_handle_request_invalid_json(self, server):
        """Test handling request with invalid JSON"""
        response = await server._handle_request("not valid json")

        assert response.error is not None
        assert response.error.code == ErrorCode.PARSE_ERROR or response.error.code == ErrorCode.INTERNAL_ERROR

    @pytest.mark.asyncio
    async def test_handle_request_invalid_version(self, server):
        """Test handling request with invalid JSON-RPC version"""
        request_json = json.dumps({
            "jsonrpc": "1.0",
            "method": "ping",
            "id": 5,
        })

        response = await server._handle_request(request_json)

        assert response.id == 5
        assert response.error is not None
        assert response.error.code == ErrorCode.INVALID_REQUEST

    @pytest.mark.asyncio
    async def test_handle_request_method_not_found(self, server):
        """Test handling request with non-existent method"""
        request_json = json.dumps({
            "jsonrpc": "2.0",
            "method": "nonexistent_method",
            "id": 6,
        })

        response = await server._handle_request(request_json)

        assert response.id == 6
        assert response.error is not None
        assert response.error.code == ErrorCode.METHOD_NOT_FOUND
        assert "available_methods" in response.error.data

    @pytest.mark.asyncio
    async def test_handle_request_invalid_params_type(self, server):
        """Test handling request with invalid params type"""
        request_json = json.dumps({
            "jsonrpc": "2.0",
            "method": "ping",
            "params": "invalid",
            "id": 7,
        })

        response = await server._handle_request(request_json)

        assert response.id == 7
        assert response.error is not None
        assert response.error.code == ErrorCode.INVALID_PARAMS

    @pytest.mark.asyncio
    async def test_handle_request_method_raises_ipc_error(self, server, mock_bridge):
        """Test handling request when method raises IPCError"""
        mock_bridge.execute_pipeline = AsyncMock(
            side_effect=IPCError(
                code=ErrorCode.FILE_NOT_FOUND,
                message="File not found",
            )
        )

        request_json = json.dumps({
            "jsonrpc": "2.0",
            "method": "execute_pipeline",
            "params": {"file_path": "/nonexistent.py"},
            "id": 8,
        })

        response = await server._handle_request(request_json)

        assert response.id == 8
        assert response.error is not None
        assert response.error.code == ErrorCode.FILE_NOT_FOUND

    @pytest.mark.asyncio
    async def test_handle_request_method_raises_exception(self, server, mock_bridge):
        """Test handling request when method raises generic exception"""
        mock_bridge.ping = AsyncMock(side_effect=ValueError("Something went wrong"))

        request_json = json.dumps({
            "jsonrpc": "2.0",
            "method": "ping",
            "id": 9,
        })

        response = await server._handle_request(request_json)

        assert response.id == 9
        assert response.error is not None
        assert response.error.code == ErrorCode.INTERNAL_ERROR
        assert "Something went wrong" in response.error.message

    @pytest.mark.asyncio
    async def test_handle_streaming_method(self, server, mock_bridge):
        """Test handling streaming method"""
        async def mock_stream():
            for chunk in ["chunk1", "chunk2", "chunk3"]:
                yield chunk

        mock_bridge.analyze_with_llm = mock_stream

        result = await server._handle_streaming_method(prompt="test")

        assert "chunks" in result
        assert len(result["chunks"]) == 3
        assert result["chunks"][0] == "chunk1"
        assert result["streaming"] is False

    def test_methods_routing(self, server):
        """Test that all required methods are registered"""
        assert "ping" in server.methods
        assert "execute_pipeline" in server.methods
        assert "get_config" in server.methods
        assert "analyze_with_llm" in server.methods
        assert "get_available_frames" in server.methods

    @pytest.mark.asyncio
    async def test_stop_server(self, server):
        """Test stopping server"""
        server.running = True
        server.server = Mock()
        server.server.close = Mock()
        server.server.wait_closed = AsyncMock()

        await server.stop()

        assert server.running is False
        server.server.close.assert_called_once()
        server.server.wait_closed.assert_called_once()


class TestIPCServerIntegration:
    """Integration tests for IPC Server"""

    @pytest.mark.asyncio
    async def test_full_request_response_cycle(self):
        """Test complete request-response cycle"""
        mock_bridge = Mock(spec=WardenBridge)
        mock_bridge.ping = AsyncMock(
            return_value={
                "status": "ok",
                "message": "pong",
                "timestamp": "2024-01-01T00:00:00",
            }
        )

        server = IPCServer(bridge=mock_bridge, transport="stdio")

        # Create request
        request = IPCRequest(method="ping", id=1)
        request_json = request.to_json()

        # Handle request
        response = await server._handle_request(request_json)

        # Verify response
        assert response.id == 1
        assert response.error is None
        assert response.result["status"] == "ok"
        assert response.result["message"] == "pong"

    @pytest.mark.asyncio
    async def test_error_handling_cycle(self):
        """Test complete error handling cycle"""
        mock_bridge = Mock(spec=WardenBridge)
        mock_bridge.execute_pipeline = AsyncMock(
            side_effect=IPCError(
                code=ErrorCode.FILE_NOT_FOUND,
                message="File not found: /test.py",
                data={"file_path": "/test.py"},
            )
        )

        server = IPCServer(bridge=mock_bridge, transport="stdio")

        # Create request
        request = IPCRequest(
            method="execute_pipeline",
            params={"file_path": "/test.py"},
            id=2,
        )
        request_json = request.to_json()

        # Handle request
        response = await server._handle_request(request_json)

        # Verify error response
        assert response.id == 2
        assert response.error is not None
        assert response.error.code == ErrorCode.FILE_NOT_FOUND
        assert "not found" in response.error.message.lower()
        assert response.error.data["file_path"] == "/test.py"
