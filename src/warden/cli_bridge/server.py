"""
IPC Server - Unix Socket and STDIO transport for JSON-RPC

Provides async IPC server supporting both Unix sockets and STDIO for communication
with the Ink CLI.
"""

import asyncio
import sys
import os
from pathlib import Path
from typing import Optional, Callable, Awaitable, Any, Dict
import signal

from warden.cli_bridge.protocol import (
    IPCRequest,
    IPCResponse,
    IPCError,
    ErrorCode,
    StreamChunk,
)

# Optional imports - graceful degradation if Warden logging not available
try:
    from warden.shared.infrastructure.logging import get_logger
    logger = get_logger(__name__)
except ImportError:
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

# Import bridge - must be imported after protocol to avoid circular import
from warden.cli_bridge.bridge import WardenBridge


class IPCServer:
    """
    Async IPC Server supporting Unix sockets and STDIO

    Implements JSON-RPC 2.0 protocol for method invocation.
    """

    def __init__(
        self,
        bridge: Optional[WardenBridge] = None,
        transport: str = "stdio",
        socket_path: Optional[str] = None,
    ) -> None:
        """
        Initialize IPC server

        Args:
            bridge: Warden bridge instance (creates default if None)
            transport: Transport type ('stdio' or 'socket')
            socket_path: Unix socket path (required if transport='socket')
        """
        self.bridge = bridge or WardenBridge()
        self.transport = transport
        self.socket_path = socket_path
        self.server: Optional[asyncio.Server] = None
        self.running = False

        # Method routing table
        self.methods = {
            "ping": self.bridge.ping,
            "scan": self.bridge.scan,  # Scan directory/file
            "analyze": self.bridge.analyze,  # Analyze single file
            "execute_pipeline": self.bridge.execute_pipeline,
            "execute_pipeline_stream": self.bridge.execute_pipeline_stream,  # NEW: Real-time streaming
            "get_config": self.bridge.get_config,
            "analyze_with_llm": self._handle_streaming_method,
            "get_available_frames": self.bridge.get_available_frames,
            "get_available_providers": self.bridge.get_available_providers,
            "test_provider": self.bridge.test_provider,
            "update_frame_status": self.bridge.update_frame_status,  # NEW: Update frame enabled status
        }

        logger.info("ipc_server_initialized", transport=transport)

    async def start(self) -> None:
        """Start IPC server based on configured transport"""
        self.running = True

        if self.transport == "stdio":
            await self._run_stdio()
        elif self.transport == "socket":
            if not self.socket_path:
                raise ValueError("socket_path required for socket transport")
            await self._run_socket()
        else:
            raise ValueError(f"Invalid transport: {self.transport}")

    async def stop(self) -> None:
        """Stop IPC server gracefully"""
        logger.info("ipc_server_stopping")
        self.running = False

        if self.server:
            self.server.close()
            await self.server.wait_closed()

        # Clean up socket file
        if self.transport == "socket" and self.socket_path:
            try:
                os.unlink(self.socket_path)
            except FileNotFoundError:
                pass

        logger.info("ipc_server_stopped")

    async def _run_stdio(self) -> None:
        """Run server using STDIO (for subprocess communication)"""
        logger.info("ipc_server_starting_stdio")

        # Set up graceful shutdown
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(self.stop()))

        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)

        writer_transport, writer_protocol = await loop.connect_write_pipe(
            asyncio.streams.FlowControlMixin, sys.stdout
        )
        writer = asyncio.StreamWriter(writer_transport, writer_protocol, reader, loop)

        try:
            while self.running:
                # Read line-delimited JSON
                line = await reader.readline()
                if not line:
                    # EOF - client closed connection
                    break

                try:
                    request_data = line.decode("utf-8").strip()
                    if not request_data:
                        continue

                    response = await self._handle_request(request_data)
                    response_json = response.to_json() + "\n"

                    writer.write(response_json.encode("utf-8"))
                    await writer.drain()

                except Exception as e:
                    logger.error("stdio_request_error", error=str(e))
                    error_response = IPCResponse.create_error(
                        error_obj=IPCError.from_exception(e), request_id=None
                    )
                    writer.write((error_response.to_json() + "\n").encode("utf-8"))
                    await writer.drain()

        except asyncio.CancelledError:
            logger.info("stdio_cancelled")
        finally:
            writer.close()
            await writer.wait_closed()

    async def _run_socket(self) -> None:
        """Run server using Unix socket"""
        logger.info("ipc_server_starting_socket", socket_path=self.socket_path)

        # Remove existing socket file
        if self.socket_path and os.path.exists(self.socket_path):
            os.unlink(self.socket_path)

        async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            """Handle client connection"""
            addr = writer.get_extra_info("peername")
            logger.info("client_connected", address=addr)

            try:
                while self.running:
                    # Read line-delimited JSON
                    line = await reader.readline()
                    if not line:
                        break

                    request_data = line.decode("utf-8").strip()
                    if not request_data:
                        continue

                    # Handle request (may be streaming or non-streaming)
                    await self._handle_request_with_writer(request_data, writer)

            except asyncio.CancelledError:
                logger.info("client_cancelled", address=addr)
            except Exception as e:
                logger.error("client_error", error=str(e), address=addr)
            finally:
                writer.close()
                await writer.wait_closed()
                logger.info("client_disconnected", address=addr)

        # Start server with increased line limit for large JSON responses
        # Default limit is 64KB, we increase to 10MB to handle large analysis results
        self.server = await asyncio.start_unix_server(
            handle_client,
            path=self.socket_path,
            limit=10 * 1024 * 1024  # 10MB limit for large responses
        )

        logger.info("ipc_server_listening", socket_path=self.socket_path, limit_mb=10)

        async with self.server:
            await self.server.serve_forever()

    async def _handle_request(self, data: str) -> IPCResponse:
        """
        Handle JSON-RPC request

        Args:
            data: JSON-RPC request string

        Returns:
            JSON-RPC response
        """
        request_id = None

        try:
            # Parse request
            request = IPCRequest.from_json(data)
            request_id = request.id

            # Validate request
            validation_error = request.validate()
            if validation_error:
                return IPCResponse.create_error(error_obj=validation_error, request_id=request_id)

            logger.info("ipc_request", method=request.method, id=request_id)

            # Route to method
            method = self.methods.get(request.method)
            if not method:
                return IPCResponse.create_error(
                    error_obj=IPCError(
                        code=ErrorCode.METHOD_NOT_FOUND,
                        message=f"Method not found: {request.method}",
                        data={"available_methods": list(self.methods.keys())},
                    ),
                    request_id=request_id,
                )

            # Extract params
            if isinstance(request.params, dict):
                result = await method(**request.params)
            elif isinstance(request.params, list):
                result = await method(*request.params)
            elif request.params is None:
                result = await method()
            else:
                return IPCResponse.create_error(
                    error_obj=IPCError(code=ErrorCode.INVALID_PARAMS, message="Invalid params type"),
                    request_id=request_id,
                )

            logger.info("ipc_response", method=request.method, id=request_id, success=True)
            return IPCResponse.create_success(result, request_id)

        except IPCError as e:
            logger.warning("ipc_error", error=e.message, code=e.code, id=request_id)
            return IPCResponse.create_error(error_obj=e, request_id=request_id)

        except Exception as e:
            logger.error("ipc_internal_error", error=str(e), id=request_id)
            return IPCResponse.create_error(error_obj=IPCError.from_exception(e), request_id=request_id)

    async def _handle_request_with_writer(self, data: str, writer: asyncio.StreamWriter) -> None:
        """
        Handle JSON-RPC request with direct access to writer (for streaming support).

        Args:
            data: JSON-RPC request string
            writer: Stream writer for sending responses

        Side effects:
            Writes response(s) to writer (one for non-streaming, multiple for streaming)
        """
        request_id = None

        try:
            # Parse request
            request = IPCRequest.from_json(data)
            request_id = request.id

            # Validate request
            validation_error = request.validate()
            if validation_error:
                response = IPCResponse.create_error(error_obj=validation_error, request_id=request_id)
                writer.write((response.to_json() + "\n").encode("utf-8"))
                await writer.drain()
                return

            logger.info("ipc_request", method=request.method, id=request_id)

            # Route to method
            method = self.methods.get(request.method)
            if not method:
                response = IPCResponse.create_error(
                    error_obj=IPCError(
                        code=ErrorCode.METHOD_NOT_FOUND,
                        message=f"Method not found: {request.method}",
                        data={"available_methods": list(self.methods.keys())},
                    ),
                    request_id=request_id,
                )
                writer.write((response.to_json() + "\n").encode("utf-8"))
                await writer.drain()
                return

            # Extract params and call method
            import inspect

            # First check if the method is an async generator function (for streaming)
            # This needs to be checked BEFORE calling the method
            is_streaming_method = inspect.isasyncgenfunction(method)

            if isinstance(request.params, dict):
                result = method(**request.params)
            elif isinstance(request.params, list):
                result = method(*request.params)
            elif request.params is None:
                result = method()
            else:
                response = IPCResponse.create_error(
                    error_obj=IPCError(code=ErrorCode.INVALID_PARAMS, message="Invalid params type"),
                    request_id=request_id,
                )
                writer.write((response.to_json() + "\n").encode("utf-8"))
                await writer.drain()
                return

            # Check if result is async generator (streaming)
            if is_streaming_method or inspect.isasyncgen(result):
                # Streaming response - write multiple line-delimited JSON events
                logger.info("ipc_streaming_started", method=request.method, id=request_id)

                async for event in result:
                    # Each event is a dict with type/event/data
                    response = IPCResponse.create_success(event, request_id)
                    writer.write((response.to_json() + "\n").encode("utf-8"))
                    await writer.drain()

                logger.info("ipc_streaming_complete", method=request.method, id=request_id)
            else:
                # Regular (non-streaming) response - await if coroutine
                if inspect.iscoroutine(result):
                    result = await result

                response = IPCResponse.create_success(result, request_id)
                writer.write((response.to_json() + "\n").encode("utf-8"))
                await writer.drain()

                logger.info("ipc_response", method=request.method, id=request_id, success=True)

        except IPCError as e:
            logger.warning("ipc_error", error=e.message, code=e.code, id=request_id)
            response = IPCResponse.create_error(error_obj=e, request_id=request_id)
            writer.write((response.to_json() + "\n").encode("utf-8"))
            await writer.drain()

        except Exception as e:
            logger.error("ipc_internal_error", error=str(e), id=request_id)
            response = IPCResponse.create_error(error_obj=IPCError.from_exception(e), request_id=request_id)
            writer.write((response.to_json() + "\n").encode("utf-8"))
            await writer.drain()

    async def _handle_streaming_method(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        """
        Handle streaming method (analyze_with_llm)

        Note: For true streaming, we would need SSE or WebSocket transport.
        For now, we collect all chunks and return them.

        TODO: Implement proper streaming support
        """
        chunks = []
        async for chunk in self.bridge.analyze_with_llm(*args, **kwargs):
            chunks.append(chunk)

        return {"chunks": chunks, "streaming": False}


async def run_ipc_server(
    transport: str = "stdio",
    socket_path: Optional[str] = None,
) -> None:
    """
    Run IPC server (convenience function)

    Args:
        transport: Transport type ('stdio' or 'socket')
        socket_path: Unix socket path (required if transport='socket')
    """
    server = IPCServer(transport=transport, socket_path=socket_path)
    await server.start()


if __name__ == "__main__":
    # Run as standalone server

    import argparse

    parser = argparse.ArgumentParser(description="Warden IPC Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "socket"],
        default="stdio",
        help="Transport type",
    )
    parser.add_argument(
        "--socket-path",
        default="/tmp/warden-ipc.sock",
        help="Unix socket path",
    )

    args = parser.parse_args()

    asyncio.run(run_ipc_server(transport=args.transport, socket_path=args.socket_path))
