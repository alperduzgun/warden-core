"""
Semantic Search Adapter

MCP adapter for semantic code search tools.
Maps to gRPC SemanticSearchMixin functionality.
"""

from pathlib import Path
from typing import Any, Dict, List

from warden.mcp.infrastructure.adapters.base_adapter import BaseWardenAdapter
from warden.mcp.domain.models import MCPToolDefinition, MCPToolResult
from warden.mcp.domain.enums import ToolCategory


class SearchAdapter(BaseWardenAdapter):
    """
    Adapter for semantic search tools.

    Tools:
        - warden_search_code: Semantic code search
        - warden_search_similar_code: Find similar code
        - warden_search_by_description: Natural language search
        - warden_index_project: Index for search
        - warden_get_index_stats: Index statistics
        - warden_clear_index: Clear index
    """

    SUPPORTED_TOOLS = frozenset({
        "warden_search_code",
        "warden_search_similar_code",
        "warden_search_by_description",
        "warden_index_project",
        "warden_get_index_stats",
        "warden_clear_index",
    })
    TOOL_CATEGORY = ToolCategory.SEARCH

    def get_tool_definitions(self) -> List[MCPToolDefinition]:
        """Get search tool definitions."""
        return [
            self._create_tool_definition(
                name="warden_search_code",
                description="Search code using semantic search with embeddings",
                properties={
                    "query": {
                        "type": "string",
                        "description": "Search query",
                    },
                    "language": {
                        "type": "string",
                        "description": "Filter by programming language",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results",
                        "default": 10,
                    },
                },
                required=["query"],
            ),
            self._create_tool_definition(
                name="warden_search_similar_code",
                description="Find similar code using embeddings",
                properties={
                    "code": {
                        "type": "string",
                        "description": "Code snippet to find similar to",
                    },
                    "language": {
                        "type": "string",
                        "description": "Programming language of the code",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results",
                        "default": 10,
                    },
                },
                required=["code"],
            ),
            self._create_tool_definition(
                name="warden_search_by_description",
                description="Search code by natural language description",
                properties={
                    "query": {
                        "type": "string",
                        "description": "Natural language description",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results",
                        "default": 10,
                    },
                },
                required=["query"],
            ),
            self._create_tool_definition(
                name="warden_index_project",
                description="Index project files for semantic search",
                properties={
                    "path": {
                        "type": "string",
                        "description": "Path to index (default: project root)",
                    },
                    "force_reindex": {
                        "type": "boolean",
                        "description": "Force reindex even if up to date",
                        "default": False,
                    },
                    "languages": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Languages to index",
                    },
                },
            ),
            self._create_tool_definition(
                name="warden_get_index_stats",
                description="Get semantic search index statistics",
                properties={},
            ),
            self._create_tool_definition(
                name="warden_clear_index",
                description="Clear semantic search index",
                properties={},
            ),
        ]

    async def _execute_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> MCPToolResult:
        """Execute search tool."""
        handlers = {
            "warden_search_code": self._search_code,
            "warden_search_similar_code": self._search_similar_code,
            "warden_search_by_description": self._search_by_description,
            "warden_index_project": self._index_project,
            "warden_get_index_stats": self._get_index_stats,
            "warden_clear_index": self._clear_index,
        }

        handler = handlers.get(tool_name)
        if handler:
            return await handler(arguments)
        return MCPToolResult.error(f"Unknown tool: {tool_name}")

    async def _search_code(self, arguments: Dict[str, Any]) -> MCPToolResult:
        """Search code using semantic search."""
        query = arguments.get("query")
        language = arguments.get("language")
        limit = arguments.get("limit", 10)

        if not query:
            return MCPToolResult.error("Missing required parameter: query")

        if not self.bridge:
            return MCPToolResult.error("Warden bridge not available")

        try:
            if hasattr(self.bridge, "search_code"):
                result = await self.bridge.search_code(query, language, limit)
                return MCPToolResult.json_result(result)
            else:
                return MCPToolResult.error("Semantic search not available")
        except Exception as e:
            return MCPToolResult.error(f"Search failed: {e}")

    async def _search_similar_code(self, arguments: Dict[str, Any]) -> MCPToolResult:
        """Find similar code."""
        code = arguments.get("code")
        language = arguments.get("language")
        limit = arguments.get("limit", 10)

        if not code:
            return MCPToolResult.error("Missing required parameter: code")

        if not self.bridge:
            return MCPToolResult.error("Warden bridge not available")

        try:
            if hasattr(self.bridge, "search_similar_code"):
                result = await self.bridge.search_similar_code(code, language, limit)
                return MCPToolResult.json_result(result)
            else:
                return MCPToolResult.error("Similar code search not available")
        except Exception as e:
            return MCPToolResult.error(f"Similar search failed: {e}")

    async def _search_by_description(self, arguments: Dict[str, Any]) -> MCPToolResult:
        """Search code by natural language description."""
        query = arguments.get("query")
        limit = arguments.get("limit", 10)

        if not query:
            return MCPToolResult.error("Missing required parameter: query")

        if not self.bridge:
            return MCPToolResult.error("Warden bridge not available")

        try:
            if hasattr(self.bridge, "search_by_description"):
                result = await self.bridge.search_by_description(query, limit)
                return MCPToolResult.json_result(result)
            else:
                # Fall back to regular search
                return await self._search_code(arguments)
        except Exception as e:
            return MCPToolResult.error(f"Description search failed: {e}")

    async def _index_project(self, arguments: Dict[str, Any]) -> MCPToolResult:
        """Index project for semantic search."""
        path = arguments.get("path", str(self.project_root))
        force = arguments.get("force_reindex", False)
        languages = arguments.get("languages")

        if not self.bridge:
            return MCPToolResult.error("Warden bridge not available")

        try:
            if hasattr(self.bridge, "index_project"):
                result = await self.bridge.index_project(path, force, languages)
                return MCPToolResult.json_result(result)
            else:
                return MCPToolResult.error("Project indexing not available")
        except Exception as e:
            return MCPToolResult.error(f"Indexing failed: {e}")

    async def _get_index_stats(self, arguments: Dict[str, Any]) -> MCPToolResult:
        """Get index statistics."""
        if not self.bridge:
            return MCPToolResult.error("Warden bridge not available")

        try:
            if hasattr(self.bridge, "get_index_stats"):
                result = await self.bridge.get_index_stats()
                return MCPToolResult.json_result(result)
            else:
                return MCPToolResult.json_result({
                    "available": False,
                    "message": "Index statistics not available",
                })
        except Exception as e:
            return MCPToolResult.error(f"Failed to get index stats: {e}")

    async def _clear_index(self, arguments: Dict[str, Any]) -> MCPToolResult:
        """Clear semantic search index."""
        if not self.bridge:
            return MCPToolResult.error("Warden bridge not available")

        try:
            if hasattr(self.bridge, "clear_index"):
                await self.bridge.clear_index()
                return MCPToolResult.json_result({
                    "success": True,
                    "message": "Index cleared",
                })
            else:
                return MCPToolResult.error("Index clearing not available")
        except Exception as e:
            return MCPToolResult.error(f"Failed to clear index: {e}")
