"""
Base Warden Adapter

Abstract base class for all MCP tool adapters.
Provides common functionality for WardenBridge integration
and tool definition management.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional

from warden.mcp.ports.tool_executor import IToolExecutor
from warden.mcp.domain.models import MCPToolDefinition, MCPToolResult
from warden.mcp.domain.enums import ToolCategory
from warden.mcp.domain.errors import MCPToolExecutionError

# Optional imports for bridge functionality
try:
    from warden.cli_bridge.bridge import WardenBridge
    BRIDGE_AVAILABLE = True
except ImportError:
    BRIDGE_AVAILABLE = False
    WardenBridge = None  # type: ignore

# Optional logging
try:
    from warden.shared.infrastructure.logging import get_logger
    logger = get_logger(__name__)
except ImportError:
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)


class BaseWardenAdapter(IToolExecutor, ABC):
    """
    Abstract base class for Warden MCP tool adapters.

    Provides:
        - WardenBridge integration with lazy initialization
        - Common tool registration patterns
        - Error handling and logging
        - Supports check via SUPPORTED_TOOLS frozenset

    Subclasses must implement:
        - SUPPORTED_TOOLS: frozenset of tool names this adapter handles
        - TOOL_CATEGORY: The ToolCategory for this adapter's tools
        - get_tool_definitions(): Return list of MCPToolDefinition
        - _execute_tool(): Handle actual tool execution
    """

    # Override in subclasses
    SUPPORTED_TOOLS: frozenset = frozenset()
    TOOL_CATEGORY: ToolCategory = ToolCategory.STATUS

    def __init__(
        self,
        project_root: Path,
        bridge: Optional[Any] = None,
    ) -> None:
        """
        Initialize adapter.

        Args:
            project_root: Project root directory
            bridge: Optional pre-initialized WardenBridge instance
        """
        self.project_root = project_root
        self._bridge = bridge
        self._bridge_initialized = bridge is not None

    @property
    def bridge(self) -> Optional[Any]:
        """
        Get WardenBridge instance (lazy initialization).

        Returns:
            WardenBridge instance or None if unavailable
        """
        if not self._bridge_initialized and BRIDGE_AVAILABLE:
            try:
                self._bridge = WardenBridge(project_root=self.project_root)
                self._bridge_initialized = True
                logger.info(
                    "warden_bridge_initialized",
                    adapter=self.__class__.__name__,
                    project_root=str(self.project_root),
                )
            except Exception as e:
                logger.warning(
                    "warden_bridge_init_failed",
                    adapter=self.__class__.__name__,
                    error=str(e),
                )
                self._bridge_initialized = True  # Don't retry
        return self._bridge

    @property
    def is_available(self) -> bool:
        """Check if adapter is available (bridge accessible)."""
        return self.bridge is not None

    def supports(self, tool_name: str) -> bool:
        """Check if this adapter supports the given tool."""
        return tool_name in self.SUPPORTED_TOOLS

    @abstractmethod
    def get_tool_definitions(self) -> List[MCPToolDefinition]:
        """
        Get all tool definitions for this adapter.

        Returns:
            List of MCPToolDefinition instances
        """
        ...

    @abstractmethod
    async def _execute_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> MCPToolResult:
        """
        Execute a specific tool.

        Args:
            tool_name: Name of tool to execute
            arguments: Tool arguments

        Returns:
            Tool execution result
        """
        ...

    async def execute(
        self,
        tool: MCPToolDefinition,
        arguments: Dict[str, Any],
    ) -> MCPToolResult:
        """
        Execute a tool and return results.

        Args:
            tool: Tool definition to execute
            arguments: Tool arguments from MCP request

        Returns:
            Tool result with content

        Raises:
            MCPToolExecutionError: If execution fails
        """
        if not self.supports(tool.name):
            raise MCPToolExecutionError(
                tool.name,
                f"Tool not supported by {self.__class__.__name__}",
            )

        try:
            logger.info(
                "mcp_tool_executing",
                tool=tool.name,
                adapter=self.__class__.__name__,
                arguments=list(arguments.keys()),
            )
            result = await self._execute_tool(tool.name, arguments)
            logger.info(
                "mcp_tool_completed",
                tool=tool.name,
                adapter=self.__class__.__name__,
                is_error=result.is_error,
            )
            return result

        except MCPToolExecutionError:
            raise
        except Exception as e:
            logger.error(
                "mcp_tool_error",
                tool=tool.name,
                adapter=self.__class__.__name__,
                error=str(e),
            )
            raise MCPToolExecutionError(tool.name, str(e))

    def _create_tool_definition(
        self,
        name: str,
        description: str,
        properties: Optional[Dict[str, Any]] = None,
        required: Optional[List[str]] = None,
    ) -> MCPToolDefinition:
        """
        Helper to create tool definitions with consistent structure.

        Args:
            name: Tool name
            description: Tool description
            properties: JSON Schema properties for input
            required: List of required property names

        Returns:
            MCPToolDefinition instance
        """
        input_schema: Dict[str, Any] = {
            "type": "object",
            "properties": properties or {},
            "required": required or [],
        }

        return MCPToolDefinition(
            name=name,
            description=description,
            category=self.TOOL_CATEGORY,
            input_schema=input_schema,
            requires_bridge=True,
        )
