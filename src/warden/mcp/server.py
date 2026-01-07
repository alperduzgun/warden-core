"""
MCP Server Implementation

STDIO-based MCP server for AI assistant integration.
Exposes Warden reports as resources and validation as tools.
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from warden.mcp.protocol import (
    MCPProtocol,
    MCPServerInfo,
    MCPServerCapabilities,
    MCPTool,
    MCPToolResult,
    MCPErrorCode,
)
from warden.mcp.resources import MCPResourceManager

# Optional imports for tool functionality
try:
    from warden.cli_bridge.bridge import WardenBridge
    BRIDGE_AVAILABLE = True
except ImportError:
    BRIDGE_AVAILABLE = False

try:
    from warden.shared.infrastructure.logging import get_logger
    logger = get_logger(__name__)
except ImportError:
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)


# MCP Protocol version
PROTOCOL_VERSION = "2024-11-05"


class MCPServer:
    """
    MCP Server with STDIO transport.

    Implements the Model Context Protocol for AI assistant integration,
    exposing Warden reports as resources and validation capabilities as tools.
    """

    def __init__(
        self,
        project_root: Optional[Path] = None,
    ):
        """
        Initialize MCP server.

        Args:
            project_root: Project root directory (default: cwd)
        """
        self.project_root = project_root or Path.cwd()
        self.protocol = MCPProtocol()
        self.resource_manager = MCPResourceManager(self.project_root)

        # Initialize bridge for tool execution (optional)
        self.bridge: Optional[Any] = None
        if BRIDGE_AVAILABLE:
            try:
                self.bridge = WardenBridge(project_root=self.project_root)
            except Exception as e:
                logger.warning(f"WardenBridge initialization failed: {e}")

        self._running = False
        self._initialized = False

        # Register MCP method handlers
        self._register_handlers()

    def _register_handlers(self) -> None:
        """Register all MCP method handlers."""
        # Core lifecycle methods
        self.protocol.register_handler("initialize", self._handle_initialize)
        self.protocol.register_handler("initialized", self._handle_initialized)
        self.protocol.register_handler("ping", self._handle_ping)

        # Resource methods
        self.protocol.register_handler("resources/list", self._handle_resources_list)
        self.protocol.register_handler("resources/read", self._handle_resources_read)

        # Tool methods
        self.protocol.register_handler("tools/list", self._handle_tools_list)
        self.protocol.register_handler("tools/call", self._handle_tools_call)

    async def start(self) -> None:
        """
        Start the MCP server on STDIO.

        Reads JSON-RPC messages from stdin, processes them,
        and writes responses to stdout.
        """
        self._running = True
        logger.info("mcp_server_starting", project_root=str(self.project_root))

        try:
            while self._running:
                # Read line from stdin
                line = await self._read_line()
                if line is None:
                    break

                line = line.strip()
                if not line:
                    continue

                # Process message and send response
                response = await self.protocol.handle_message(line)
                if response:
                    await self._write_line(response)

        except asyncio.CancelledError:
            logger.info("mcp_server_cancelled")
        except Exception as e:
            logger.error("mcp_server_error", error=str(e))
        finally:
            self._running = False
            logger.info("mcp_server_stopped")

    async def stop(self) -> None:
        """Stop the MCP server gracefully."""
        self._running = False

    async def _read_line(self) -> Optional[str]:
        """Read a line from stdin asynchronously."""
        loop = asyncio.get_event_loop()
        try:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            return line if line else None
        except Exception:
            return None

    async def _write_line(self, data: str) -> None:
        """Write a line to stdout."""
        sys.stdout.write(data + "\n")
        sys.stdout.flush()

    # =========================================================================
    # MCP Method Handlers
    # =========================================================================

    async def _handle_initialize(
        self, params: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Handle initialize request.

        Returns server capabilities and information.
        """
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {
                "resources": {},
                "tools": {},
            },
            "serverInfo": {
                "name": "warden-mcp",
                "version": "1.0.0",
            },
        }

    async def _handle_initialized(
        self, params: Optional[Dict[str, Any]]
    ) -> None:
        """Handle initialized notification."""
        self._initialized = True
        logger.info("mcp_client_initialized")
        return None

    async def _handle_ping(
        self, params: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Handle ping request."""
        return {}

    async def _handle_resources_list(
        self, params: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Handle resources/list request.

        Returns list of available Warden report resources.
        """
        resources = self.resource_manager.list_resources()
        return {
            "resources": [r.to_dict() for r in resources],
        }

    async def _handle_resources_read(
        self, params: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Handle resources/read request.

        Returns content of the requested resource.
        """
        if not params or "uri" not in params:
            raise ValueError("Missing required parameter: uri")

        uri = params["uri"]

        try:
            content = self.resource_manager.read_resource(uri)
            return {
                "contents": [content.to_dict()],
            }
        except ValueError as e:
            raise ValueError(str(e))

    async def _handle_tools_list(
        self, params: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Handle tools/list request.

        Returns list of available Warden tools.
        """
        tools = self._get_available_tools()
        return {
            "tools": [t.to_dict() for t in tools],
        }

    async def _handle_tools_call(
        self, params: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Handle tools/call request.

        Executes the requested tool and returns results.
        """
        if not params or "name" not in params:
            raise ValueError("Missing required parameter: name")

        tool_name = params["name"]
        arguments = params.get("arguments", {})

        result = await self._execute_tool(tool_name, arguments)
        return result.to_dict()

    # =========================================================================
    # Tool Definitions and Execution
    # =========================================================================

    def _get_available_tools(self) -> List[MCPTool]:
        """Get list of available tools."""
        tools = [
            MCPTool(
                name="warden_status",
                description="Get Warden security status for the current project",
                input_schema={
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            ),
            MCPTool(
                name="warden_list_reports",
                description="List all available Warden reports",
                input_schema={
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            ),
        ]

        # Add scan tool if bridge is available
        if self.bridge is not None:
            tools.extend([
                MCPTool(
                    name="warden_scan",
                    description="Run Warden security scan on the project",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "Path to scan (default: project root)",
                            },
                            "frames": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Specific frames to run (default: all enabled)",
                            },
                        },
                        "required": [],
                    },
                ),
                MCPTool(
                    name="warden_get_config",
                    description="Get current Warden configuration",
                    input_schema={
                        "type": "object",
                        "properties": {},
                        "required": [],
                    },
                ),
                MCPTool(
                    name="warden_list_frames",
                    description="List available validation frames",
                    input_schema={
                        "type": "object",
                        "properties": {},
                        "required": [],
                    },
                ),
            ])

        return tools

    async def _execute_tool(
        self, tool_name: str, arguments: Dict[str, Any]
    ) -> MCPToolResult:
        """Execute a tool and return results."""
        try:
            if tool_name == "warden_status":
                return await self._tool_status()
            elif tool_name == "warden_list_reports":
                return await self._tool_list_reports()
            elif tool_name == "warden_scan":
                return await self._tool_scan(arguments)
            elif tool_name == "warden_get_config":
                return await self._tool_get_config()
            elif tool_name == "warden_list_frames":
                return await self._tool_list_frames()
            else:
                return MCPToolResult(
                    content=[{"type": "text", "text": f"Unknown tool: {tool_name}"}],
                    is_error=True,
                )
        except Exception as e:
            return MCPToolResult(
                content=[{"type": "text", "text": f"Tool execution error: {e}"}],
                is_error=True,
            )

    async def _tool_status(self) -> MCPToolResult:
        """Get Warden status."""
        status_file = self.project_root / ".warden" / "ai_status.md"

        if status_file.exists():
            content = status_file.read_text(encoding="utf-8")
            return MCPToolResult(
                content=[{"type": "text", "text": content}],
            )
        else:
            return MCPToolResult(
                content=[{"type": "text", "text": "Warden status file not found. Run 'warden scan' first."}],
            )

    async def _tool_list_reports(self) -> MCPToolResult:
        """List all available reports."""
        reports = self.resource_manager.list_all_reports()

        if not reports:
            return MCPToolResult(
                content=[{"type": "text", "text": "No reports found. Run 'warden scan' to generate reports."}],
            )

        text = "Available Warden Reports:\n\n"
        for report in reports:
            size_kb = report["size"] / 1024
            text += f"- {report['name']} ({size_kb:.1f} KB)\n"
            text += f"  Path: {report['path']}\n"
            text += f"  Type: {report['mime_type']}\n\n"

        return MCPToolResult(
            content=[{"type": "text", "text": text}],
        )

    async def _tool_scan(self, arguments: Dict[str, Any]) -> MCPToolResult:
        """Run Warden scan."""
        if self.bridge is None:
            return MCPToolResult(
                content=[{"type": "text", "text": "Warden bridge not available"}],
                is_error=True,
            )

        path = arguments.get("path", str(self.project_root))
        frames = arguments.get("frames")

        try:
            result = await self.bridge.execute_pipeline(
                file_path=path,
                frames=frames,
            )
            return MCPToolResult(
                content=[{
                    "type": "text",
                    "text": json.dumps(result, indent=2, default=str),
                }],
            )
        except Exception as e:
            return MCPToolResult(
                content=[{"type": "text", "text": f"Scan failed: {e}"}],
                is_error=True,
            )

    async def _tool_get_config(self) -> MCPToolResult:
        """Get Warden configuration."""
        if self.bridge is None:
            return MCPToolResult(
                content=[{"type": "text", "text": "Warden bridge not available"}],
                is_error=True,
            )

        try:
            config = await self.bridge.get_config()
            return MCPToolResult(
                content=[{
                    "type": "text",
                    "text": json.dumps(config, indent=2, default=str),
                }],
            )
        except Exception as e:
            return MCPToolResult(
                content=[{"type": "text", "text": f"Failed to get config: {e}"}],
                is_error=True,
            )

    async def _tool_list_frames(self) -> MCPToolResult:
        """List available validation frames."""
        if self.bridge is None:
            return MCPToolResult(
                content=[{"type": "text", "text": "Warden bridge not available"}],
                is_error=True,
            )

        try:
            frames = await self.bridge.get_available_frames()
            return MCPToolResult(
                content=[{
                    "type": "text",
                    "text": json.dumps(frames, indent=2, default=str),
                }],
            )
        except Exception as e:
            return MCPToolResult(
                content=[{"type": "text", "text": f"Failed to list frames: {e}"}],
                is_error=True,
            )
