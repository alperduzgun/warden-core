"""
MCP Service

Main application orchestrator for MCP operations.
Coordinates transport, session management, and use case execution.
"""

import json
import asyncio
import os
from pathlib import Path
from typing import Any, Dict, Optional

from warden.mcp.domain.models import MCPSession
from warden.mcp.domain.enums import MCPErrorCode
from warden.mcp.domain.errors import MCPProtocolError, MCPDomainError
from warden.mcp.domain.value_objects import ProtocolVersion, ServerInfo, ServerCapabilities
from warden.mcp.ports.transport import ITransport
from warden.mcp.application.tool_executor import ToolExecutorService
from warden.mcp.application.resource_provider import ResourceProviderService
from warden.mcp.application.session_manager import SessionManager
from warden.mcp.infrastructure.tool_registry import ToolRegistry

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
        project_root: Optional[Path] = None,
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
        
        # Background tasks
        self._watcher_task: Optional[asyncio.Task] = None

        # Handler dispatch table
        self._handlers: Dict[str, Any] = {
            "initialize": self._handle_initialize,
            "initialized": self._handle_initialized,
            "ping": self._handle_ping,
            "resources/list": self._handle_resources_list,
            "resources/read": self._handle_resources_read,
            "tools/list": self._handle_tools_list,
            "tools/call": self._handle_tools_call,
        }

    async def start(self) -> None:
        """Start the MCP service main loop."""
        session = self.session_manager.create_session()
        session.start()

        # Start background tasks
        self._watcher_task = asyncio.create_task(self._watch_report_file())

        logger.info("mcp_service_starting", project_root=str(self.project_root))

        try:
            while self.transport.is_open:
                message = await self.transport.read_message()
                if message is None:
                    break
                if not message:
                    continue

                response = await self._process_message(message, session)
                if response:
                    await self.transport.write_message(response)

        except Exception as e:
            logger.error("mcp_service_error", error=str(e))
            session.set_error()
        finally:
            # Cancel background tasks
            if self._watcher_task:
                self._watcher_task.cancel()
                try:
                    await self._watcher_task
                except asyncio.CancelledError:
                    pass
            
            session.stop()
            await self.transport.close()
            logger.info("mcp_service_stopped")

    async def _process_message(
        self, raw: str, session: MCPSession
    ) -> Optional[str]:
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

    async def _handle_initialize(
        self, params: Optional[Dict], session: MCPSession
    ) -> Dict:
        """Handle initialize request."""
        return {
            "protocolVersion": str(self._protocol_version),
            "capabilities": self._capabilities.to_dict(),
            "serverInfo": self._server_info.to_dict(),
        }

    async def _handle_initialized(
        self, params: Optional[Dict], session: MCPSession
    ) -> None:
        """Handle initialized notification."""
        session.mark_initialized(params)
        logger.info("mcp_client_initialized")
        return None

    async def _handle_ping(
        self, params: Optional[Dict], session: MCPSession
    ) -> Dict:
        """Handle ping request."""
        return {}

    async def _handle_resources_list(
        self, params: Optional[Dict], session: MCPSession
    ) -> Dict:
        """Handle resources/list request."""
        resources = await self.resource_provider.list_resources()
        return {"resources": [r.to_mcp_format() for r in resources]}

    async def _handle_resources_read(
        self, params: Optional[Dict], session: MCPSession
    ) -> Dict:
        """Handle resources/read request."""
        if not params or "uri" not in params:
            raise MCPProtocolError("Missing required parameter: uri")
        uri = params["uri"]
        content = await self.resource_provider.read_resource(uri)
        return {"contents": [content]}

    async def _handle_tools_list(
        self, params: Optional[Dict], session: MCPSession
    ) -> Dict:
        """Handle tools/list request."""
        tools = self._tool_registry.list_all(self.tool_executor.bridge_available)
        return {"tools": [t.to_mcp_format() for t in tools]}

    async def _handle_tools_call(
        self, params: Optional[Dict], session: MCPSession
    ) -> Dict:
        """Handle tools/call request."""
        if not params or "name" not in params:
            raise MCPProtocolError("Missing required parameter: name")
        result = await self.tool_executor.execute(
            params["name"],
            params.get("arguments", {}),
        )
        return result

    # =========================================================================
    # Notification & Background Tasks
    # =========================================================================

    async def send_notification(self, method: str, params: Dict[str, Any]) -> None:
        """
        Send a JSON-RPC notification to the client.

        Args:
            method: Notification method name
            params: Notification parameters
        """
        if not self.transport.is_open:
            return

        message = json.dumps({
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        })
        await self.transport.write_message(message)

    async def _watch_report_file(self) -> None:
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
            try:
                last_mtime = os.path.getmtime(report_path)
            except OSError:
                pass

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
                        await self.send_notification(
                            "notifications/resources/updated",
                            {"uri": "warden://reports/latest"}
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
        return json.dumps({
            "jsonrpc": "2.0",
            "id": request_id,
            "result": result,
        })

    def _error_response(
        self, request_id: Any, code: MCPErrorCode, message: str
    ) -> str:
        """Create error response JSON."""
        return json.dumps({
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": int(code), "message": message},
        })
