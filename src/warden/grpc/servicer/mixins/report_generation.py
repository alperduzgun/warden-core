"""
Report Generation Mixin

Endpoints: GenerateHtmlReport, GeneratePdfReport, GenerateJsonReport, GetReportStatus
"""

import json
import uuid
from datetime import datetime
from pathlib import Path

try:
    from warden.grpc.generated import warden_pb2
except ImportError:
    warden_pb2 = None

try:
    from warden.shared.infrastructure.logging import get_logger
    logger = get_logger(__name__)
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


class ReportGenerationMixin:
    """Report generation endpoints (4 endpoints)."""

    async def GenerateHtmlReport(self, request, context) -> "warden_pb2.ReportResponse":
        """Generate HTML report."""
        logger.info("grpc_generate_html_report", run_id=request.run_id)

        try:
            report_id = str(uuid.uuid4())

            if hasattr(self.bridge, 'generate_html_report'):
                result = await self.bridge.generate_html_report(
                    run_id=request.run_id,
                    output_path=request.output_path
                )
                return warden_pb2.ReportResponse(
                    success=True,
                    report_id=report_id,
                    file_path=result.get("file_path", ""),
                    size_bytes=result.get("size_bytes", 0)
                )

            html_content = self._generate_simple_html_report(request)
            output_path = request.output_path or f"/tmp/warden_report_{report_id}.html"

            Path(output_path).write_text(html_content)

            return warden_pb2.ReportResponse(
                success=True,
                report_id=report_id,
                file_path=output_path,
                size_bytes=len(html_content.encode())
            )

        except Exception as e:
            logger.error("grpc_generate_html_error: %s", str(e))
            return warden_pb2.ReportResponse(
                success=False,
                error_message=str(e)
            )

    async def GeneratePdfReport(self, request, context) -> "warden_pb2.ReportResponse":
        """Generate PDF report."""
        logger.info("grpc_generate_pdf_report", run_id=request.run_id)

        try:
            report_id = str(uuid.uuid4())

            if hasattr(self.bridge, 'generate_pdf_report'):
                result = await self.bridge.generate_pdf_report(
                    run_id=request.run_id,
                    output_path=request.output_path
                )
                return warden_pb2.ReportResponse(
                    success=True,
                    report_id=report_id,
                    file_path=result.get("file_path", ""),
                    size_bytes=result.get("size_bytes", 0)
                )

            return warden_pb2.ReportResponse(
                success=False,
                report_id=report_id,
                error_message="PDF generation not available. Install wkhtmltopdf."
            )

        except Exception as e:
            logger.error("grpc_generate_pdf_error: %s", str(e))
            return warden_pb2.ReportResponse(
                success=False,
                error_message=str(e)
            )

    async def GenerateJsonReport(self, request, context) -> "warden_pb2.ReportResponse":
        """Generate JSON report."""
        logger.info("grpc_generate_json_report", run_id=request.run_id)

        try:
            report_id = str(uuid.uuid4())

            report_data = {
                "report_id": report_id,
                "run_id": request.run_id,
                "generated_at": datetime.now().isoformat(),
                "project_name": request.project_name,
                "branch": request.branch,
                "commit_hash": request.commit_hash,
                "issues": list(self._issues.values()),
                "summary": {
                    "total_issues": len(self._issues),
                    "critical": sum(
                        1 for i in self._issues.values()
                        if i.get("severity") == "critical"
                    ),
                    "high": sum(
                        1 for i in self._issues.values()
                        if i.get("severity") == "high"
                    ),
                    "medium": sum(
                        1 for i in self._issues.values()
                        if i.get("severity") == "medium"
                    ),
                    "low": sum(
                        1 for i in self._issues.values()
                        if i.get("severity") == "low"
                    )
                }
            }

            json_content = json.dumps(report_data, indent=2)

            if request.output_path:
                Path(request.output_path).write_text(json_content)

            return warden_pb2.ReportResponse(
                success=True,
                report_id=report_id,
                file_path=request.output_path or "",
                content=json_content,
                size_bytes=len(json_content.encode())
            )

        except Exception as e:
            logger.error("grpc_generate_json_error: %s", str(e))
            return warden_pb2.ReportResponse(
                success=False,
                error_message=str(e)
            )

    async def GetReportStatus(self, request, context) -> "warden_pb2.ReportStatusResponse":
        """Get report generation status."""
        logger.info("grpc_get_report_status", report_id=request.report_id)

        try:
            status = self._report_status.get(request.report_id, {})

            return warden_pb2.ReportStatusResponse(
                report_id=request.report_id,
                status=status.get("status", "not_found"),
                progress=status.get("progress", 0.0),
                file_path=status.get("file_path", ""),
                error_message=status.get("error", "")
            )

        except Exception as e:
            logger.error("grpc_get_report_status_error: %s", str(e))
            return warden_pb2.ReportStatusResponse(
                report_id=request.report_id,
                status="error",
                error_message=str(e)
            )

    def _generate_simple_html_report(self, request) -> str:
        """Generate a simple HTML report."""
        issues = list(self._issues.values())

        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Warden Security Report - {request.project_name or 'Project'}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        h1 {{ color: #333; }}
        .summary {{ background: #f5f5f5; padding: 15px; border-radius: 5px; }}
        .critical {{ color: #d32f2f; }}
        .high {{ color: #f57c00; }}
        .medium {{ color: #fbc02d; }}
        .low {{ color: #388e3c; }}
        table {{ border-collapse: collapse; width: 100%; margin-top: 20px; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background: #333; color: white; }}
    </style>
</head>
<body>
    <h1>Warden Security Report</h1>
    <div class="summary">
        <h2>Summary</h2>
        <p><strong>Project:</strong> {request.project_name or 'N/A'}</p>
        <p><strong>Branch:</strong> {request.branch or 'N/A'}</p>
        <p><strong>Generated:</strong> {datetime.now().isoformat()}</p>
        <p><strong>Total Issues:</strong> {len(issues)}</p>
        <p class="critical"><strong>Critical:</strong> {sum(1 for i in issues if i.get('severity') == 'critical')}</p>
        <p class="high"><strong>High:</strong> {sum(1 for i in issues if i.get('severity') == 'high')}</p>
        <p class="medium"><strong>Medium:</strong> {sum(1 for i in issues if i.get('severity') == 'medium')}</p>
        <p class="low"><strong>Low:</strong> {sum(1 for i in issues if i.get('severity') == 'low')}</p>
    </div>

    <h2>Issues</h2>
    <table>
        <tr>
            <th>Severity</th>
            <th>Title</th>
            <th>File</th>
            <th>Line</th>
            <th>Status</th>
        </tr>
"""

        for issue in issues:
            severity = issue.get('severity', 'medium')
            html += f"""        <tr>
            <td class="{severity}">{severity.upper()}</td>
            <td>{issue.get('title', '')}</td>
            <td>{issue.get('file_path', '')}</td>
            <td>{issue.get('line_number', 0)}</td>
            <td>{issue.get('state', 'open')}</td>
        </tr>
"""

        html += """    </table>
</body>
</html>"""

        return html
