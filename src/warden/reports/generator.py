"""Report generator for Warden scan results."""

from pathlib import Path
from typing import Any, Dict, Optional
import json
import os
import tempfile
import fcntl
from contextlib import contextmanager

from .html_generator import HtmlReportGenerator

@contextmanager
def file_lock(lock_path: Path, timeout: float = 10.0):
    """
    Context manager for file locking to prevent race conditions.

    CHAOS ENGINEERING: Includes stale lock detection to prevent deadlocks
    from crashed processes (e.g., kill -9).

    Args:
        lock_path: Path to the lock file
        timeout: Maximum time to wait for lock (seconds)

    Raises:
        TimeoutError: If lock cannot be acquired within timeout

    Note:
        If lock file is older than 5 minutes (stale), automatically removes it.
        This prevents permanent deadlocks from ungraceful process termination.
    """
    import time
    from warden.shared.infrastructure.logging import get_logger

    logger = get_logger(__name__)
    STALE_LOCK_THRESHOLD = 300  # 5 minutes in seconds

    lock_file = None
    try:
        # ANTI-FRAGILITY: Detect and remove stale locks from crashed processes
        if lock_path.exists():
            try:
                lock_age = time.time() - lock_path.stat().st_mtime
                if lock_age > STALE_LOCK_THRESHOLD:
                    logger.warning(
                        "removing_stale_lock",
                        path=str(lock_path),
                        age_seconds=int(lock_age),
                        threshold=STALE_LOCK_THRESHOLD
                    )
                    lock_path.unlink()
            except (OSError, FileNotFoundError) as e:
                logger.debug("stale_lock_check_failed", path=str(lock_path), error=str(e))

        # Create lock file
        lock_file = open(lock_path, 'w')

        # Try to acquire exclusive lock with timeout
        start_time = time.time()
        while True:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break  # Lock acquired
            except (IOError, OSError):
                elapsed = time.time() - start_time
                if elapsed > timeout:
                    raise TimeoutError(
                        f"Could not acquire lock on {lock_path} within {timeout}s. "
                        f"Another process may be writing to the same file."
                    )
                time.sleep(0.1)  # Wait a bit before retrying

        yield lock_file

    finally:
        if lock_file:
            try:
                # IMPORTANT: Unlock BEFORE closing to prevent race conditions
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                lock_file.close()

                # Clean up lock file AFTER unlock+close (chaos engineering principle)
                # This prevents race where another process creates lock between unlink and close
                if lock_path.exists():
                    try:
                        lock_path.unlink()
                    except (OSError, FileNotFoundError):
                        pass
            except Exception as e:
                # Defensive: Log but don't raise in finally block
                logger = get_logger(__name__)
                logger.debug("lock_cleanup_error", error=str(e))

