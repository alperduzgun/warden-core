"""
Warden MCP (Model Context Protocol) Server Module

Exposes Warden's validation reports and capabilities to AI assistants
via the Model Context Protocol (MCP) over STDIO transport.

Usage:
    warden serve mcp
    python -m warden.services.mcp_entry

Resources exposed:
    - warden://reports/sarif    - SARIF format scan results
    - warden://reports/json     - JSON format scan results
    - warden://reports/html     - HTML format scan results
    - warden://config           - Warden configuration
    - warden://ai-status        - AI security status

Tools exposed:
    - warden_scan              - Run security scan
    - warden_status            - Get Warden status
    - warden_generate_report   - Generate report in specific format
"""

from warden.mcp.server import MCPServer
from warden.mcp.resources import MCPResourceManager
from warden.mcp.protocol import MCPProtocol

__all__ = ["MCPServer", "MCPResourceManager", "MCPProtocol"]
