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
from warden.mcp.domain.enums import MCPErrorCode, ToolCategory, ToolTier
from warden.mcp.domain.errors import MCPDomainError, MCPProtocolError
from warden.mcp.domain.models import MCPSession, MCPToolDefinition, MCPToolResult
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

    Tool Tiering:
        By default, tools/list returns only CORE-tier tools (8 essential tools).
        Agents can call warden_expand_tools(tier="extended") to unlock the
        full tool surface. The expanded tier is tracked per-session.
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

        # Session-level tool tier (starts at CORE, can be expanded)
        self._active_tier: ToolTier = ToolTier.CORE

        # Register the warden_expand_tools meta-tool in both registries
        self._register_meta_tools()

        # Background tasks
        self._watcher_task: asyncio.Task | None = None

        # Handler dispatch table
        self._handlers: dict[str, Any] = {
            "initialize": self._handle_initialize_async,
            # Both "initialized" (older) and "notifications/initialized" (standard MCP)
            "initialized": self._handle_initialized_async,
            "notifications/initialized": self._handle_initialized_async,
            "ping": self._handle_ping_async,
            "resources/list": self._handle_resources_list_async,
            "resources/read": self._handle_resources_read_async,
            "tools/list": self._handle_tools_list_async,
            "tools/call": self._handle_tools_call_async,
        }

    def _register_meta_tools(self) -> None:
        """Register meta-tools for tool tiering control."""
        expand_tool = MCPToolDefinition(
            name="warden_expand_tools",
            description=(
                "Unlock additional Warden tools beyond the default core set. "
                "Call with tier='extended' to access the full 44-tool surface "
                "including analysis, search, CI, cleanup, and fortification tools. "
                "Call with tier='core' to return to the default minimal set."
            ),
            category=ToolCategory.META,
            input_schema={
                "type": "object",
                "properties": {
                    "tier": {
                        "type": "string",
                        "description": "Tool tier to activate: 'core' (default 8 tools) or 'extended' (all tools)",
                        "enum": ["core", "extended"],
                    },
                },
                "required": ["tier"],
            },
            requires_bridge=False,
            tier=ToolTier.CORE,
        )
        # Register in both the service-level registry and the executor's registry
        self._tool_registry.register(expand_tool)
        self.tool_executor.registry.register(expand_tool)

    @property
    def active_tier(self) -> ToolTier:
        """Get the current active tool tier for this session."""
        return self._active_tier

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
        """
        Handle tools/list request.

        Returns tools filtered by the session's active tier.
        By default only CORE tools are returned. After calling
        warden_expand_tools(tier="extended"), all CORE + EXTENDED
        tools are returned.
        """
        tools = self.tool_executor.registry.list_by_tier(
            self._active_tier,
            self.tool_executor.bridge_available,
        )
        return {"tools": [t.to_mcp_format() for t in tools]}

    async def _handle_tools_call_async(self, params: dict | None, session: MCPSession) -> dict:
        """
        Handle tools/call request.

        Note: Tool *execution* is allowed for ALL registered tools regardless
        of the current tier. The tier only controls what tools/list returns.
        This ensures that if an agent knows a tool name, it can always call it.
        """
        if not params or "name" not in params:
            raise MCPProtocolError("Missing required parameter: name")

        tool_name = params["name"]

        # Handle the meta-tool directly in the service layer
        if tool_name == "warden_expand_tools":
            return self._handle_expand_tools(params.get("arguments", {}))

        result = await self.tool_executor.execute_async(
            tool_name,
            params.get("arguments", {}),
        )
        return result

    def _handle_expand_tools(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """
        Handle the warden_expand_tools meta-tool.

        Changes the session's active tier and returns information
        about how many tools are now visible.

        Args:
            arguments: Must contain "tier" key with value "core" or "extended"

        Returns:
            Tool result in MCP format
        """
        tier_str = arguments.get("tier", "").lower()

        tier_map = {
            "core": ToolTier.CORE,
            "extended": ToolTier.EXTENDED,
        }

        if tier_str not in tier_map:
            return MCPToolResult.error(f"Invalid tier: '{tier_str}'. Must be 'core' or 'extended'.").to_dict()

        new_tier = tier_map[tier_str]
        old_tier = self._active_tier
        self._active_tier = new_tier

        # Count tools at the new tier
        visible_tools = self.tool_executor.registry.list_by_tier(
            new_tier,
            self.tool_executor.bridge_available,
        )
        all_tools = self.tool_executor.registry.list_all(
            self.tool_executor.bridge_available,
        )

        # Build a summary of newly available tool categories
        tool_names = [t.name for t in visible_tools]

        logger.info(
            "tool_tier_changed",
            old_tier=old_tier.value,
            new_tier=new_tier.value,
            visible_count=len(visible_tools),
            total_count=len(all_tools),
        )

        return MCPToolResult.json_result(
            {
                "success": True,
                "previous_tier": old_tier.value,
                "active_tier": new_tier.value,
                "visible_tools": len(visible_tools),
                "total_tools": len(all_tools),
                "tools": tool_names,
            }
        ).to_dict()

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
