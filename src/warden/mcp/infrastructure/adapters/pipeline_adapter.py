"""
Pipeline Adapter

MCP adapter for pipeline execution tools.
Maps to gRPC PipelineMixin functionality.
"""

from pathlib import Path
from typing import Any, Dict, List

from warden.mcp.infrastructure.adapters.base_adapter import BaseWardenAdapter
from warden.mcp.domain.models import MCPToolDefinition, MCPToolResult
from warden.mcp.domain.enums import ToolCategory


class PipelineAdapter(BaseWardenAdapter):
    """
    Adapter for pipeline execution tools.

    Tools:
        - warden_execute_pipeline: Execute full validation pipeline
        - warden_execute_pipeline_stream: Execute pipeline with streaming
    """

    SUPPORTED_TOOLS = frozenset({
        "warden_execute_pipeline",
        "warden_execute_pipeline_stream",
    })
    TOOL_CATEGORY = ToolCategory.PIPELINE

    def get_tool_definitions(self) -> List[MCPToolDefinition]:
        """Get pipeline tool definitions."""
        return [
            self._create_tool_definition(
                name="warden_execute_pipeline",
                description="Execute full validation pipeline on a file or directory",
                properties={
                    "path": {
                        "type": "string",
                        "description": "Path to file or directory to validate (default: project root)",
                    },
                    "frames": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Specific frames to run (default: all configured frames)",
                    },
                },
            ),
            self._create_tool_definition(
                name="warden_execute_pipeline_stream",
                description="Execute pipeline with progress events (returns collected events)",
                properties={
                    "path": {
                        "type": "string",
                        "description": "Path to file or directory to validate",
                    },
                    "frames": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Specific frames to run",
                    },
                    "verbose": {
                        "type": "boolean",
                        "description": "Enable verbose logging",
                        "default": False,
                    },
                },
            ),
        ]

    async def _execute_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> MCPToolResult:
        """Execute pipeline tool."""
        if tool_name == "warden_execute_pipeline":
            return await self._execute_pipeline(arguments)
        elif tool_name == "warden_execute_pipeline_stream":
            return await self._execute_pipeline_stream(arguments)
        else:
            return MCPToolResult.error(f"Unknown tool: {tool_name}")

    async def _execute_pipeline(self, arguments: Dict[str, Any]) -> MCPToolResult:
        """Execute full validation pipeline."""
        path = arguments.get("path", str(self.project_root))
        frames = arguments.get("frames")

        if not self.bridge:
            return MCPToolResult.error("Warden bridge not available")

        try:
            result = await self.bridge.execute_pipeline(
                file_path=path,
                frames=frames,
            )
            return MCPToolResult.json_result(result)
        except Exception as e:
            return MCPToolResult.error(f"Pipeline execution failed: {e}")

    async def _execute_pipeline_stream(self, arguments: Dict[str, Any]) -> MCPToolResult:
        """Execute pipeline with streaming (collect all events)."""
        path = arguments.get("path", str(self.project_root))
        frames = arguments.get("frames")
        verbose = arguments.get("verbose", False)

        if not self.bridge:
            return MCPToolResult.error("Warden bridge not available")

        try:
            # Collect all streaming events
            events = []
            final_result = None

            async for event in self.bridge.execute_pipeline_stream(
                file_path=path,
                frames=frames,
                verbose=verbose,
            ):
                if event.get("type") == "result":
                    final_result = event.get("data")
                else:
                    events.append(event)

            return MCPToolResult.json_result({
                "events": events,
                "result": final_result,
                "event_count": len(events),
            })
        except Exception as e:
            return MCPToolResult.error(f"Pipeline stream failed: {e}")
