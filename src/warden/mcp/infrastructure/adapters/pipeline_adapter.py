"""
Pipeline Adapter

MCP adapter for pipeline execution tools.
Maps to gRPC PipelineMixin functionality.
"""

from typing import Any

from warden.mcp.domain.enums import ToolCategory
from warden.mcp.domain.models import MCPToolDefinition, MCPToolResult
from warden.mcp.infrastructure.adapters.base_adapter import BaseWardenAdapter
from warden.shared.utils.path_utils import sanitize_path
from warden.shared.utils.retry_utils import async_retry


class PipelineAdapter(BaseWardenAdapter):
    """
    Adapter for pipeline execution tools.

    Tools:
        - warden_execute_pipeline: Execute full validation pipeline
        - warden_execute_pipeline_stream: Execute pipeline with streaming
    """

    SUPPORTED_TOOLS = frozenset(
        {
            "warden_execute_pipeline",
            "warden_execute_pipeline_stream",
        }
    )
    TOOL_CATEGORY = ToolCategory.PIPELINE

    def get_tool_definitions(self) -> list[MCPToolDefinition]:
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

    async def _execute_tool_async(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> MCPToolResult:
        """Execute pipeline tool."""
        if tool_name == "warden_execute_pipeline":
            return await self._execute_pipeline_async(arguments)
        elif tool_name == "warden_execute_pipeline_stream":
            return await self._execute_pipeline_stream_async(arguments)
        else:
            return MCPToolResult.error(f"Unknown tool: {tool_name}")

    @async_retry(retries=5, initial_delay=1.0)
    async def _execute_pipeline_async(self, arguments: dict[str, Any]) -> MCPToolResult:
        """Execute full validation pipeline."""
        path = arguments.get("path", str(self.project_root))
        frames = arguments.get("frames")

        if not self.bridge:
            raise RuntimeError("Warden bridge not available")

        try:
            safe_path = sanitize_path(path, self.project_root)
            result = await self.bridge.execute_pipeline_async(
                file_path=str(safe_path),
                frames=frames,
            )
            # Validate pipeline completion before returning (#158).
            # PipelineStatus.COMPLETED=2, COMPLETED_WITH_FAILURES=5 are the only
            # states where findings and frame_results are meaningful.
            _COMPLETE_STATUSES = {2, 5}
            pipeline_status = result.get("status") if isinstance(result, dict) else None
            if pipeline_status is not None and pipeline_status not in _COMPLETE_STATUSES:
                return MCPToolResult.error(
                    f"Pipeline did not complete (status={pipeline_status}). "
                    "Results may be partial or empty — retry the scan."
                )
            return MCPToolResult.json_result(result)
        except ValueError as e:
            return MCPToolResult.error(f"Path validation failed: {e}")
        except Exception as e:
            return MCPToolResult.error(f"Pipeline execution failed: {e}")

    @async_retry(retries=5, initial_delay=1.0)
    async def _execute_pipeline_stream_async(self, arguments: dict[str, Any]) -> MCPToolResult:
        """Execute pipeline with streaming (collect all events)."""
        path = arguments.get("path", str(self.project_root))
        frames = arguments.get("frames")
        verbose = arguments.get("verbose", False)

        if not self.bridge:
            raise RuntimeError("Warden bridge not available")

        try:
            safe_path = sanitize_path(path, self.project_root)
            # Collect all streaming events
            events = []
            final_result = None

            async for event in self.bridge.execute_pipeline_stream_async(
                file_path=str(safe_path),
                frames=frames,
                verbose=verbose,
            ):
                if event.get("type") == "result":
                    final_result = event.get("data")
                else:
                    events.append(event)

            return MCPToolResult.json_result(
                {
                    "events": events,
                    "result": final_result,
                    "event_count": len(events),
                }
            )
        except Exception as e:
            return MCPToolResult.error(f"Pipeline stream failed: {e}")
