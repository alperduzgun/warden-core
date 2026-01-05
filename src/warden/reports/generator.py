"""Report generator for Warden scan results."""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import json

from .html_generator import HtmlReportGenerator

class ReportGenerator:
    """Generate reports in various formats."""

    def __init__(self):
        """Initialize report generator."""
        self.templates_dir = Path(__file__).parent / "templates"
        self.html_generator = HtmlReportGenerator()

    def generate_json_report(
        self,
        scan_results: Dict[str, Any],
        output_path: Path,
        base_path: Optional[Path] = None
    ) -> None:
        """
        Generate JSON report from scan results.

        Args:
            scan_results: Dictionary containing scan results
            output_path: Path to save the JSON report
            base_path: Optional base path for relativizing paths (defaults to CWD)
        """
        # Create a deep copy to sanitization doesn't affect the running pipeline
        import copy
        sanitized_results = copy.deepcopy(scan_results)
        self._sanitize_paths(sanitized_results, base_path)
        
        with open(output_path, 'w') as f:
            json.dump(sanitized_results, f, indent=4)

    def _sanitize_paths(self, data: Any, base_path: Optional[Path] = None) -> None:
        """
        Recursively convert absolute paths to relative paths in dictionary/list.
        
        Args:
            data: Data to sanitize
            base_path: Base path to relativize against (default: Path.cwd())
        """
        # Resolving allow generic usage
        root = str(base_path.resolve()) if base_path else str(Path.cwd().resolve())
        root_path_obj = base_path.resolve() if base_path else Path.cwd().resolve()
        
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, (dict, list)):
                    self._sanitize_paths(value, base_path)
                elif isinstance(value, str):
                    if root in value:
                        try:
                            # Try to treat as pure path first
                            path_val = Path(value)
                            if path_val.is_absolute() and str(path_val.resolve()).startswith(root):
                                data[key] = str(path_val.resolve().relative_to(root_path_obj))
                            else:
                                # Fallback for sentences containing the path
                                data[key] = value.replace(root, ".")
                        except Exception:
                             # If Path() fails or other error, just replace string
                             data[key] = value.replace(root, ".")
        elif isinstance(data, list):
            for i, item in enumerate(data):
                if isinstance(item, (dict, list)):
                    self._sanitize_paths(item, base_path)
                elif isinstance(item, str):
                     if root in item:
                        try:
                            path_item = Path(item)
                            if path_item.is_absolute() and str(path_item.resolve()).startswith(root):
                                data[i] = str(path_item.resolve().relative_to(root_path_obj))
                            else:
                                data[i] = item.replace(root, ".")
                        except Exception:
                            data[i] = item.replace(root, ".")

    def generate_sarif_report(
        self,
        scan_results: Dict[str, Any],
        output_path: Path,
        base_path: Optional[Path] = None
    ) -> None:
        """
        Generate SARIF report from scan results for GitHub integration.

        Args:
            scan_results: Dictionary containing scan results
            output_path: Path to save the SARIF report
            base_path: Optional base path for relativizing paths
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
        
        # Add custom properties for LLM usage
        llm_usage = scan_results.get('llmUsage', {})
        if llm_usage:
            sarif["runs"][0]["properties"] = {
                "llmUsage": llm_usage
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
                                    "uri": self._to_relative_uri(file_path)
                                },
                                "region": {
                                    "startLine": max(1, finding.get('line', 1)),
                                    "startColumn": max(1, finding.get('column', 1))
                                }
                            }
                        }
                    ]
                }
                
                # Add detail if available
                if finding.get('detail'):
                    result["message"]["text"] += f"\\n\\nDetails: {finding['detail']}"
                    
                run["results"].append(result)
        
        # Sanitize final SARIF output
        self._sanitize_paths(sarif, base_path)

        with open(output_path, 'w') as f:
            json.dump(sarif, f, indent=4)

    def _to_relative_uri(self, file_path: str) -> str:
        """
        Convert file path to a relative URI compatible with SARIF / GitHub.
        Falls back to filename if relativization fails.
        """
        path_obj = Path(file_path)
        try:
            # Try standard relative_to
            if path_obj.is_absolute():
                return str(path_obj.relative_to(Path.cwd()))
            return str(path_obj)
        except ValueError:
            # If path is not under CWD (e.g. /tmp or external)
            try:
                # Naive fallback: if src/ is in path, take it from there
                parts = path_obj.parts
                if "src" in parts:
                    idx = parts.index("src")
                    # Reconstruct path from 'src' onwards
                    return str(Path(*parts[idx:]))
                
                # Last resort: just the filename to avoid "uri must be relative" error
                return path_obj.name
            except Exception:
                return "unknown_file"

    def generate_junit_report(
        self,
        scan_results: Dict[str, Any],
        output_path: Path,
        base_path: Optional[Path] = None
    ) -> None:
        """
        Generate JUnit XML report for general CI/CD compatibility.
        """
        import xml.etree.ElementTree as ET
        
        # Clone and sanitize first to ensure all content in XML is safe
        import copy
        sanitized_results = copy.deepcopy(scan_results)
        self._sanitize_paths(sanitized_results, base_path)
        
        testsuites = ET.Element("testsuites", name="Warden Scan")
        
        frame_results = sanitized_results.get('frame_results', sanitized_results.get('frameResults', []))
        
        testsuite = ET.SubElement(
            testsuites, 
            "testsuite", 
            name="security_validation",
            tests=str(len(frame_results)),
            failures=str(sanitized_results.get('frames_failed', sanitized_results.get('framesFailed', 0))),
            errors="0",
            skipped=str(sanitized_results.get('frames_skipped', sanitized_results.get('framesSkipped', 0))),
            time=str(sanitized_results.get('duration', 0))
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
                failure_text = "\\n".join([
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
        output_path: Path,
        base_path: Optional[Path] = None
    ) -> None:
        """
        Generate HTML report from scan results.

        Args:
            scan_results: Dictionary containing scan results
            output_path: Path to save the HTML report
            base_path: Optional base path for relativizing paths
        """
        # Create sanitized copy for HTML generation too
        import copy
        sanitized_results = copy.deepcopy(scan_results)
        self._sanitize_paths(sanitized_results, base_path)
        
        self.html_generator.generate(sanitized_results, output_path)

    def generate_pdf_report(
        self,
        scan_results: Dict[str, Any],
        output_path: Path,
        base_path: Optional[Path] = None
    ) -> None:
        """
        Generate PDF report from HTML.

        Args:
            scan_results: Dictionary containing scan results
            output_path: Path to save the PDF report
            base_path: Optional base path for relativizing paths
        """
        # Create sanitized copy
        import copy
        sanitized_results = copy.deepcopy(scan_results)
        self._sanitize_paths(sanitized_results, base_path)
        
        # First generate HTML content using the helper
        html_content = self.html_generator._create_html_content(sanitized_results)

        try:
            # Try to use WeasyPrint if available
            from weasyprint import HTML, CSS

            # Convert HTML to PDF
            HTML(string=html_content).write_pdf(
                output_path,
                stylesheets=[CSS(string=self.html_generator.get_pdf_styles())]
            )
        except ImportError:
            # Fall back to saving as HTML with .pdf extension warning
            print("Warning: WeasyPrint not installed. Install it with: pip install weasyprint")
            print("Saving as HTML format instead...")

            # Save as HTML with warning
            html_path = output_path.with_suffix('.html')
            with open(html_path, 'w') as f:
                f.write(html_content)