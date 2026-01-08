"""
File-based Resource Repository

Reads Warden resources from the filesystem.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

from warden.mcp.ports.resource_repository import IResourceRepository
from warden.mcp.domain.models import MCPResourceDefinition
from warden.mcp.domain.enums import ResourceType
from warden.mcp.domain.errors import MCPResourceNotFoundError

# Optional logging
try:
    from warden.shared.infrastructure.logging import get_logger
    logger = get_logger(__name__)
except ImportError:
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)


# Standard Warden resources
WARDEN_RESOURCES: List[MCPResourceDefinition] = [
    MCPResourceDefinition(
        uri="warden://reports/sarif",
        name="SARIF Report",
        description="Warden scan results in SARIF format (GitHub/CI compatible)",
        resource_type=ResourceType.REPORT_SARIF,
        mime_type="application/json",
        file_path=".warden/reports/warden-report.sarif",
    ),
    MCPResourceDefinition(
        uri="warden://reports/json",
        name="JSON Report",
        description="Warden scan results in JSON format",
        resource_type=ResourceType.REPORT_JSON,
        mime_type="application/json",
        file_path=".warden/reports/warden-report.json",
    ),
    MCPResourceDefinition(
        uri="warden://reports/html",
        name="HTML Report",
        description="Warden scan results in HTML format (visual report)",
        resource_type=ResourceType.REPORT_HTML,
        mime_type="text/html",
        file_path=".warden/reports/warden-report.html",
    ),
    MCPResourceDefinition(
        uri="warden://config",
        name="Warden Configuration",
        description="Warden pipeline configuration (.warden/config.yaml)",
        resource_type=ResourceType.CONFIG,
        mime_type="application/x-yaml",
        file_path=".warden/config.yaml",
    ),
    MCPResourceDefinition(
        uri="warden://ai-status",
        name="AI Security Status",
        description="Warden AI security status summary",
        resource_type=ResourceType.STATUS,
        mime_type="text/markdown",
        file_path=".warden/ai_status.md",
    ),
    MCPResourceDefinition(
        uri="warden://rules",
        name="Validation Rules",
        description="Custom validation rules (.warden/rules.yaml)",
        resource_type=ResourceType.RULES,
        mime_type="application/x-yaml",
        file_path=".warden/rules.yaml",
    ),
]


class FileResourceRepository(IResourceRepository):
    """
    File-based resource repository.

    Reads resources from the project's .warden directory.
    """

    def __init__(self, project_root: Path) -> None:
        """
        Initialize repository.

        Args:
            project_root: Project root directory
        """
        self.project_root = project_root
        self._resources: Dict[str, MCPResourceDefinition] = {
            r.uri: r for r in WARDEN_RESOURCES
        }

    async def exists(self, uri: str) -> bool:
        """Check if resource file exists."""
        if uri == "warden://reports/latest":
            return bool(self._find_latest_report())

        resource = self._resources.get(uri)
        if not resource:
            return False
        return (self.project_root / resource.file_path).exists()

    async def get_content(self, uri: str) -> Optional[str]:
        """Read resource content."""
        if uri == "warden://reports/latest":
            report_path = self._find_latest_report()
            if not report_path:
                raise MCPResourceNotFoundError(uri)
            return report_path.read_text(encoding="utf-8")

        resource = self._resources.get(uri)
        if not resource:
            raise MCPResourceNotFoundError(uri)

        full_path = self.project_root / resource.file_path
        if not full_path.exists():
            raise MCPResourceNotFoundError(uri)

        try:
            return full_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.error("resource_read_error", uri=uri, error=str(e))
            raise MCPResourceNotFoundError(uri)

    def _find_latest_report(self) -> Optional[Path]:
        """Find the most recently modified report file."""
        reports_dir = self.get_reports_dir()
        if not reports_dir.exists():
            return None
            
        # Filter for known report types
        report_files = [
            f for f in reports_dir.iterdir() 
            if f.is_file() and f.suffix in {'.json', '.sarif', '.html', '.md'}
        ]
        
        if not report_files:
            return None
            
        # Return newest
        return max(report_files, key=lambda f: f.stat().st_mtime)

    async def list_available(self) -> List[MCPResourceDefinition]:
        """List resources that exist on disk."""
        available = []
        for resource in self._resources.values():
            if await self.exists(resource.uri):
                available.append(resource)
        
        # Add dynamic latest report if available
        latest_path = self._find_latest_report()
        if latest_path:
            available.append(MCPResourceDefinition(
                uri="warden://reports/latest",
                name="Latest Scan Report",
                description="The most recently generated scan report",
                resource_type=ResourceType.REPORT_JSON, # Default to generic report type
                mime_type="application/json" if latest_path.suffix in {'.json', '.sarif'} else "text/plain",
                file_path=str(latest_path.relative_to(self.project_root))
            ))

        return available

    def get_definition(self, uri: str) -> Optional[MCPResourceDefinition]:
        """Get resource definition by URI."""
        return self._resources.get(uri)

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
        mime_types = {
            ".json": "application/json",
            ".sarif": "application/json",
            ".html": "text/html",
            ".xml": "application/xml",
            ".pdf": "application/pdf",
            ".md": "text/markdown",
        }

        for file_path in reports_dir.iterdir():
            if file_path.is_file():
                ext = file_path.suffix.lower()
                reports.append({
                    "name": file_path.name,
                    "path": str(file_path.relative_to(self.project_root)),
                    "size": file_path.stat().st_size,
                    "modified": file_path.stat().st_mtime,
                    "mime_type": mime_types.get(ext, "application/octet-stream"),
                })

        return reports
