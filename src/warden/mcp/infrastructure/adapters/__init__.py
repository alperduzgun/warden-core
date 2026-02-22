"""
MCP Tool Adapters

Specialized adapters for exposing Warden functionality via MCP tools.
Each adapter handles a specific domain (pipeline, search, issues, etc.)
and implements the IToolExecutor interface.

Architecture:
    - BaseWardenAdapter: Abstract base with common patterns
    - *Adapter: Specialized adapters for each tool category
    - All adapters connect to WardenBridge for backend operations

Total: 12 adapters exposing 51 tools
"""

from warden.mcp.infrastructure.adapters.analysis_adapter import AnalysisAdapter
from warden.mcp.infrastructure.adapters.audit_adapter import AuditAdapter
from warden.mcp.infrastructure.adapters.base_adapter import BaseWardenAdapter

# CI/CD adapter
from warden.mcp.infrastructure.adapters.ci_adapter import CIAdapter
from warden.mcp.infrastructure.adapters.cleanup_adapter import CleanupAdapter
from warden.mcp.infrastructure.adapters.config_adapter import ConfigAdapter

# Discovery & Analysis adapters
from warden.mcp.infrastructure.adapters.discovery_adapter import DiscoveryAdapter
from warden.mcp.infrastructure.adapters.fortification_adapter import FortificationAdapter
from warden.mcp.infrastructure.adapters.health_adapter import HealthAdapter

# Issue & Suppression adapters
from warden.mcp.infrastructure.adapters.issue_adapter import IssueAdapter
from warden.mcp.infrastructure.adapters.llm_adapter import LlmAdapter

# Core adapters
from warden.mcp.infrastructure.adapters.pipeline_adapter import PipelineAdapter

# Report, Cleanup, Fortification adapters
from warden.mcp.infrastructure.adapters.report_adapter import ReportAdapter

# Search & LLM adapters
from warden.mcp.infrastructure.adapters.search_adapter import SearchAdapter
from warden.mcp.infrastructure.adapters.suppression_adapter import SuppressionAdapter

__all__ = [
    # Base
    "BaseWardenAdapter",
    # Core (9 tools)
    "PipelineAdapter",
    "ConfigAdapter",
    "HealthAdapter",
    # Issue & Suppression (12 tools)
    "IssueAdapter",
    "SuppressionAdapter",
    # Search & LLM (11 tools)
    "SearchAdapter",
    "LlmAdapter",
    # Discovery & Analysis (9 tools)
    "DiscoveryAdapter",
    "AnalysisAdapter",
    # Report, Cleanup, Fortification (10 tools)
    "ReportAdapter",
    "CleanupAdapter",
    "FortificationAdapter",
    # CI/CD (4 tools)
    "CIAdapter",
    # Audit (2 tools)
    "AuditAdapter",
]