class ReportGenerator:
    """Generate reports in various formats."""

    def __init__(self):
        """
        Initialize report generator with template directory and HTML generator.

        Sets up:
            - templates_dir: Path to report templates directory
            - html_generator: HTML report generator instance for HTML/PDF reports
        """
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
        # Use file lock to prevent race conditions with file watchers
        lock_path = output_path.parent / f".{output_path.name}.lock"

        with file_lock(lock_path):
            # Use inplace=False to create a copy for sanitization
            sanitized_results = self._sanitize_paths(scan_results, base_path, inplace=False)

            # Atomic write: write to temp file first, then replace atomically
            temp_fd, temp_path = tempfile.mkstemp(
                suffix='.json',
                dir=output_path.parent,
                prefix='.tmp_'
            )
            try:
                with os.fdopen(temp_fd, 'w') as f:
                    json.dump(sanitized_results, f, indent=4)
                os.replace(temp_path, output_path)  # Atomic on Unix/Linux
            except Exception:
                # Clean up temp file on failure
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
                raise

    def _sanitize_paths(self, data: Any, base_path: Optional[Path] = None, inplace: bool = True) -> Any:
        """
        Recursively convert absolute paths to relative paths using strict pathlib logic.

        Args:
            data: Data to sanitize
            base_path: Base path to relativize against (default: Path.cwd())
            inplace: If True, modifies data in-place. If False, creates a deep copy first.

        Returns:
            The sanitized data (same reference if inplace=True, new copy if inplace=False)
        """
        # If not in-place, create a deep copy first
        if not inplace:
            import copy
            data = copy.deepcopy(data)

        # Resolving allow generic usage (Fail Fast logic: base_path must be valid if provided)
        root_path = base_path.resolve() if base_path else Path.cwd().resolve()
        
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, (dict, list)):
                    self._sanitize_paths(value, base_path, inplace=True)
                elif isinstance(value, str):
                    # Only attempt sanitization if it looks like a path (e.g. contains separators)
                    # and contains the root path string to avoid wasting cycles
                    if str(root_path) in value:
                        data[key] = self._relativize_string(value, root_path)

        elif isinstance(data, list):
            for i, item in enumerate(data):
                if isinstance(item, (dict, list)):
                    self._sanitize_paths(item, base_path, inplace=True)
                elif isinstance(item, str):
                    if str(root_path) in item:
                        data[i] = self._relativize_string(item, root_path)

        return data

    def _relativize_string(self, text: str, root_path: Path) -> str:
        """Helper to safely relativize path strings."""
        try:
            # Case 1: The string IS the path
            path_obj = Path(text)
            if path_obj.is_absolute():
                # Strict check: Is it actually inside the root?
                if path_obj.resolve().is_relative_to(root_path):
                    return str(path_obj.resolve().relative_to(root_path))
            
            # Case 2: String contains the path (e.g. "File found at /users/...")
            # This uses string replacement but constrained by the known root path
            return text.replace(str(root_path), ".")
            
        except (ValueError, OSError):
             # On failure, return original (Fail Safe) or attempt minimal replacement
             return text.replace(str(root_path), ".")

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
                    "invocations": [
                        {
                            "executionSuccessful": True,
                            "toolExecutionNotifications": []
                        }
                    ],
                    "results": []
                }
            ]
        }
        
        # Inject AI Advisories from Metadata
        metadata = scan_results.get('metadata', {})
        advisories = metadata.get('advisories', []) 
        # Fallback to check if it's in top-level for some reason
        if not advisories:
            advisories = scan_results.get('advisories', [])
            
        if advisories:
            notifications = []
            for advice in advisories:
                notifications.append({
                    "descriptor": {
                        "id": "AI001", 
                        "name": "AI Advisor Note"
                    },
                    "message": {
                        "text": advice
                    },
                    "level": "note"
                })
            sarif["runs"][0]["invocations"][0]["toolExecutionNotifications"] = notifications
        
        # Add custom properties for LLM usage and metrics
        properties = {}
        
        llm_usage = scan_results.get('llmUsage', {})
        if llm_usage:
            properties["llmUsage"] = llm_usage
        
        llm_metrics = scan_results.get('llmMetrics', {})
        if llm_metrics:
            properties["llmMetrics"] = llm_metrics
        
        if properties:
            sarif["runs"][0]["properties"] = properties

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
                detail = finding.get('detail', '')
                
                # Check for manual review flag in verification metadata
                verification = finding.get('verification_metadata', {})
                if verification.get('review_required'):
                    result["message"]["text"] = f"⚠️ [MANUAL REVIEW REQUIRED] {result['message']['text']}"
                    if not detail:
                        detail = verification.get('reason', 'LLM verification was uncertain or skipped.')
                    else:
                        detail = f"{verification.get('reason', 'Verification uncertain')} | {detail}"

                if detail:
                    result["message"]["text"] += f"\\n\\nDetails: {detail}"
                    
                run["results"].append(result)

        # Sanitize final SARIF output (in-place is fine since sarif is local to this method)
        self._sanitize_paths(sarif, base_path, inplace=True)

        # Use file lock to prevent race conditions with file watchers
        lock_path = output_path.parent / f".{output_path.name}.lock"

        with file_lock(lock_path):
            # Atomic write: write to temp file first, then replace atomically
            temp_fd, temp_path = tempfile.mkstemp(
                suffix='.sarif',
                dir=output_path.parent,
                prefix='.tmp_'
            )
            try:
                with os.fdopen(temp_fd, 'w') as f:
                    json.dump(sarif, f, indent=4)
                os.replace(temp_path, output_path)  # Atomic on Unix/Linux
            except Exception:
                # Clean up temp file on failure
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
                raise

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

        # Use inplace=False to create a copy for sanitization
        sanitized_results = self._sanitize_paths(scan_results, base_path, inplace=False)

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

        # Atomic write: write to temp file first, then replace atomically
        tree = ET.ElementTree(testsuites)
        temp_fd, temp_path = tempfile.mkstemp(
            suffix='.xml',
            dir=output_path.parent,
            prefix='.tmp_'
        )
        try:
            # Close the file descriptor and use path-based write
            os.close(temp_fd)
            tree.write(temp_path, encoding="utf-8", xml_declaration=True)
            os.replace(temp_path, output_path)  # Atomic on Unix/Linux
        except Exception:
            # Clean up temp file on failure
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            raise

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
        # Use inplace=False to create a copy for sanitization
        sanitized_results = self._sanitize_paths(scan_results, base_path, inplace=False)

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

        Raises:
            RuntimeError: If WeasyPrint is not installed
        """
        # Use inplace=False to create a copy for sanitization
        sanitized_results = self._sanitize_paths(scan_results, base_path, inplace=False)

        # First generate HTML content using the helper
        html_content = self.html_generator._create_html_content(sanitized_results)

        try:
            # Try to use WeasyPrint if available
            from weasyprint import HTML, CSS
        except ImportError:
            raise RuntimeError(
                "PDF generation requires WeasyPrint. Install with: pip install weasyprint"
            )

        # Convert HTML to PDF using atomic write
        temp_fd, temp_path = tempfile.mkstemp(
            suffix='.pdf',
            dir=output_path.parent,
            prefix='.tmp_'
        )
        try:
            # Close the file descriptor as WeasyPrint writes to path directly
            os.close(temp_fd)
            HTML(string=html_content).write_pdf(
                temp_path,
                stylesheets=[CSS(string=self.html_generator.get_pdf_styles())]
            )
            os.replace(temp_path, output_path)  # Atomic on Unix/Linux
        except Exception:
            # Clean up temp file on failure
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            raise