"""
Report Generation Adapter

MCP adapter for report generation tools.
Maps to gRPC ReportGenerationMixin functionality.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
import uuid

from warden.mcp.infrastructure.adapters.base_adapter import BaseWardenAdapter
from warden.mcp.domain.models import MCPToolDefinition, MCPToolResult
from warden.mcp.domain.enums import ToolCategory


class ReportAdapter(BaseWardenAdapter):
    """
    Adapter for report generation tools.

    Tools:
        - warden_generate_html_report: Generate HTML report
        - warden_generate_pdf_report: Generate PDF report
        - warden_generate_json_report: Generate JSON report
        - warden_get_report_status: Get report status
    """

    SUPPORTED_TOOLS = frozenset({
        "warden_generate_html_report",
        "warden_generate_pdf_report",
        "warden_generate_json_report",
        "warden_get_report_status",
    })
    TOOL_CATEGORY = ToolCategory.REPORT

    def __init__(self, project_root: Path, bridge: Any = None) -> None:
        """Initialize report adapter."""
        super().__init__(project_root, bridge)
        self._report_status: Dict[str, Dict[str, Any]] = {}

    def get_tool_definitions(self) -> List[MCPToolDefinition]:
        """Get report tool definitions."""
        return [
            self._create_tool_definition(
                name="warden_generate_html_report",
                description="Generate HTML report from pipeline results",
                properties={
                    "run_id": {
                        "type": "string",
                        "description": "Pipeline run ID",
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Output file path",
                    },
                    "project_name": {
                        "type": "string",
                        "description": "Project name for report header",
                    },
                    "branch": {
                        "type": "string",
                        "description": "Git branch name",
                    },
                },
            ),
            self._create_tool_definition(
                name="warden_generate_pdf_report",
                description="Generate PDF report from pipeline results",
                properties={
                    "run_id": {
                        "type": "string",
                        "description": "Pipeline run ID",
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Output file path",
                    },
                },
            ),
            self._create_tool_definition(
                name="warden_generate_json_report",
                description="Generate JSON report from pipeline results",
                properties={
                    "run_id": {
                        "type": "string",
                        "description": "Pipeline run ID",
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Output file path",
                    },
                    "project_name": {
                        "type": "string",
                        "description": "Project name",
                    },
                    "branch": {
                        "type": "string",
                        "description": "Git branch",
                    },
                    "commit_hash": {
                        "type": "string",
                        "description": "Git commit hash",
                    },
                },
            ),
            self._create_tool_definition(
                name="warden_get_report_status",
                description="Get report generation status",
                properties={
                    "report_id": {
                        "type": "string",
                        "description": "Report ID",
                    },
                },
                required=["report_id"],
            ),
        ]

    async def _execute_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> MCPToolResult:
        """Execute report tool."""
        handlers = {
            "warden_generate_html_report": self._generate_html_report,
            "warden_generate_pdf_report": self._generate_pdf_report,
            "warden_generate_json_report": self._generate_json_report,
            "warden_get_report_status": self._get_report_status,
        }

        handler = handlers.get(tool_name)
        if handler:
            return await handler(arguments)
        return MCPToolResult.error(f"Unknown tool: {tool_name}")

    async def _generate_html_report(self, arguments: Dict[str, Any]) -> MCPToolResult:
        """Generate HTML report."""
        run_id = arguments.get("run_id", str(uuid.uuid4()))
        output_path = arguments.get("output_path")
        project_name = arguments.get("project_name", "Warden Report")
        branch = arguments.get("branch", "main")

        if not output_path:
            output_path = str(self.project_root / ".warden" / f"report_{run_id}.html")

        report_id = str(uuid.uuid4())

        try:
            # Try bridge method first
            if self.bridge and hasattr(self.bridge, "generate_html_report"):
                result = await self.bridge.generate_html_report(run_id, output_path)
                return MCPToolResult.json_result(result)

            # Fallback: generate basic HTML report
            html_content = self._generate_basic_html(project_name, branch, run_id)

            # Write report
            output = Path(output_path)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(html_content, encoding="utf-8")

            self._report_status[report_id] = {
                "status": "completed",
                "file_path": str(output),
                "progress": 100,
            }

            return MCPToolResult.json_result({
                "success": True,
                "report_id": report_id,
                "file_path": str(output),
                "size_bytes": output.stat().st_size,
            })
        except Exception as e:
            return MCPToolResult.error(f"HTML report generation failed: {e}")

    async def _generate_pdf_report(self, arguments: Dict[str, Any]) -> MCPToolResult:
        """Generate PDF report."""
        run_id = arguments.get("run_id", str(uuid.uuid4()))
        output_path = arguments.get("output_path")

        if not output_path:
            output_path = str(self.project_root / ".warden" / f"report_{run_id}.pdf")

        report_id = str(uuid.uuid4())

        try:
            # Try bridge method first
            if self.bridge and hasattr(self.bridge, "generate_pdf_report"):
                result = await self.bridge.generate_pdf_report(run_id, output_path)
                return MCPToolResult.json_result(result)

            # PDF generation typically requires wkhtmltopdf
            return MCPToolResult.error(
                "PDF generation requires wkhtmltopdf. "
                "Use warden_generate_html_report instead."
            )
        except Exception as e:
            return MCPToolResult.error(f"PDF report generation failed: {e}")

    async def _generate_json_report(self, arguments: Dict[str, Any]) -> MCPToolResult:
        """Generate JSON report."""
        run_id = arguments.get("run_id", str(uuid.uuid4()))
        output_path = arguments.get("output_path")
        project_name = arguments.get("project_name", "Warden Report")
        branch = arguments.get("branch", "main")
        commit_hash = arguments.get("commit_hash", "")

        if not output_path:
            output_path = str(self.project_root / ".warden" / f"report_{run_id}.json")

        report_id = str(uuid.uuid4())

        try:
            # Generate JSON report
            report_data = {
                "report_id": report_id,
                "run_id": run_id,
                "generated_at": datetime.utcnow().isoformat(),
                "project_name": project_name,
                "branch": branch,
                "commit_hash": commit_hash,
                "issues": [],  # Would be populated from actual results
                "summary": {
                    "critical": 0,
                    "high": 0,
                    "medium": 0,
                    "low": 0,
                    "info": 0,
                },
            }

            # Write report
            output = Path(output_path)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report_data, indent=2), encoding="utf-8")

            self._report_status[report_id] = {
                "status": "completed",
                "file_path": str(output),
                "progress": 100,
            }

            return MCPToolResult.json_result({
                "success": True,
                "report_id": report_id,
                "file_path": str(output),
                "size_bytes": output.stat().st_size,
                "content": report_data,
            })
        except Exception as e:
            return MCPToolResult.error(f"JSON report generation failed: {e}")

    async def _get_report_status(self, arguments: Dict[str, Any]) -> MCPToolResult:
        """Get report generation status."""
        report_id = arguments.get("report_id")

        if not report_id:
            return MCPToolResult.error("Missing required parameter: report_id")

        status = self._report_status.get(report_id)

        if not status:
            return MCPToolResult.error(f"Report not found: {report_id}")

        return MCPToolResult.json_result({
            "report_id": report_id,
            **status,
        })

    def _generate_basic_html(self, project_name: str, branch: str, run_id: str) -> str:
        """Generate basic HTML report."""
        return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>{project_name} - Warden Report</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 40px; }}
        h1 {{ color: #1a1a1a; }}
        .metadata {{ color: #666; margin-bottom: 20px; }}
        .summary {{ background: #f5f5f5; padding: 20px; border-radius: 8px; }}
    </style>
</head>
<body>
    <h1>{project_name}</h1>
    <div class="metadata">
        <p>Branch: {branch}</p>
        <p>Run ID: {run_id}</p>
        <p>Generated: {datetime.utcnow().isoformat()}</p>
    </div>
    <div class="summary">
        <h2>Summary</h2>
        <p>Report generated by Warden MCP Server</p>
    </div>
</body>
</html>"""
