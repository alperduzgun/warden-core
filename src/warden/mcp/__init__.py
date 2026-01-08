"""
Warden MCP (Model Context Protocol) Server Module

Exposes Warden's validation reports and capabilities to AI assistants
via the Model Context Protocol (MCP) over STDIO transport.

Usage:
    warden serve mcp
    python -m warden.mcp.entry

Resources exposed:
    - warden://reports/sarif    - SARIF format scan results
    - warden://reports/json     - JSON format scan results
    - warden://reports/html     - HTML format scan results
    - warden://config           - Warden configuration
    - warden://ai-status        - AI security status

Tools exposed:
    - warden_scan              - Run security scan
    - warden_status            - Get Warden status
    - warden_list_reports      - List available reports
    - warden_get_config        - Get configuration
    - warden_list_frames       - List validation frames

Architecture (DDD):
    - domain/       - Pure business logic, entities, value objects
    - application/  - Application services, use cases
    - infrastructure/ - External integrations, repositories
    - ports/        - Abstract interfaces
"""

# Backward compatible exports (original API)
from warden.mcp.server import MCPServer
from warden.mcp.resources import MCPResourceManager
from warden.mcp.protocol import MCPProtocol

# New DDD API exports
from warden.mcp.application.mcp_service import MCPService
from warden.mcp.domain.models import MCPSession, MCPToolDefinition, MCPResourceDefinition
from warden.mcp.domain.enums import ServerStatus, MCPErrorCode, ToolCategory, ResourceType
from warden.mcp.infrastructure.stdio_transport import STDIOTransport
from warden.mcp.infrastructure.tool_registry import ToolRegistry

__all__ = [
    # Backward compatible (original API)
    "MCPServer",
    "MCPResourceManager",
    "MCPProtocol",
    # New DDD API
    "MCPService",
    "MCPSession",
    "MCPToolDefinition",
    "MCPResourceDefinition",
    "ServerStatus",
    "MCPErrorCode",
    "ToolCategory",
    "ResourceType",
    "STDIOTransport",
    "ToolRegistry",
]
