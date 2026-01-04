"""Report generator for Warden scan results."""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import json


class ReportGenerator:
    """Generate reports in various formats."""

    def __init__(self):
        """Initialize report generator."""
        self.templates_dir = Path(__file__).parent / "templates"

    def generate_json_report(
        self,
        scan_results: Dict[str, Any],
        output_path: Path
    ) -> None:
        """
        Generate JSON report from scan results.

        Args:
            scan_results: Dictionary containing scan results
            output_path: Path to save the JSON report
        """
        with open(output_path, 'w') as f:
            json.dump(scan_results, f, indent=4)

    def generate_sarif_report(
        self,
        scan_results: Dict[str, Any],
        output_path: Path
    ) -> None:
        """
        Generate SARIF report from scan results for GitHub integration.

        Args:
            scan_results: Dictionary containing scan results
            output_path: Path to save the SARIF report
        """
        # Basic SARIF v2.1.0 structure
        sarif = {
            "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
            "version": "2.1.0",
            "runs": [
                {
                    "tool": {
                        "driver": {
                            "name": "Warden",
                            "semanticVersion": "0.1.0",
                            "informationUri": "https://github.com/alperduzgun/warden-core",
                            "rules": []
                        }
                    },
                    "results": []
                }
            ]
        }

        run = sarif["runs"][0]
        rules_map = {}
        
        # Support both snake_case (CLI) and camelCase (Panel)
        frame_results = scan_results.get('frame_results', scan_results.get('frameResults', []))
        
        for frame in frame_results:
            findings = frame.get('findings', [])
            frame_id = frame.get('frame_id', frame.get('frameId', 'generic'))
            
            for finding in findings:
                # Use finding ID or Fallback to frame ID
                rule_id = finding.get('id', frame_id).lower().replace(' ', '-')
                
                # Register rule if not seen
                if rule_id not in rules_map:
                    rule = {
                        "id": rule_id,
                        "shortDescription": {
                            "text": frame.get('frame_name', frame.get('frameName', frame_id))
                        },
                        "helpUri": "https://github.com/alperduzgun/warden-core/docs/rules"
                    }
                    run["tool"]["driver"]["rules"].append(rule)
                    rules_map[rule_id] = rule

                # Create SARIF result
                severity = finding.get('severity', 'warning').lower()
                level = "error" if severity in ["critical", "high"] else "warning"
                
                # Handle file path - Finding has 'location' usually as 'file:line'
                location_str = finding.get('location', 'unknown')
                file_path = location_str.split(':')[0] if ':' in location_str else location_str
                
                result = {
                    "ruleId": rule_id,
                    "level": level,
                    "message": {
                        "text": finding.get('message', 'Issue detected by Warden')
                    },
                    "locations": [
                        {
                            "physicalLocation": {
                                "artifactLocation": {
                                    "uri": file_path
                                },
                                "region": {
                                    "startLine": finding.get('line', 1),
                                    "startColumn": finding.get('column', 1)
                                }
                            }
                        }
                    ]
                }
                
                # Add detail if available
                if finding.get('detail'):
                    result["message"]["text"] += f"\n\nDetails: {finding['detail']}"
                    
                run["results"].append(result)

        with open(output_path, 'w') as f:
            json.dump(sarif, f, indent=4)

    def generate_junit_report(
        self,
        scan_results: Dict[str, Any],
        output_path: Path
    ) -> None:
        """
        Generate JUnit XML report for general CI/CD compatibility.
        """
        import xml.etree.ElementTree as ET
        
        testsuites = ET.Element("testsuites", name="Warden Scan")
        
        frame_results = scan_results.get('frame_results', scan_results.get('frameResults', []))
        
        testsuite = ET.SubElement(
            testsuites, 
            "testsuite", 
            name="security_validation",
            tests=str(len(frame_results)),
            failures=str(scan_results.get('frames_failed', scan_results.get('framesFailed', 0))),
            errors="0",
            skipped=str(scan_results.get('frames_skipped', scan_results.get('framesSkipped', 0))),
            time=str(scan_results.get('duration', 0))
        )
        
        for frame in frame_results:
            name = frame.get('frame_name', frame.get('frameName', 'Unknown Frame'))
            classname = f"warden.{frame.get('frame_id', frame.get('frameId', 'generic'))}"
            duration = str(frame.get('duration', 0))
            
            testcase = ET.SubElement(
                testsuite, 
                "testcase", 
                name=name,
                classname=classname,
                time=duration
            )
            
            status = frame.get('status')
            if status == "failed":
                findings = frame.get('findings', [])
                message = f"Found {len(findings)} issues in {name}"
                failure_text = "\n".join([
                    f"- [{f.get('severity')}] {f.get('location')}: {f.get('message')}"
                    for f in findings
                ])
                
                failure = ET.SubElement(
                    testcase,
                    "failure",
                    message=message,
                    type="SecurityViolation"
                )
                failure.text = failure_text
            elif status == "skipped":
                ET.SubElement(testcase, "skipped")

        # Write to file
        tree = ET.ElementTree(testsuites)
        tree.write(output_path, encoding="utf-8", xml_declaration=True)

    def generate_html_report(
        self,
        scan_results: Dict[str, Any],
        output_path: Path
    ) -> None:
        """
        Generate HTML report from scan results.

        Args:
            scan_results: Dictionary containing scan results
            output_path: Path to save the HTML report
        """
        html_content = self._create_html_content(scan_results)

        with open(output_path, 'w') as f:
            f.write(html_content)

    def generate_pdf_report(
        self,
        scan_results: Dict[str, Any],
        output_path: Path
    ) -> None:
        """
        Generate PDF report from HTML.

        Args:
            scan_results: Dictionary containing scan results
            output_path: Path to save the PDF report
        """
        # First generate HTML
        html_content = self._create_html_content(scan_results)

        try:
            # Try to use WeasyPrint if available
            from weasyprint import HTML, CSS

            # Convert HTML to PDF
            HTML(string=html_content).write_pdf(
                output_path,
                stylesheets=[CSS(string=self._get_pdf_styles())]
            )
        except ImportError:
            # Fall back to saving as HTML with .pdf extension warning
            print("Warning: WeasyPrint not installed. Install it with: pip install weasyprint")
            print("Saving as HTML format instead...")

            # Save as HTML with warning
            html_path = output_path.with_suffix('.html')
            with open(html_path, 'w') as f:
                f.write(html_content)

    def _create_html_content(self, scan_results: Dict[str, Any]) -> str:
        """Create HTML content from scan results."""
        timestamp = scan_results.get('timestamp', datetime.now().isoformat())
        project = scan_results.get('project', 'Unknown Project')
        total_files = scan_results.get('total_files', 0)
        analyzed_files = scan_results.get('analyzed_files', 0)
        total_issues = scan_results.get('total_issues', 0)
        critical_issues = scan_results.get('critical_issues', 0)
        high_issues = scan_results.get('high_issues', 0)
        duration = scan_results.get('duration_seconds', 0)
        frame_results = scan_results.get('frame_results', [])

        # Determine overall status
        if critical_issues > 0:
            status_color = "#dc3545"  # Red
            status_text = "CRITICAL"
        elif high_issues > 0:
            status_color = "#ffc107"  # Yellow
            status_text = "WARNING"
        else:
            status_color = "#28a745"  # Green
            status_text = "PASSED"

        # Build frame results table
        frame_rows = ""
        for frame in frame_results:
            status_icon = "✅" if frame['passed'] else "❌"
            blocker_badge = '<span class="badge badge-danger">Blocker</span>' if frame['is_blocker'] else ''
            frame_rows += f"""
            <tr>
                <td>{frame['frame']}</td>
                <td>{status_icon}</td>
                <td>{frame['issues']}</td>
                <td>{blocker_badge}</td>
            </tr>
            """

        html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Warden Scan Report - {project}</title>
    <style>
        {self._get_html_styles()}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🛡️ Warden Scan Report</h1>
            <div class="status-badge" style="background-color: {status_color}">
                {status_text}
            </div>
        </header>

        <section class="info-section">
            <h2>Project Information</h2>
            <div class="info-grid">
                <div class="info-item">
                    <strong>Project:</strong> {project}
                </div>
                <div class="info-item">
                    <strong>Scan Date:</strong> {timestamp}
                </div>
                <div class="info-item">
                    <strong>Duration:</strong> {duration:.2f}s
                </div>
            </div>
        </section>

        <section class="summary-section">
            <h2>Summary Statistics</h2>
            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-value">{total_files}</div>
                    <div class="stat-label">Total Files</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{analyzed_files}</div>
                    <div class="stat-label">Analyzed</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value" style="color: {status_color}">{total_issues}</div>
                    <div class="stat-label">Total Issues</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value" style="color: #dc3545">{critical_issues}</div>
                    <div class="stat-label">Critical</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value" style="color: #ffc107">{high_issues}</div>
                    <div class="stat-label">High Priority</div>
                </div>
            </div>
        </section>

        <section class="results-section">
            <h2>Validation Frame Results</h2>
            <table>
                <thead>
                    <tr>
                        <th>Frame</th>
                        <th>Status</th>
                        <th>Issues</th>
                        <th>Priority</th>
                    </tr>
                </thead>
                <tbody>
                    {frame_rows}
                </tbody>
            </table>
        </section>

        <footer>
            <p>Generated by <strong>Warden v0.1.0</strong> - AI Code Guardian</p>
            <p><small>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</small></p>
        </footer>
    </div>
