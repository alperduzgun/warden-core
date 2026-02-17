"""
MCP Service

Main application orchestrator for MCP operations.
Coordinates transport, session management, and use case execution.
"""

import asyncio
import contextlib
import json
import os
from pathlib import Path
from typing import Any

from warden.mcp.application.resource_provider import ResourceProviderService
from warden.mcp.application.session_manager import SessionManager
from warden.mcp.application.tool_executor import ToolExecutorService
from warden.mcp.domain.enums import MCPErrorCode
from warden.mcp.domain.errors import MCPDomainError, MCPProtocolError
from warden.mcp.domain.models import MCPSession
from warden.mcp.domain.value_objects import ProtocolVersion, ServerCapabilities, ServerInfo
from warden.mcp.infrastructure.tool_registry import ToolRegistry
from warden.mcp.ports.transport import ITransport

# Optional logging
try:
    from warden.shared.infrastructure.logging import get_logger

    logger = get_logger(__name__)
except ImportError:
    import logging

    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)


class MCPService:
    """
    Main MCP application service.

    Coordinates transport, session management, and use case execution.
    This is the primary entry point for MCP operations.
    """

    def __init__(
        self,
        transport: ITransport,
        project_root: Path | None = None,
    ) -> None:
        """
        Initialize MCP service.

        Args:
            transport: Transport implementation for I/O
            project_root: Project root directory
        """
        self.transport = transport
        self.project_root = project_root or Path.cwd()

        # Protocol constants
        self._protocol_version = ProtocolVersion()
        self._server_info = ServerInfo()
        self._capabilities = ServerCapabilities()

        # Initialize sub-services
        self.session_manager = SessionManager()
        self.tool_executor = ToolExecutorService(self.project_root)
        self.resource_provider = ResourceProviderService(self.project_root)
        self._tool_registry = ToolRegistry()

        # Register Setup Resource Adapter
        # This provides the Agentry Protocol
        from warden.mcp.infrastructure.adapters.setup_resource_adapter import SetupResourceAdapter

        self._setup_adapter = SetupResourceAdapter(self.project_root)

        # Background tasks
        self._watcher_task: asyncio.Task | None = None

        # Handler dispatch table
        self._handlers: dict[str, Any] = {
            "initialize": self._handle_initialize_async,
            "initialized": self._handle_initialized_async,
            "ping": self._handle_ping_async,
            "resources/list": self._handle_resources_list_async,
            "resources/read": self._handle_resources_read_async,
            "tools/list": self._handle_tools_list_async,
            "tools/call": self._handle_tools_call_async,
        }

    async def start_async(self) -> None:
        """Start the MCP service main loop."""
        session = self.session_manager.create_session()
        session.start()

        # Start background tasks
        self._watcher_task = asyncio.create_task(self._watch_report_file_async())

        logger.info("mcp_service_starting", project_root=str(self.project_root))

        try:
            while self.transport.is_open:
                message = await self.transport.read_message()
                if message is None:
                    break
                if not message:
                    continue

                response = await self._process_message_async(message, session)
                if response:
                    await self.transport.write_message(response)

        except Exception as e:
            logger.error("mcp_service_error", error=str(e))
            session.set_error()
        finally:
            # Cancel background tasks
            if self._watcher_task:
                self._watcher_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._watcher_task

            session.stop()
            await self.transport.close()
            logger.info("mcp_service_stopped")

    async def _process_message_async(self, raw: str, session: MCPSession) -> str | None:
        """Process incoming message and return response."""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            return self._error_response(None, MCPErrorCode.PARSE_ERROR, f"Parse error: {e}")

        method = data.get("method")
        request_id = data.get("id")
        params = data.get("params")

        handler = self._handlers.get(method)
        if not handler:
            return self._error_response(
                request_id,
                MCPErrorCode.METHOD_NOT_FOUND,
                f"Method not found: {method}",
            )

        try:
            result = await handler(params, session)
            # Notifications (no id) don't get responses
            if request_id is None:
                return None
            return self._success_response(request_id, result)
        except MCPDomainError as e:
            return self._error_response(request_id, e.code, e.message)
        except Exception as e:
            return self._error_response(
                request_id,
                MCPErrorCode.INTERNAL_ERROR,
                str(e),
            )

    # =========================================================================
    # Handler Methods
    # =========================================================================

    async def _handle_initialize_async(self, params: dict | None, session: MCPSession) -> dict:
        """Handle initialize request."""
        return {
            "protocolVersion": str(self._protocol_version),
            "capabilities": self._capabilities.to_dict(),
            "serverInfo": self._server_info.to_dict(),
        }

    async def _handle_initialized_async(self, params: dict | None, session: MCPSession) -> None:
        """Handle initialized notification."""
        session.mark_initialized(params)
        logger.info("mcp_client_initialized")
        return None

    async def _handle_ping_async(self, params: dict | None, session: MCPSession) -> dict:
        """Handle ping request."""
        return {}

    async def _handle_resources_list_async(self, params: dict | None, session: MCPSession) -> dict:
        """Handle resources/list request."""
        resources = await self.resource_provider.list_resources()

        # Merge Protocol Resources
        protocol_resources = self._setup_adapter.list_resources()

        all_resources = [r.to_mcp_format() for r in resources] + [r.to_mcp_format() for r in protocol_resources]
        return {"resources": all_resources}

    async def _handle_resources_read_async(self, params: dict | None, session: MCPSession) -> dict:
        """Handle resources/read request."""
        if not params or "uri" not in params:
            raise MCPProtocolError("Missing required parameter: uri")
        uri = params["uri"]

        # Check Protocol Resources first
        protocol_content = self._setup_adapter.read_resource(uri)
        if protocol_content:
            return {"contents": [{"uri": uri, "mimeType": "text/markdown", "text": protocol_content}]}

        content = await self.resource_provider.read_resource(uri)
        return {"contents": [content]}

    async def _handle_tools_list_async(self, params: dict | None, session: MCPSession) -> dict:
        """Handle tools/list request."""
        tools = self.tool_executor.registry.list_all(self.tool_executor.bridge_available)
        return {"tools": [t.to_mcp_format() for t in tools]}

    async def _handle_tools_call_async(self, params: dict | None, session: MCPSession) -> dict:
        """Handle tools/call request."""
        if not params or "name" not in params:
            raise MCPProtocolError("Missing required parameter: name")
        result = await self.tool_executor.execute_async(
            params["name"],
            params.get("arguments", {}),
        )
        return result

    # =========================================================================
    # Notification & Background Tasks
    # =========================================================================

    async def send_notification_async(self, method: str, params: dict[str, Any]) -> None:
        """
        Send a JSON-RPC notification to the client.

        Args:
            method: Notification method name
            params: Notification parameters
        """
        if not self.transport.is_open:
            return

        message = json.dumps(
            {
                "jsonrpc": "2.0",
                "method": method,
                "params": params,
            }
        )
        await self.transport.write_message(message)

    async def _watch_report_file_async(self) -> None:
        """
        Background task to watch warden_report.json for changes.
        Sends notifications/resources/updated when changed.
        """
        report_path = self.project_root / ".warden" / "reports" / "warden_report.json"

        # Check alternate location if default doesn't exist
        if not report_path.exists():
            alternate = self.project_root / "warden_report.json"
            if alternate.exists():
                report_path = alternate

        last_mtime = 0.0

        # Initial check
        if report_path.exists():
            with contextlib.suppress(OSError):
                last_mtime = os.path.getmtime(report_path)

        logger.info("mcp_report_watcher_started", path=str(report_path))

        while True:
            try:
                await asyncio.sleep(2.0)  # Polling interval

                if not report_path.exists():
                    continue

                try:
                    current_mtime = os.path.getmtime(report_path)
                    if current_mtime > last_mtime:
                        last_mtime = current_mtime

                        logger.info("mcp_report_updated", path=str(report_path))

                        # Notify clients that reports resource has changed
                        await self.send_notification_async(
                            "notifications/resources/updated", {"uri": "warden://reports/latest"}
                        )
                except OSError as e:
                    logger.warning("mcp_watcher_error", error=str(e))

            except asyncio.CancelledError:
                logger.info("mcp_report_watcher_stopped")
                break
            except Exception as e:
                logger.error("mcp_watcher_crash", error=str(e))
                await asyncio.sleep(5.0)  # Backoff on error

    # =========================================================================
    # Response Helpers
    # =========================================================================

    def _success_response(self, request_id: Any, result: Any) -> str:
        """Create success response JSON."""
        return json.dumps(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": result,
            }
        )

    def _error_response(self, request_id: Any, code: MCPErrorCode, message: str) -> str:
        """Create error response JSON."""
        return json.dumps(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": int(code), "message": message},
            }
        )
