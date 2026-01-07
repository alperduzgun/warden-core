"""
Tool Executor Port

Abstract interface for tool execution.
Implementations handle actual tool logic (built-in tools, bridge tools, etc.).
"""

from abc import ABC, abstractmethod
from typing import Any, Dict

from warden.mcp.domain.models import MCPToolDefinition, MCPToolResult


class IToolExecutor(ABC):
    """
    Abstract tool executor interface.

    Defines the contract for executing MCP tools.
    Different executors handle different tool categories
    (built-in, bridge-based, custom, etc.).
    """

    @abstractmethod
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
        ...

    @abstractmethod
    def supports(self, tool_name: str) -> bool:
        """
        Check if this executor supports the given tool.

        Args:
            tool_name: Name of the tool to check

        Returns:
            True if this executor can handle the tool
        """
        ...

    @property
    @abstractmethod
    def is_available(self) -> bool:
        """
        Check if this executor is available.

        Some executors may be unavailable if dependencies
        are missing (e.g., WardenBridge not installed).

        Returns:
            True if executor is ready to use
        """
        ...