</body>
</html>
"""
        return html

    def _get_html_styles(self) -> str:
        """Get CSS styles for HTML report."""
        return """
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            line-height: 1.6;
            color: #333;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }

        .container {
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            border-radius: 10px;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
            overflow: hidden;
        }

        header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            text-align: center;
            position: relative;
        }

        h1 {
            font-size: 2.5em;
            margin-bottom: 10px;
        }

        .status-badge {
            display: inline-block;
            padding: 10px 30px;
            border-radius: 25px;
            font-weight: bold;
            color: white;
            margin-top: 10px;
        }

        section {
            padding: 30px;
        }

        h2 {
            color: #667eea;
            margin-bottom: 20px;
            border-bottom: 2px solid #667eea;
            padding-bottom: 10px;
        }

        .info-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-top: 20px;
        }

        .info-item {
            padding: 10px;
            background: #f8f9fa;
            border-radius: 5px;
        }

        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 20px;
            margin-top: 20px;
        }

        .stat-card {
            background: #f8f9fa;
            border-radius: 10px;
            padding: 20px;
            text-align: center;
            transition: transform 0.3s;
        }

        .stat-card:hover {
            transform: translateY(-5px);
            box-shadow: 0 5px 15px rgba(0, 0, 0, 0.1);
        }

        .stat-value {
            font-size: 2.5em;
            font-weight: bold;
            color: #333;
        }

        .stat-label {
            color: #666;
            margin-top: 5px;
        }

        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 20px;
        }

        th {
            background: #667eea;
            color: white;
            padding: 12px;
            text-align: left;
        }

        td {
            padding: 12px;
            border-bottom: 1px solid #ddd;
        }

        tr:hover {
            background: #f8f9fa;
        }

        .badge {
            display: inline-block;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 0.85em;
            font-weight: bold;
        }

        .badge-danger {
            background: #dc3545;
            color: white;
        }

        footer {
            background: #f8f9fa;
            text-align: center;
            padding: 20px;
            color: #666;
        }
        """

    def _get_pdf_styles(self) -> str:
        """Get CSS styles specifically for PDF generation."""
        return """
        @page {
            size: A4;
            margin: 2cm;
        }

        body {
            font-size: 10pt;
        }

        .container {
            box-shadow: none;
        }
        """