"""
MCP Domain Enums

Protocol-defined status codes and type classifications.
Following project conventions: IntEnum for status codes, str Enum for categories.
"""

from enum import IntEnum, Enum


class MCPErrorCode(IntEnum):
    """
    MCP-specific error codes (JSON-RPC 2.0 compatible).

    Standard JSON-RPC errors: -32700 to -32600
    MCP-specific errors: -32001 to -32099
    """
    # Standard JSON-RPC errors
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603

    # MCP-specific errors
    RESOURCE_NOT_FOUND = -32001
    TOOL_NOT_FOUND = -32002
    TOOL_EXECUTION_ERROR = -32003
    SESSION_NOT_INITIALIZED = -32004
    TRANSPORT_ERROR = -32005


class ServerStatus(str, Enum):
    """
    MCP server lifecycle status.

    Tracks the server state from initialization to shutdown.
    """
    INITIALIZING = "initializing"
    READY = "ready"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


class MessageType(str, Enum):
    """
    MCP message types per JSON-RPC 2.0.
    """
    REQUEST = "request"
    RESPONSE = "response"
    NOTIFICATION = "notification"


class ResourceType(str, Enum):
    """
    Warden resource types exposed via MCP.

    Categories for different report and configuration resources.
    """
    REPORT_SARIF = "report_sarif"
    REPORT_JSON = "report_json"
    REPORT_HTML = "report_html"
    CONFIG = "config"
    STATUS = "status"
    RULES = "rules"


class ToolCategory(str, Enum):
    """
    Tool categorization for discovery and organization.

    Helps clients understand tool capabilities.
    Maps to gRPC servicer mixin categories for full feature parity.
    """
    # Core categories (existing)
    STATUS = "status"
    SCAN = "scan"
    CONFIG = "config"
    REPORT = "report"

    # Extended categories (gRPC parity)
    PIPELINE = "pipeline"          # Pipeline execution
    SEARCH = "search"              # Semantic code search
    LLM = "llm"                    # LLM operations
    ISSUE = "issue"                # Issue management
    DISCOVERY = "discovery"        # File discovery
    ANALYSIS = "analysis"          # Result analysis
    CLEANUP = "cleanup"            # Code cleanup
    FORTIFICATION = "fortification"  # Security fortification
    SUPPRESSION = "suppression"    # Suppression rules
