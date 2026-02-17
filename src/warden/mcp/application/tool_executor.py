"""
Tool Executor Service

Application service for tool execution.
Routes tool calls to appropriate executors.

Supports:
- Multi-adapter routing (each adapter handles a set of tools)
- Built-in tools (no bridge required)
- Legacy WardenBridgeAdapter for backward compatibility
- Dynamic adapter registration
"""

from pathlib import Path
from typing import Any

from warden.mcp.domain.errors import MCPToolExecutionError, MCPToolNotFoundError
from warden.mcp.domain.models import MCPToolResult
from warden.mcp.infrastructure.file_resource_repo import FileResourceRepository
from warden.mcp.infrastructure.tool_registry import ToolRegistry
from warden.mcp.infrastructure.warden_adapter import WardenBridgeAdapter
from warden.mcp.ports.tool_executor import IToolExecutor

# Optional logging
try:
    from warden.shared.infrastructure.logging import get_logger

    logger = get_logger(__name__)
except ImportError:
    import logging

    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)


class ToolExecutorService:
    """
    Application service for tool execution.

    Coordinates tool lookup, routing, and execution.
    Routes tool calls to appropriate adapters based on tool support.
    """

    def __init__(self, project_root: Path) -> None:
        """
        Initialize tool executor.

        Args:
            project_root: Project root directory
        """
        self.project_root = project_root
        self._registry = ToolRegistry()
        self._resource_repo = FileResourceRepository(project_root)

        # Adapter registry - stores all registered adapters
        self._adapters: list[IToolExecutor] = []

        # Legacy bridge adapter (for backward compatibility)
        self._bridge_adapter = WardenBridgeAdapter(project_root)

        # Initialize all available adapters
        self._initialize_adapters()

    def _initialize_adapters(self) -> None:
        """
        Initialize and register all available adapters.

        Adapters are imported dynamically to avoid circular imports
        and allow graceful degradation if dependencies are missing.
        """
        # Import adapters dynamically
        try:
            from warden.mcp.infrastructure.adapters.pipeline_adapter import PipelineAdapter

            self.register_adapter(PipelineAdapter(self.project_root))
        except ImportError:
            pass

        try:
            from warden.mcp.infrastructure.adapters.config_adapter import ConfigAdapter

            self.register_adapter(ConfigAdapter(self.project_root))
        except ImportError:
            pass

        try:
            from warden.mcp.infrastructure.adapters.health_adapter import HealthAdapter

            self.register_adapter(HealthAdapter(self.project_root))
        except ImportError:
            pass

        try:
            from warden.mcp.infrastructure.adapters.issue_adapter import IssueAdapter

            self.register_adapter(IssueAdapter(self.project_root))
        except ImportError:
            pass

        try:
            from warden.mcp.infrastructure.adapters.suppression_adapter import SuppressionAdapter

            self.register_adapter(SuppressionAdapter(self.project_root))
        except ImportError:
            pass

        try:
            from warden.mcp.infrastructure.adapters.search_adapter import SearchAdapter

            self.register_adapter(SearchAdapter(self.project_root))
        except ImportError:
            pass

        try:
            from warden.mcp.infrastructure.adapters.llm_adapter import LlmAdapter

            self.register_adapter(LlmAdapter(self.project_root))
        except ImportError:
            pass

        try:
            from warden.mcp.infrastructure.adapters.discovery_adapter import DiscoveryAdapter

            self.register_adapter(DiscoveryAdapter(self.project_root))
        except ImportError:
            pass

        try:
            from warden.mcp.infrastructure.adapters.analysis_adapter import AnalysisAdapter

            self.register_adapter(AnalysisAdapter(self.project_root))
        except ImportError:
            pass

        try:
            from warden.mcp.infrastructure.adapters.report_adapter import ReportAdapter

            self.register_adapter(ReportAdapter(self.project_root))
        except ImportError:
            pass

        try:
            from warden.mcp.infrastructure.adapters.cleanup_adapter import CleanupAdapter

            self.register_adapter(CleanupAdapter(self.project_root))
        except ImportError:
            pass

        try:
            from warden.mcp.infrastructure.adapters.fortification_adapter import FortificationAdapter

            self.register_adapter(FortificationAdapter(self.project_root))
        except ImportError:
            pass

        logger.info(
            "tool_adapters_initialized",
            adapter_count=len(self._adapters),
            adapters=[a.__class__.__name__ for a in self._adapters],
        )

    def register_adapter(self, adapter: IToolExecutor) -> None:
        """
        Register an adapter and its tools.

        Args:
            adapter: Adapter instance to register
        """
        self._adapters.append(adapter)

        # Register adapter's tools in the registry
        if hasattr(adapter, "get_tool_definitions"):
            self._registry.register_from_adapter(adapter)
            logger.info(
                "adapter_registered",
                adapter=adapter.__class__.__name__,
                tool_count=len(adapter.get_tool_definitions()),
            )

    def _find_adapter_for_tool(self, tool_name: str) -> IToolExecutor | None:
        """
        Find the adapter that supports the given tool.

        Args:
            tool_name: Name of the tool

        Returns:
            Adapter instance or None if not found
        """
        for adapter in self._adapters:
            if adapter.supports(tool_name):
                return adapter
        return None

    @property
    def bridge_available(self) -> bool:
        """
        Non-blocking bridge availability check for tools/list.

        Does NOT trigger lazy WardenBridge initialization.
        If bridge is already initialized, report its actual status.
        If not yet initialized, return True optimistically so all tools
        are visible — bridge availability is verified at execution time.
        """
        # Check _bridge_adapter without triggering lazy init
        bridge_adapter = self._bridge_adapter
        if getattr(bridge_adapter, "_bridge_initialized", False):
            return getattr(bridge_adapter, "_bridge", None) is not None
        # Check adapters that have already initialized their bridge
        for adapter in self._adapters:
            if getattr(adapter, "_bridge_initialized", False):
                if getattr(adapter, "_bridge", None) is not None:
                    return True
        # Not yet checked — optimistically return True.
        # Bridge-requiring tools will check availability at execution time.
        return True

    @property
    def registry(self) -> ToolRegistry:
        """Get the tool registry."""
        return self._registry

    async def execute_async(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Execute a tool by name.

        Routing priority:
        1. Check registered adapters first (new DDD adapters)
        2. Fall back to built-in tools (warden_status, warden_list_reports)
        3. Fall back to legacy bridge adapter

        Args:
            tool_name: Name of tool to execute
            arguments: Tool arguments

        Returns:
            Tool result in MCP format
        """
        tool = self._registry.get(tool_name)
        if not tool:
            raise MCPToolNotFoundError(tool_name)

        try:
            # 1. Try to find a registered adapter that supports this tool
            adapter = self._find_adapter_for_tool(tool_name)
            if adapter:
                # Only check bridge availability if the tool actually needs it.
                # Skipping this for bridge-free tools (health, config) avoids
                # the 5-6s blocking WardenBridge init on every status call.
                if tool.requires_bridge:
                    import asyncio

                    loop = asyncio.get_running_loop()
                    is_avail = await loop.run_in_executor(None, lambda: adapter.is_available)
                    if not is_avail:
                        return MCPToolResult.error(f"Adapter for {tool_name} not available").to_dict()
                result = await adapter.execute_async(tool, arguments)
                return result.to_dict()

            # 2. Try built-in tools (no bridge required)
            if not tool.requires_bridge:
                result = await self._execute_builtin_async(tool_name, arguments)
                return result.to_dict()

            # 3. Fall back to legacy bridge adapter
            if self._bridge_adapter.supports(tool_name):
                import asyncio

                loop = asyncio.get_running_loop()
                is_avail = await loop.run_in_executor(None, lambda: self._bridge_adapter.is_available)
                if not is_avail:
                    return MCPToolResult.error("Warden bridge not available").to_dict()
                result = await self._bridge_adapter.execute_async(tool, arguments)
                return result.to_dict()

            # No executor found
            raise MCPToolExecutionError(
                tool_name,
                f"No executor found for tool: {tool_name}",
            )

        except MCPToolExecutionError as e:
            logger.error("tool_execution_failed", tool=tool_name, error=str(e))
            return MCPToolResult.error(str(e)).to_dict()
        except Exception as e:
            logger.error("tool_execution_error", tool=tool_name, error=str(e))
            return MCPToolResult.error(f"Tool execution error: {e}").to_dict()

    async def _execute_builtin_async(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> MCPToolResult:
        """
        Execute built-in (non-bridge) tools.

        Args:
            tool_name: Tool name
            arguments: Tool arguments

        Returns:
            Tool result
        """
        if tool_name == "warden_status":
            return await self._tool_status_async()
        elif tool_name == "warden_list_reports":
            return await self._tool_list_reports_async()
        else:
            raise MCPToolExecutionError(tool_name, "Unknown built-in tool")

    async def _tool_status_async(self) -> MCPToolResult:
        """Get Warden status."""
        status_file = self.project_root / ".warden" / "ai_status.md"

        if status_file.exists():
            content = status_file.read_text(encoding="utf-8")
            return MCPToolResult.success(content)
        else:
            return MCPToolResult.success("Warden status file not found. Run 'warden scan' first.")

    async def _tool_list_reports_async(self) -> MCPToolResult:
        """List all available reports."""
        reports = self._resource_repo.list_all_reports()

        if not reports:
            return MCPToolResult.success("No reports found. Run 'warden scan' to generate reports.")

        text = "Available Warden Reports:\n\n"
        for report in reports:
            size_kb = report["size"] / 1024
            text += f"- {report['name']} ({size_kb:.1f} KB)\n"
            text += f"  Path: {report['path']}\n"
            text += f"  Type: {report['mime_type']}\n\n"

        return MCPToolResult.success(text)
