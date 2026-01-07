"""
MCP Resource Manager

Manages Warden report resources for MCP protocol.
Exposes validation reports, configuration, and status files.
"""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass

from warden.mcp.protocol import MCPResource, MCPResourceContent, MCPErrorCode


@dataclass
class ResourceDefinition:
    """Internal resource definition."""
    uri: str
    name: str
    description: str
    mime_type: str
    file_path: str  # Relative to project root


# Standard Warden resources
WARDEN_RESOURCES: List[ResourceDefinition] = [
    ResourceDefinition(
        uri="warden://reports/sarif",
        name="SARIF Report",
        description="Warden scan results in SARIF format (GitHub/CI compatible)",
        mime_type="application/json",
        file_path=".warden/reports/warden-report.sarif",
    ),
    ResourceDefinition(
        uri="warden://reports/json",
        name="JSON Report",
        description="Warden scan results in JSON format",
        mime_type="application/json",
        file_path=".warden/reports/warden-report.json",
    ),
    ResourceDefinition(
        uri="warden://reports/html",
        name="HTML Report",
        description="Warden scan results in HTML format (visual report)",
        mime_type="text/html",
        file_path=".warden/reports/warden-report.html",
    ),
    ResourceDefinition(
        uri="warden://config",
        name="Warden Configuration",
        description="Warden pipeline configuration (.warden/config.yaml)",
        mime_type="application/x-yaml",
        file_path=".warden/config.yaml",
    ),
    ResourceDefinition(
        uri="warden://ai-status",
        name="AI Security Status",
        description="Warden AI security status summary",
        mime_type="text/markdown",
        file_path=".warden/ai_status.md",
    ),
    ResourceDefinition(
        uri="warden://rules",
        name="Validation Rules",
        description="Custom validation rules (.warden/rules.yaml)",
        mime_type="application/x-yaml",
        file_path=".warden/rules.yaml",
    ),
]


class MCPResourceManager:
    """
    Manages MCP resources for Warden.

    Provides resource discovery and content retrieval
    for Warden reports and configuration files.
    """

    def __init__(self, project_root: Path):
        """
        Initialize resource manager.

        Args:
            project_root: Root directory of the Warden project
        """
        self.project_root = project_root
        self._resource_definitions = {r.uri: r for r in WARDEN_RESOURCES}

    def list_resources(self) -> List[MCPResource]:
        """
        List all available resources.

        Only returns resources that actually exist on disk.
        """
        resources = []

        for defn in WARDEN_RESOURCES:
            full_path = self.project_root / defn.file_path
            if full_path.exists():
                resources.append(
                    MCPResource(
                        uri=defn.uri,
                        name=defn.name,
                        description=defn.description,
                        mime_type=defn.mime_type,
                    )
                )

        return resources

    def read_resource(self, uri: str) -> MCPResourceContent:
        """
        Read resource content by URI.

        Args:
            uri: Resource URI (e.g., "warden://reports/sarif")

        Returns:
            MCPResourceContent with the file contents

        Raises:
            ValueError: If resource not found or file doesn't exist
        """
        defn = self._resource_definitions.get(uri)

        if defn is None:
            raise ValueError(f"Unknown resource URI: {uri}")

        full_path = self.project_root / defn.file_path

        if not full_path.exists():
            raise ValueError(f"Resource file not found: {defn.file_path}")

        # Read file content
        try:
            content = full_path.read_text(encoding="utf-8")
        except Exception as e:
            raise ValueError(f"Failed to read resource: {e}")

        return MCPResourceContent(
            uri=uri,
            mime_type=defn.mime_type,
            text=content,
        )

    def get_resource_info(self, uri: str) -> Optional[ResourceDefinition]:
        """Get resource definition by URI."""
        return self._resource_definitions.get(uri)

    def resource_exists(self, uri: str) -> bool:
        """Check if a resource exists."""
        defn = self._resource_definitions.get(uri)
        if defn is None:
            return False
        full_path = self.project_root / defn.file_path
        return full_path.exists()

    def get_reports_dir(self) -> Path:
        """Get the reports directory path."""
        return self.project_root / ".warden" / "reports"

    def list_all_reports(self) -> List[Dict[str, Any]]:
        """
        List all report files in the reports directory.

        Returns additional reports beyond the standard ones.
        """
        reports_dir = self.get_reports_dir()
        if not reports_dir.exists():
            return []

        reports = []
        for file_path in reports_dir.iterdir():
            if file_path.is_file():
                # Determine mime type from extension
                ext = file_path.suffix.lower()
                mime_types = {
                    ".json": "application/json",
                    ".sarif": "application/json",
                    ".html": "text/html",
                    ".xml": "application/xml",
                    ".pdf": "application/pdf",
                    ".md": "text/markdown",
                }
                mime_type = mime_types.get(ext, "application/octet-stream")

                reports.append({
                    "name": file_path.name,
                    "path": str(file_path.relative_to(self.project_root)),
                    "size": file_path.stat().st_size,
                    "modified": file_path.stat().st_mtime,
                    "mime_type": mime_type,
                })

        return reports
