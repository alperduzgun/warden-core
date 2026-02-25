"""Report generator for Warden scan results."""

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any

from .html_generator import HtmlReportGenerator

# ---------------------------------------------------------------------------
# Contract Mode SARIF Rule Metadata
# ---------------------------------------------------------------------------
# These five rules are injected into tool.driver.rules whenever SARIF output
# is generated, allowing GitHub Code Scanning to surface contract violations
# with rich descriptions.

CONTRACT_RULE_META: dict[str, dict[str, Any]] = {
    "CONTRACT-DEAD-WRITE": {
        "id": "CONTRACT-DEAD-WRITE",
        "name": "DeadWrite",
        "shortDescription": {"text": "Dead data write: field written but never read"},
        "fullDescription": {
            "text": (
                "A pipeline context field is written but never consumed by any subsequent phase. "
                "This indicates dead code or a missing data consumer."
            )
        },
        "help": {"text": "Remove the write or add a consumer frame that reads this field."},
        "properties": {
            "tags": ["contract", "data-flow", "dead-code"],
            "precision": "high",
        },
    },
    "CONTRACT-MISSING-WRITE": {
        "id": "CONTRACT-MISSING-WRITE",
        "name": "MissingWrite",
        "shortDescription": {"text": "Missing data write: field read but never written"},
        "fullDescription": {
            "text": (
                "A pipeline context field is consumed by a frame but never populated by any previous phase. "
                "This means the frame is operating on uninitialized/None data."
            )
        },
        "help": {"text": "Add a phase that writes this field before it is consumed."},
        "properties": {
            "tags": ["contract", "data-flow", "uninitialized"],
            "precision": "high",
        },
    },
    "CONTRACT-NEVER-POPULATED": {
        "id": "CONTRACT-NEVER-POPULATED",
        "name": "NeverPopulated",
        "shortDescription": {"text": "Optional field never populated"},
        "fullDescription": {
            "text": (
                "A field declared as Optional in PipelineContext is never assigned a value. "
                "Downstream consumers always receive None."
            )
        },
        "help": {
            "text": ("Implement the phase responsible for populating this field, or remove it from PipelineContext.")
        },
        "properties": {
            "tags": ["contract", "data-flow", "never-populated"],
            "precision": "very-high",
        },
    },
    "CONTRACT-STALE-SYNC": {
        "id": "CONTRACT-STALE-SYNC",
        "name": "StaleSync",
        "shortDescription": {"text": "Stale synchronization: co-written fields diverge"},
        "fullDescription": {
            "text": (
                "Two or more fields that are always written together have diverged. "
                "One is updated but the other is not, causing stale/inconsistent state."
            )
        },
        "help": {"text": "Ensure all co-written fields are updated atomically."},
        "properties": {
            "tags": ["contract", "data-flow", "stale-sync"],
            "precision": "medium",
        },
    },
    "CONTRACT-ASYNC-RACE": {
        "id": "CONTRACT-ASYNC-RACE",
        "name": "AsyncRace",
        "shortDescription": {"text": "Potential async race condition on shared mutable state"},
        "fullDescription": {
            "text": (
                "An asyncio.gather call operates on shared mutable context without a lock. "
                "Concurrent modifications may produce non-deterministic results."
            )
        },
        "help": {"text": "Add asyncio.Lock protection around shared mutable state in concurrent code."},
        "properties": {
            "tags": ["contract", "async", "race-condition"],
            "precision": "medium",
        },
    },
}


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
                        threshold=STALE_LOCK_THRESHOLD,
                    )
                    lock_path.unlink()
            except (OSError, FileNotFoundError) as e:
                logger.debug("stale_lock_check_failed", path=str(lock_path), error=str(e))

        # Create lock file
        lock_file = open(lock_path, "w")

        # Try to acquire exclusive lock with timeout
        start_time = time.time()
        while True:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break  # Lock acquired
            except OSError:
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
                    with suppress(OSError, FileNotFoundError):
                        lock_path.unlink()
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

    @staticmethod
    def _get_version() -> str:
        try:
            from warden._version import __version__

            return __version__
        except Exception:
            return "0.0.0"

    def _get_val(self, obj: Any, key: str, default: Any = None) -> Any:
        """
        Safely get a value from either a dictionary or an object.
        Supports both dict.get() and getattr().
        """
        if obj is None:
            return default
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    def generate_json_report(
        self, scan_results: dict[str, Any], output_path: Path, base_path: Path | None = None
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
            temp_fd, temp_path = tempfile.mkstemp(suffix=".json", dir=output_path.parent, prefix=".tmp_")
            try:
                with os.fdopen(temp_fd, "w") as f:
                    json.dump(sanitized_results, f, indent=4)
                os.replace(temp_path, output_path)  # Atomic on Unix/Linux
            except Exception:
                # Clean up temp file on failure
                with suppress(OSError):
                    os.unlink(temp_path)
                raise

    def _sanitize_paths(self, data: Any, base_path: Path | None = None, inplace: bool = True) -> Any:
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
                elif isinstance(item, str) and str(root_path) in item:
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
        self, scan_results: dict[str, Any], output_path: Path, base_path: Path | None = None
    ) -> None:
        """
        Generate SARIF report from scan results for GitHub integration.

        Args:
            scan_results: Dictionary containing scan results
            output_path: Path to save the SARIF report
            base_path: Optional base path for relativizing paths
        """
        from warden.shared.infrastructure.logging import get_logger

        logger = get_logger(__name__)

        # Basic SARIF v2.1.0 structure
        sarif = {
            "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
            "version": "2.1.0",
            "runs": [
                {
                    "tool": {
                        "driver": {
                            "name": "Warden",
                            "semanticVersion": self._get_version(),
                            "informationUri": "https://github.com/alperduzgun/warden-core",
                            "rules": [],
                        }
                    },
                    "invocations": [{"executionSuccessful": True, "toolExecutionNotifications": []}],
                    "results": [],
                }
            ],
        }

        # Inject AI Advisories from Metadata
        metadata = scan_results.get("metadata", {})
        advisories = metadata.get("advisories", [])
        # Fallback to check if it's in top-level for some reason
        if not advisories:
            advisories = scan_results.get("advisories", [])

        if advisories:
            notifications = []
            for advice in advisories:
                notifications.append(
                    {
                        "descriptor": {"id": "AI001"},
                        "message": {"text": advice},
                        "level": "note",
                    }
                )
            sarif["runs"][0]["invocations"][0]["toolExecutionNotifications"] = notifications

        # Add custom properties for LLM usage and metrics
        properties = {}

        llm_usage = scan_results.get("llmUsage", {})
        if llm_usage:
            properties["llmUsage"] = llm_usage

        llm_metrics = scan_results.get("llmMetrics", {})
        if llm_metrics:
            properties["llmMetrics"] = llm_metrics

        if properties:
            sarif["runs"][0]["properties"] = properties

        run = sarif["runs"][0]
        rules_map = {}

        # Inject contract mode rule definitions into tool.driver.rules so that
        # GitHub Code Scanning can show full descriptions for CONTRACT-* findings.
        for rule_id, rule_meta in CONTRACT_RULE_META.items():
            sarif_rule = {
                "id": rule_meta["id"],
                "name": rule_meta["name"],
                "shortDescription": rule_meta["shortDescription"],
                "fullDescription": rule_meta["fullDescription"],
                "help": rule_meta["help"],
                "properties": rule_meta["properties"],
                "helpUri": "https://github.com/alperduzgun/warden-core/docs/rules/contract",
            }
            run["tool"]["driver"]["rules"].append(sarif_rule)
            rules_map[rule_id.lower()] = sarif_rule

        # Support both snake_case (CLI) and camelCase (Panel)
        frame_results = scan_results.get("frame_results", scan_results.get("frameResults", []))

        for frame in frame_results:
            findings = self._get_val(frame, "findings", [])
            frame_id = self._get_val(frame, "frame_id", self._get_val(frame, "frameId", "generic"))

            for finding in findings:
                # Use finding ID or Fallback to frame ID
                rule_id = str(self._get_val(finding, "id", frame_id)).lower().replace(" ", "-")

                # Handle file path - Finding has 'location' usually as 'file:line'
                location_str = self._get_val(finding, "location", "unknown")
                file_path = location_str.split(":")[0] if ":" in location_str else location_str

                # Log if critical attributes are missing
                if not rule_id or not location_str:
                    logger.warning(
                        "sarif_finding_missing_critical_attributes",
                        finding_id=rule_id,
                        location=location_str,
                        frame_id=frame_id,
                    )

                # Register rule if not seen
                if rule_id not in rules_map:
                    rule = {
                        "id": rule_id,
                        "shortDescription": {
                            "text": self._get_val(frame, "frame_name", self._get_val(frame, "frameName", frame_id))
                        },
                        "helpUri": "https://github.com/alperduzgun/warden-core/docs/rules",
                    }
                    run["tool"]["driver"]["rules"].append(rule)
                    rules_map[rule_id] = rule

                # Create SARIF result
                severity = self._get_val(finding, "severity", "warning").lower()
                level = "error" if severity in ["critical", "high"] else "warning"

                result = {
                    "ruleId": rule_id,
                    "level": level,
                    "message": {"text": self._get_val(finding, "message", "Issue detected by Warden")},
                    "locations": [
                        {
                            "physicalLocation": {
                                "artifactLocation": {"uri": self._to_relative_uri(file_path)},
                                "region": {
                                    "startLine": max(1, self._get_val(finding, "line", 1)),
                                    "startColumn": max(1, self._get_val(finding, "column", 1)),
                                },
                            }
                        }
                    ],
                }

                # Add detail if available
                detail = self._get_val(finding, "detail", "")

                # Check for manual review flag in verification metadata
                verification = self._get_val(finding, "verification_metadata", {})
                if self._get_val(verification, "review_required"):
                    result["message"]["text"] = f"⚠️ [MANUAL REVIEW REQUIRED] {result['message']['text']}"
                    if not detail:
                        detail = self._get_val(verification, "reason", "LLM verification was uncertain or skipped.")
                    else:
                        detail = f"{self._get_val(verification, 'reason', 'Verification uncertain')} | {detail}"

                if detail:
                    result["message"]["text"] += f"\\n\\nDetails: {detail}"

                # Add exploit evidence if available
                exploit_evidence = self._get_val(finding, "exploitEvidence", None)
                if exploit_evidence:
                    if "properties" not in result:
                        result["properties"] = {}
                    result["properties"]["exploitEvidence"] = exploit_evidence

                run["results"].append(result)

        # Log suppressed findings
        suppressed_findings = scan_results.get("suppressed_findings", [])
        if suppressed_findings:
            logger.info(
                "sarif_suppressed_findings",
                count=len(suppressed_findings),
                findings=[f.get("id", "unknown") for f in suppressed_findings],
            )
            # Optionally, add suppressed findings to SARIF as notifications or with suppression property
            # For now, just logging as per instruction.

        # Sanitize final SARIF output (in-place is fine since sarif is local to this method)
        self._sanitize_paths(sarif, base_path, inplace=True)

        # Use file lock to prevent race conditions with file watchers
        lock_path = output_path.parent / f".{output_path.name}.lock"

        with file_lock(lock_path):
            # Atomic write: write to temp file first, then replace atomically
            temp_fd, temp_path = tempfile.mkstemp(suffix=".sarif", dir=output_path.parent, prefix=".tmp_")
            try:
                with os.fdopen(temp_fd, "w") as f:
                    json.dump(sarif, f, indent=4)
                os.replace(temp_path, output_path)  # Atomic on Unix/Linux
            except Exception:
                # Clean up temp file on failure
                with suppress(OSError):
                    os.unlink(temp_path)
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
                raise

    def generate_svg_badge(
        self, scan_results: dict[str, Any], output_path: Path, base_path: Path | None = None
    ) -> None:
        """
        Generate a premium, standalone SVG badge for the project quality.
        """
        from warden.shared.utils.quality_calculator import calculate_quality_score

        # Extract findings
        all_findings = []
        frame_results = scan_results.get("frame_results", scan_results.get("frameResults", []))
        for frame in frame_results:
            all_findings.extend(frame.get("findings", []))
        manual = scan_results.get("manual_review_findings_list", [])
        all_findings.extend(manual)

        score = calculate_quality_score(all_findings, 10.0)

        # Determine Color Gradient
        if score >= 9.0:
            gradient_start, gradient_end = "#10B981", "#059669"  # Emerald
            status_text = "EXCELLENT"
        elif score >= 7.5:
            gradient_start, gradient_end = "#3B82F6", "#2563EB"  # Blue
            status_text = "GOOD"
        elif score >= 5.0:
            gradient_start, gradient_end = "#F59E0B", "#D97706"  # Amber
            status_text = "WARNING"
        elif score >= 2.5:
            gradient_start, gradient_end = "#F97316", "#EA580C"  # Orange
            status_text = "RISK"
        else:
            gradient_start, gradient_end = "#EF4444", "#DC2626"  # Red
            status_text = "CRITICAL"

        # Calculate progress circle (circumference = 2 * pi * r)
        # r=16 -> circ ≈ 100
        (score / 10.0) * 100.0

        # Calculate HMAC Signature (Simple MVP)
        import hashlib
        import hmac
        import time

        timestamp = int(time.time())
        badge_secret = os.environ.get("WARDEN_BADGE_SECRET", "")
        if not badge_secret:
            from warden.shared.infrastructure.logging import get_logger as _get_logger

            _get_logger(__name__).warning(
                "badge_secret_not_set",
                message="WARDEN_BADGE_SECRET env var not set. Badge signature uses weak default. "
                "Set WARDEN_BADGE_SECRET for production use.",
            )
            badge_secret = "warden-local-dev-only"  # warden-ignore: hardcoded-password
        secret_key = badge_secret.encode()
        payload = f"{score:.1f}|{timestamp}|WARDEN_QUALITY".encode()
        signature = hmac.new(secret_key, payload, hashlib.sha256).hexdigest()

        # Generate SVG with Link and Metadata
        svg_content = f"""<svg width="400" height="100" viewBox="0 0 400 100" fill="none" xmlns="http://www.w3.org/2000/svg"
     data-warden-score="{score:.1f}"
     data-warden-timestamp="{timestamp}"
     data-warden-signature="{signature}">
    <a href="https://warden.ai/verify?score={score:.1f}&amp;sig={signature}&amp;ts={timestamp}" target="_blank">
        <!-- Drop Shadow Filter -->
        <defs>
            <filter id="shadow" x="-10%" y="-10%" width="120%" height="120%">
                <feDropShadow dx="0" dy="4" stdDeviation="4" flood-color="#000" flood-opacity="0.25"/>
            </filter>
            <linearGradient id="cardGrad" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0%" stop-color="#1e1e2e"/>
                <stop offset="100%" stop-color="#2a2a3c"/>
            </linearGradient>
            <linearGradient id="scoreGrad" x1="0" y1="0" x2="1" y2="0">
                <stop offset="0%" stop-color="{gradient_start}"/>
                <stop offset="100%" stop-color="{gradient_end}"/>
            </linearGradient>
        </defs>

        <!-- Background Card -->
        <rect x="2" y="2" width="396" height="96" rx="16" fill="url(#cardGrad)" stroke="#3b3b4f" stroke-width="1" filter="url(#shadow)"/>

        <!-- Warden Logo (White) -->
        <g transform="translate(24, 18) scale(0.09)">
            <path fill="#ffffff" d="m378.5 15.3c-36.8 28.4-89.3 53.8-140.1 67.6-33.1 9-60.2 13.3-99.6 15.7l-9.8 0.6-0.2 152.1-0.3 152.2-4.8-9.5c-2.7-5.6-5.7-13.6-7.2-19.5-2.2-8.8-2.5-12.1-2.5-28.6 0-25-1.9-31.3-11.1-35.9-12.3-6.3-28.4 2.1-36.9 19.4-8.2 16.4-8.5 30.2-1.4 55.5 0.7 2.4 0.6 2.4-3.7 1.5-2.4-0.5-9.1-0.9-14.9-0.9-9.4 0.1-11.2 0.4-16.8 2.9-4.2 2-7.9 4.6-11.1 8.2-7.9 8.6-9.7 17-6.5 30l1.7 6.5-2.6 2.7c-3.4 3.5-7.5 12.7-8.3 18.3-0.8 5.7 1.7 15.6 5.5 22.4 2.1 3.8 2.6 5.6 1.9 6.8-1.9 3.5-2.8 13.1-1.7 19.1 4.3 24.2 37 44.5 71.6 44.6 5 0 10.4 0.5 12 1.1 2.7 1.2 2.7 1.2-3.2 2.6-3.3 0.8-7.1 1.6-8.3 1.9-2 0.4-2.3 0.9-1.7 3.2 0.3 1.5 2 4.5 3.7 6.6 12.2 15.3 33.9 27.1 61.1 33.1l7.8 1.7-6.1 2.9c-4.3 2-6 3.4-6 4.8 0 4.7 12.3 12.7 26.2 16.9 12.9 4 39.8 5.2 58.3 2.6 3.9-0.5 4.3-0.2 13.7 8 30.6 26.7 65 49.4 99.4 65.7 20.5 9.7 46.5 20.1 50.4 20.1 7.5 0.1 52-19.7 79-35 46-26.1 92.1-65.9 121.4-104.6 29.4-39 45.7-75.3 54.3-120.6l2.8-14.5 0.3-172.1 0.2-172.2-11.7-0.6c-58.1-3.5-109.5-15.8-162-39-25.6-11.4-60.2-31.8-77.1-45.5-3.4-2.8-6.5-5.1-7-5.1-0.4 0-4.3 2.9-8.7 6.3zm15.1 18c58.4 42.5 139.2 71.9 217.8 79.2 9.3 0.9 17.3 1.8 17.8 2.1 1.2 0.8 1 300.8-0.2 317.9-2.3 31.3-12.9 67.5-28.1 96l-5 9.3-6.7-5c-3.7-2.8-9-6.2-11.9-7.5-5.1-2.3-16.4-5.2-21.3-5.3-2.7-0.1-26.8-18.6-30.2-23.1-1.5-2-1.9-4.4-2-12-0.2-13.5 1.5-18.4 10.2-29.2 19.2-23.8 34-53.9 39.6-80.7 4.7-22.6 5.8-48.7 3-69.5-0.9-6.1-2.4-17.5-3.5-25.5-4-29.3-10.5-50.1-22.2-71.2-15-26.9-39.7-50.3-68.8-64.8-28.4-14.3-70.5-22.2-89.4-17-7.7 2.2-14.2 11.1-16.8 22.9-0.6 2.8-1.2 5.1-1.4 5.1-0.2 0-5.9-2.5-12.7-5.6-17.8-8-18.4-8.1-35.9 0-51.1 23.6-83.2 57-96.9 101.1-6.9 21.9-9.1 37.2-6.7 45.6 2.1 6.9 9.5 19 15.4 25l4.5 4.7-1.2 5.3c-2.5 11.7-2.3 39.8 0.5 47 0.4 1.1-0.6 2.1-3.5 3.4-13 5.9-16.7 22.3-8.5 37.1l3.7 6.7-5.8-0.9c-3.3-0.5-11.7-0.9-18.9-0.8-10.9 0-13.9 0.4-18.5 2.2-19.2 7.6-23.8 27.5-9.7 41.7 9.4 9.3 21.6 14.5 34.3 14.5 5.9 0 6.2 0.1 7.4 3 6.3 15.1 28.8 28 68.5 39 8.3 2.4 15.6 4.4 16.4 4.6 1.9 0.6 0.3 2.2-7.6 7.6l-6.8 4.6-9.5-0.8c-32.8-2.9-64.6-15.4-90.6-35.7-14.6-11.3-36.9-36.3-42.6-47.8-1.6-3.1-3.3-13.9-4.2-26-0.3-3.9-0.6-76.5-0.6-161.4-0.1-113.6 0.2-154.6 1-155.1 0.6-0.4 6.5-1 13.1-1.4 71.3-4 155.7-33.5 215.9-75.5 6.3-4.4 11.8-8 12.1-8 0.4-0.1 3.3 1.8 6.5 4.2zm33.9 107.3c38.5 6.4 71.8 24.4 95 51.3 6 6.9 22.4 32.1 22.5 34.3 0 0.4-3.3-2.9-7.3-7.5-13.4-15-28.8-26.5-48.6-36.2-24.4-12-49.3-17.4-79.6-17.5-14.2 0-16.4-0.2-19.3-2-2.7-1.7-3.1-2.4-2.6-4.7 2.8-13.1 5.5-17.7 10.7-19.1 4.2-1.1 18-0.4 29.2 1.4zm-74.4 19.4c11.8 4.9 32.5 16 45.4 24.4 49.3 32.1 85.1 68.8 109.5 112.4 7.4 13.2 14.6 29.5 13.2 30-5.5 1.8-17.1 13.1-18.7 18.2-0.4 1.1-1.2 1.9-1.8 1.9-0.7-0.1-5-4.2-9.7-9.3-18.3-19.7-43.8-40.1-66-52.8-29.9-17.1-72.8-33-102.3-37.8-6.6-1.1-12.2-2.1-12.4-2.4-0.6-0.6 2.4-12.9 5.8-24.1 6.1-19.7 17.4-45.6 25.5-58.3 1.9-2.8 3.5-5.2 3.8-5.2 0.2 0 3.6 1.4 7.7 3zm-26.7 9.2c-10.1 20.1-20.4 49-24.1 67.4l-1.6 8.3-5.6 1.1c-20.8 4.1-40.1 12.2-53.5 22.5-2.6 1.9-4.8 3.5-5 3.5-1.9 0 9.3-30.3 15.1-41 9.3-17.1 25.8-35.7 42.1-47.5 7.8-5.7 33.8-21.4 35.5-21.5 0.4 0-0.9 3.3-2.9 7.2zm101.6 9.9c22.3 2.7 38.4 7.5 57.5 16.9 26.5 13.2 47.3 33.4 61.1 59.5 12.4 23.4 20.5 62.8 17.9 87l-0.7 6.9-3.5-6.7c-4.5-8.4-10.3-13.9-18-16.7l-6-2.2-6.1-12.6c-23.4-48.6-52.8-84.6-98.4-120-7-5.5-13.8-10.6-15-11.5l-2.3-1.6h2.5c1.4-0.1 6.4 0.4 11 1zm-111.3 80.4c17.8 2.9 53.5 13.4 63.7 18.7l2.8 1.5-4.4 2.6c-10.5 6.1-24.8 27.1-21 30.9 0.6 0.6 2.7-1 5.8-4.4 14.3-15.6 22.9-21.2 32.6-21.3 4.8 0 6.9 0.7 14.5 4.6 11.7 6.2 26.7 15.6 38.3 24.3 9.9 7.4 31.3 27.6 40.3 37.9l5.2 6 0.4 11.6c0.6 19.6 0.5 29-0.3 29.8-0.5 0.4-1.1 0.3-1.3-0.4-1.2-3.5-6.8-10.4-10.2-12.6-7.3-4.9-17.6-6.8-24-4.6-5 1.8-3.7 4.2 2.8 5.1 7.1 1.1 12.9 3.7 17.9 8.2 6 5.4 8.2 11 8.2 20.3 0 10.3-1.2 12-3.6 5.3-4.7-13-18.6-22-33.9-22-11.4 0-21.7 4-38.2 14.7-15.1 9.7-18.2 10.8-30.3 10.8-8.7-0.1-11.3-0.4-15.4-2.3-5.6-2.6-16-10-25.1-18-13.4-11.7-30.3-16.6-42.2-12.1-2.7 1-2.7 0.8-0.8-5.7 4.3-14.8 3.9-42-1-63.9-3-13.1-6.2-20.1-11.5-24.9-8.9-8-18.3-6.8-28.3 3.8-5.2 5.6-5.1 5.9-2.6-5.4 1.4-6.4 5.6-15.3 9.5-19.9 3.5-4.3 7.4-6.1 12.7-6.1 5.7 0 10.2 3 14.4 9.5 6.2 9.6 5.8 9.2 7.1 6.9 2.3-4.3-2.4-16.2-9.1-23.1-4-4.2-4-4.2-1.6-4.8 10.5-2.6 17.1-2.9 28.6-1zm-71.8 29.2c-1.5 4.9-3.1 10.1-3.4 11.8l-0.7 3-2.3-4.5c-1.3-2.5-2.4-5.2-2.5-6.1 0-1.2 10.5-12.8 11.6-12.9 0.1 0-1.1 3.9-2.7 8.7zm32 17.7c5.3 2.8 11 17.6 13.5 35.4l0.6 4.2-3.7-2c-4.2-2.2-7.6-1.8-11.1 1.4-2.1 1.8-6.2 8.5-6.2 10 0 0.3 1.8 1 4 1.6 3.2 0.8 4.5 1.9 5.7 4.5 1.6 3.3 1.5 3.6-0.2 5.5-2 2.2-5.5 2.6-8.7 0.9-2.9-1.5-3.8 0.2-3.8 7.6 0 11.9 5 27.1 9.5 28.9 2.4 0.9 1.7 2.6-1 2.6-10 0-17.7-10.5-21.7-29.8-5.5-26.4 2.8-64.3 15.4-70.5 4.1-2 4.2-2 7.7-0.3zm-178.6 15.4c2.7 2.9 3.6 10.7 3 25.2-0.7 16.2 1.3 30.3 5.8 42 1.6 4.1 7 14.9 12 24 11.9 21.7 14.1 28.2 14.7 43 0.3 9.1-0.1 13.7-1.8 21.9-1.1 5.7-1.9 10.6-1.6 10.8 1.7 1.7 8.5-5.8 11.4-12.8l1.8-4.1 7 8.8c26.1 33 56.7 54.2 94.5 65.5 10.4 3.1 29.9 6.9 35.7 6.9 1.7 0 3.2 0.3 3.2 0.6 0 0.4-1.5 2.7-3.4 5.3-5.2 7.2-15 24.7-19.1 34.4-4 9.2-4.7 10-12.4 12.3-28 8.3-58.1 9.5-79.1 3.3-10.5-3.1-10.5-3.2 0.2-8.4 8.8-4.3 17.8-10.6 17.8-12.4 0-0.4-5.1-1.1-11.4-1.4-26.4-1.6-49.7-7.7-65.5-17.4-5.2-3.2-9.6-6.3-9.8-6.9-0.2-0.7 4.4-1.3 14.4-1.8 13.7-0.6 26.3-2.8 26.3-4.6 0-0.4-4.8-2.4-10.7-4.5-6-2.1-14.4-5.6-18.8-7.7l-7.9-4 2.9-2.1c4.7-3.3 8.9-8.3 11.4-13.3 2.3-4.5 4-12.4 2.7-12.4-0.4 0-3.4 2.9-6.8 6.6-7.6 8.1-12.2 10.9-22.9 13.5-18.1 4.6-40.7-0.6-57-13.1-10.3-8-13.8-13.9-13.9-23.2 0-5 0.4-6.2 3-9.2 4.7-5.3 10.6-7.1 22.5-7 10.7 0.1 23.5 2.9 29.3 6.4 6.7 4.1 7.8 12 2.4 17.8-3.9 4.2-8.7 5.2-24.3 5.2-10.8 0-13.8 0.3-14.2 1.4-1.5 3.9 10.6 9.5 22.3 10.3 14.1 1 24.6-4 29.5-14.1 2.4-4.9 2.7-6.4 2.3-12.8-0.3-4-0.8-8-1.2-8.9-0.5-1.1 0.1-1.9 1.9-2.7 3.2-1.5 6.3-0.1 12.6 5.8 4.5 4.2 5.9 4.8 5.9 2.7 0-3.7-2.5-9-6.3-13.3l-4.2-4.8v-8.5c0-7-0.5-9.4-2.3-12.9l-2.2-4.3 2.5-3.3c6.4-8.5 7-19.1 1.5-30.3-2.5-5-4.5-7.3-9.9-11.5-3.8-2.9-8.3-6.1-10-7-2.4-1.3-3.1-2.4-3.1-4.6 0-1.6-1.1-6.6-2.5-11.3-1.4-4.6-3-11.5-3.5-15.2-2.2-17.6 5.3-36.8 16.5-41.8 5.1-2.3 6.8-2.4 8.8-0.1zm441.7 17.7c6 3.1 9.8 8.4 12.5 17.7 5.3 18.3-1.8 40.4-15 46.8-5.6 2.7-13.1 2.4-17.3-0.7-4.5-3.3-8.8-10.7-10.7-18.3-6.7-27.2 11.9-55 30.5-45.5zm-292.5 57c0.9 2.5 3.5 6.8 5.6 9.6 11.2 14.1 23.9 16.1 38.2 5.9 16.1-11.6 27.2-9.4 48.7 9.4 10.1 8.9 24.6 16.2 35.2 17.7 14.3 2.1 27.1-1.9 45.2-13.8 13.2-8.8 18.6-10.7 30.1-10.8 8.1 0 9.5 0.3 13.7 2.7 3.6 2.2 5.3 4.1 7.4 8.5 4 8 4.3 14.9 1.1 24-3.3 9.3-6.8 14.3-16.4 23.3-20.2 18.9-55.6 36.4-86.8 43-14.3 3.1-36.2 3.8-48.9 1.6-34.1-5.8-70-19.3-81.8-30.6-7.6-7.3-6.4-12 2.9-12 7.3 0 17.7 3.7 39.3 14 18.6 8.9 29.2 12.8 41 15.1 9 1.8 31.5 1.5 42.6-0.4 34-6.1 65.8-25.8 79.7-49.5 4.5-7.6 6.7-9.6 8.2-7.3 0.3 0.5 2.2 1.5 4.1 2.1 2.8 1 3.8 1 4.4 0.1 1.2-2-0.1-5.9-2.9-8.7-8.1-8.3-22.9-8.6-32.1-0.7-6.3 5.4-5.5 6.6 3.7 5.8l7.6-0.8-3.4 4.9c-8.3 11.8-21.6 22.7-36.9 30.4-19 9.6-37.2 13.5-58.5 12.7-19.4-0.7-23.7-2.1-61.2-19.5-26.2-12.2-44.4-17.9-59.8-18.9-7.4-0.5-9.7-0.3-12.4 1.1-5.4 2.8-3.8 4.8 4.9 6.3 9.3 1.5 16 3.3 16 4.3 0 3.1-9 4.4-17.8 2.6-8.4-1.7-15.7-6-19.9-11.5-5.4-7-3.8-14.2 4-18.3 3.8-2.1 5.6-2.3 18.2-2.3 11 0 16.3 0.5 24.4 2.3 14 3.2 30.6 9.1 46.9 16.8 7.4 3.5 13.6 6.4 13.8 6.4 1.2 0 0-2.4-2.8-5.5-6.6-7.6-25.8-18.6-43.1-24.8-1.7-0.7-1.7-0.9 0.5-3.9 1.7-2.5 2.3-4.7 2.3-8.6 0-4.6-0.4-5.7-2.8-7.8-1.5-1.3-3.1-2.4-3.5-2.4-0.4 0-0.6 2.1-0.3 4.6 0.5 6.8-1.1 7.3-4.9 1.5-4.9-7.8-5.3-14.9-0.9-20.4 3.1-4 5.3-3.5 7.4 1.8zm-182.3 4.5c10.9 3.3 24.1 13.4 26.7 20.3 1.5 4 1.4 8.3-0.4 11.7-2.5 4.8-4.4 5.2-10 2-7.1-4-17.7-7.6-26.8-9-7.2-1.2-14.6-1-25.3 0.6-4.1 0.6-4.2 0.6-5.4-3.1-1.5-4.7-0.8-13.4 1.5-16.9 2.3-3.4 7.4-6.5 12.7-7.6 6.2-1.3 19.5-0.3 27 2zm446 11.4c7.3 6.2 19.2 8.4 28.3 5.1 2.2-0.8 4.1-1.5 4.2-1.5 0.7 0-8 14.2-13.1 21.3-22.2 31.1-52.5 54.4-89.6 69-16.4 6.5-19 6.7-8.8 0.9 16.8-9.6 31.3-21.2 41.6-33.2 13.7-16.1 24-34.9 28.8-52.7 3.4-12.7 3.2-12.3 4-12.3 0.3 0 2.4 1.6 4.6 3.4zm-452.8 27.1c3.8 0.8 11.1 3.5 16.3 6 9.9 4.8 13.6 8.6 14.9 15.1 0.8 4.4-2.6 12.1-5.8 12.9-1.4 0.4-7-0.7-13.3-2.6-9.8-2.9-12.4-3.2-23.5-3.3-10.5 0-13.5 0.4-18.8 2.2-4.9 1.7-6.7 2-7.8 1.2-1.7-1.5-5.4-11.3-5.4-14.5 0-7 5.6-14 13.8-17 5-1.8 21-1.8 29.6 0zm445.5 62.8c-17.3 16-57.2 35.5-87.5 42.7-33.3 7.9-63 6.1-78.5-4.6-3.4-2.3-6.9-6.3-6.9-7.9 0-0.3 14.5-0.4 32.3-0.3 32 0.3 32.3 0.3 45.7-2.5 33.2-7 63.6-20.7 90.3-40.8l10.2-7.7 0.3 7.7 0.3 7.6zm22.4 13.2c4.2 3.2 7.7 6.1 7.7 6.5 0 0.3-2.1 1.2-4.7 1.9-14.5 3.8-30.6 13.3-55.8 32.7-9.6 7.4-22.9 17-29.7 21.5-23.6 15.4-51.1 26.7-74.4 30.4l-11.1 1.8-5.8-2.7c-12.3-5.6-27.4-19.1-36.5-32.6-4.4-6.5-10-20.4-10-25 0-1.9 1.4-3.4 6.1-6.7l6.2-4.2 2.1 2.7c23 29.3 88.6 27.8 150.8-3.4 12-6 24.2-13.6 35.8-22.3 5.2-3.9 9.9-7 10.5-6.7 0.5 0.2 4.5 3 8.8 6.1zm38.8 19.3c7.4 2.1 13.5 5.3 19.3 10.4l4 3.5-2.8 4.7c-8.7 14.9-32.4 42.7-50.5 59.2-14.7 13.6-36 30.6-37.4 30.1-1.9-0.6-6.6-17-7.5-26.6-2.7-26.7 6.5-54.1 23.1-68.6 13.7-12 35.2-17.3 51.8-12.7zm-267.3 33.9c9.1 22 33.4 46 54.4 53.8 4.2 1.5 5.7 1.6 13 0.6 37.9-5.4 74.6-22.8 112.6-53.4 3.9-3.2 7.2-5.7 7.2-5.4 0 0.2-1.1 3.6-2.5 7.7-4 11.7-5.5 21-5.5 33.8 0 13.8 1.8 24.9 6.2 37.5 1.6 4.9 2.9 9 2.7 9.1-0.2 0.2-5.6 3.6-11.9 7.6-22.3 14.3-52.6 29.4-76.2 38.1l-10.7 3.9-10.4-3.9c-27.4-10.3-57.6-25.7-81.8-41.7-14-9.2-32.6-23.2-33.3-24.9-1.3-3.4 14.4-40.6 23-54.5 8.7-14.2 9.8-15.9 10-15.7 0.1 0.1 1.5 3.5 3.2 7.4zm-47.8 51.9c0 0.8-0.5 1.2-1 0.9-0.6-0.4-0.8-1.1-0.5-1.6 0.9-1.4 1.5-1.1 1.5 0.7z"/>
            <path fill="#ffffff" d="m352.3 177.2c-3.2 3.5-22.3 50.4-22.3 54.8 0 2.6 4 6.8 7.1 7.5 4.9 1.2 7-2.4 17.4-28.3 5.3-13.4 9.9-25.9 10.2-27.7 1.1-6.8-7.8-11.3-12.4-6.3z"/>
            <path fill="#ffffff" d="m383.7 193.1c-0.9 0.6-3.1 4-4.8 7.7-4.8 10.6-15.9 38.7-15.9 40.4 0 3.1 4 6.8 7.3 6.8 3.8 0 5-0.7 6.7-4 3.8-7.2 17-41.9 17-44.7 0-5.7-5.5-9-10.3-6.2z"/>
            <path fill="#ffffff" d="m412.4 213.5c-1.2 0.8-2.7 2.9-3.4 4.7-0.8 1.8-4.2 10.2-7.7 18.6-3.5 8.4-6.3 16.3-6.3 17.6 0 3.2 4 6.6 7.8 6.6 4.2 0 5.1-1.5 13.4-22.3 8.1-20.5 8.4-22.8 3.1-25.6-2.9-1.5-4.4-1.4-6.9 0.4z"/>
            <path fill="#ffffff" d="m295.3 190c-2.5 1-4.1 3.8-7.9 13.6-4.1 10.7-7.3 21.4-8 26.7-0.8 5.7 1.2 8.7 5.7 8.7 3.9 0 5.2-2.4 9.5-16.8 1.9-6.6 4.6-14.9 6-18.3 3-7.9 3.1-11.3 0.2-13.3-2.5-1.8-2.5-1.8-5.5-0.6z"/>
            <path fill="#ffffff" d="m264.5 218.4c-1.7 2.5-6.8 16.8-7.9 22.2-0.5 2.3-0.2 3.7 1.3 5.5 1.6 2 2.3 2.2 4.7 1.4 2.5-0.9 3.3-2.3 6.1-10 3.9-11.1 4.9-16.6 3.4-19.4-1.6-2.9-5.6-2.7-7.6 0.3z"/>
            <path fill="#ffffff" d="m397 309.9c-11.5 3.8-22 13.1-34 30.1-4.1 5.8-8.7 12.1-10.3 14-3.6 4.3-9.4 8-12.5 8-3.7 0-6.9-4-7.7-9.8-0.8-5.8-2.2-7.4-4.1-4.8-2.1 2.9-2.7 9.3-1.4 14.7 1.5 6.4 5.9 10 12.9 10.7 4.1 0.4 5.9-0.1 11.2-2.9 6.8-3.7 12.8-10.2 22.4-24.4 16-23.8 33.4-31.4 46.1-20.2 2 1.7 5.4 5.5 7.6 8.4 5.6 7.6 7.3 5.8 4.3-4.4-2.1-7-7.6-13.8-13.7-16.9-5.4-2.7-16.2-4-20.8-2.5z"/>
            <path fill="#ffffff" d="m390.3 359.1c-11.2 1.1-20.4 7.1-31.1 20.3-8.8 10.8-9.9 13.7-6.5 17.1 2.3 2.3 6.7 1.5 12.8-2.4 2.7-1.7 8.5-4.5 13-6.3 7-2.8 9.2-3.2 17.5-3.1 7.6 0 11.2 0.5 17.9 2.7 8.1 2.7 8.5 2.7 9.8 1 1.8-2.4 1.6-3.7-0.8-6.8-2.9-3.7-10.8-7.5-19.2-9.2-7.8-1.7-17.2-0.8-24.7 2.2-2.3 0.9-4.3 1.4-4.6 1.1-1.7-1.7 16.4-12.7 21-12.7 2.2 0 5.6-1.8 5.6-2.9 0-1.3-3.9-1.7-10.7-1z"/>
            <path fill="#ffffff" d="m320.2 426.5c-3.3 2.7-5.7 7.7-4.9 9.9 0.4 1 1.5 1.2 4.9 0.5 2.4-0.4 4.6-0.8 4.9-0.9 0.3 0 1.5-0.9 2.7-2 2.8-2.6 2.9-7.5 0.3-9-3-1.5-4.7-1.2-7.9 1.5z"/>
        </g>

        <!-- Header -->
        <text x="100" y="32" fill="#a1a1aa" font-family="system-ui, -apple-system, Segoe UI, sans-serif" font-size="11" font-weight="600" letter-spacing="1.5" style="text-transform: uppercase;">WARDEN QUALITY</text>

        <!-- Score Display (Improved Alignment) -->
        <text x="100" y="72" fill="#fff" font-family="system-ui, -apple-system, Segoe UI, sans-serif" font-weight="700">
            <tspan font-size="36">{score:.1f}</tspan>
            <tspan font-size="18" fill="#71717a" font-weight="400" dx="2">/ 10</tspan>
        </text>

        <!-- Status Badge (Right Aligned) -->
        <rect x="284" y="20" width="92" height="24" rx="6" fill="{gradient_start}" fill-opacity="0.15" stroke="{gradient_start}" stroke-opacity="0.3" stroke-width="1"/>
        <text x="330" y="36" fill="{gradient_start}" font-family="system-ui, -apple-system, Segoe UI, sans-serif" font-size="10" font-weight="700" text-anchor="middle" letter-spacing="0.5">{status_text}</text>

        <!-- Progress Bar Section -->
        <line x1="284" y1="64" x2="376" y2="64" stroke="#3f3f46" stroke-width="4" stroke-linecap="round" stroke-opacity="0.5"/>
        <line x1="284" y1="64" x2="{284 + (92 * (score / 10.0))}" y2="64" stroke="url(#scoreGrad)" stroke-width="4" stroke-linecap="round"/>

        <!-- Footer Meta -->
        <text x="376" y="84" fill="#52525b" font-family="system-ui, -apple-system, Segoe UI, sans-serif" font-size="9" text-anchor="end" letter-spacing="0.5">AI-NATIVE GUARDIAN</text>
    </a>
</svg>"""

        # Atomic write
        lock_path = output_path.parent / f".{output_path.name}.lock"
        with file_lock(lock_path):
            temp_fd, temp_path = tempfile.mkstemp(suffix=".svg", dir=output_path.parent, prefix=".tmp_badge_")
            try:
                with os.fdopen(temp_fd, "w") as f:
                    f.write(svg_content)
                os.replace(temp_path, output_path)
            except Exception:
                with suppress(OSError):
                    os.unlink(temp_path)
                raise

    def generate_junit_report(
        self, scan_results: dict[str, Any], output_path: Path, base_path: Path | None = None
    ) -> None:
        """
        Generate JUnit XML report for general CI/CD compatibility.
        """
        import xml.etree.ElementTree as ET

        # Use inplace=False to create a copy for sanitization
        sanitized_results = self._sanitize_paths(scan_results, base_path, inplace=False)

        testsuites = ET.Element("testsuites", name="Warden Scan")

        frame_results = sanitized_results.get("frame_results", sanitized_results.get("frameResults", []))

        testsuite = ET.SubElement(
            testsuites,
            "testsuite",
            name="security_validation",
            tests=str(len(frame_results)),
            failures=str(sanitized_results.get("frames_failed", sanitized_results.get("framesFailed", 0))),
            errors="0",
            skipped=str(sanitized_results.get("frames_skipped", sanitized_results.get("framesSkipped", 0))),
            time=str(sanitized_results.get("duration", 0)),
        )

        for frame in frame_results:
            name = frame.get("frame_name", frame.get("frameName", "Unknown Frame"))
            classname = f"warden.{frame.get('frame_id', frame.get('frameId', 'generic'))}"
            duration = str(frame.get("duration", 0))

            testcase = ET.SubElement(testsuite, "testcase", name=name, classname=classname, time=duration)

            status = frame.get("status")
            if status == "failed":
                findings = frame.get("findings", [])
                message = f"Found {len(findings)} issues in {name}"
                failure_text = "\\n".join(
                    [f"- [{f.get('severity')}] {f.get('location')}: {f.get('message')}" for f in findings]
                )

                failure = ET.SubElement(testcase, "failure", message=message, type="SecurityViolation")
                failure.text = failure_text
            elif status == "skipped":
                ET.SubElement(testcase, "skipped")

        # Atomic write: write to temp file first, then replace atomically
        tree = ET.ElementTree(testsuites)
        temp_fd, temp_path = tempfile.mkstemp(suffix=".xml", dir=output_path.parent, prefix=".tmp_")
        try:
            # Close the file descriptor and use path-based write
            os.close(temp_fd)
            tree.write(temp_path, encoding="utf-8", xml_declaration=True)
            os.replace(temp_path, output_path)  # Atomic on Unix/Linux
        except Exception:
            # Clean up temp file on failure
            with suppress(OSError):
                os.unlink(temp_path)
            raise

    def generate_html_report(
        self, scan_results: dict[str, Any], output_path: Path, base_path: Path | None = None
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
        self, scan_results: dict[str, Any], output_path: Path, base_path: Path | None = None
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
        from warden.shared.infrastructure.logging import get_logger

        logger = get_logger(__name__)

        # OBSERVABILITY: Log PDF generation start
        logger.info(
            "pdf_generation_started", output_path=str(output_path), findings_count=scan_results.get("total_findings", 0)
        )

        # Use inplace=False to create a copy for sanitization
        sanitized_results = self._sanitize_paths(scan_results, base_path, inplace=False)

        # First generate HTML content using the helper
        html_content = self.html_generator._create_html_content(sanitized_results)

        try:
            # Try to use WeasyPrint if available
            from weasyprint import CSS, HTML
        except ImportError:
            logger.error("pdf_generation_failed", reason="weasyprint_not_installed")
            raise RuntimeError("PDF generation requires WeasyPrint. Install with: pip install weasyprint")

        # Convert HTML to PDF using atomic write
        temp_fd, temp_path = tempfile.mkstemp(suffix=".pdf", dir=output_path.parent, prefix=".tmp_")
        try:
            # Close the file descriptor as WeasyPrint writes to path directly
            os.close(temp_fd)
            HTML(string=html_content).write_pdf(
                temp_path, stylesheets=[CSS(string=self.html_generator.get_pdf_styles())]
            )
            os.replace(temp_path, output_path)  # Atomic on Unix/Linux

            # OBSERVABILITY: Log successful PDF generation
            logger.info(
                "pdf_generated", output_path=str(output_path), file_size_kb=round(output_path.stat().st_size / 1024, 2)
            )
        except Exception as e:
            # Clean up temp file on failure
            with suppress(OSError):
                os.unlink(temp_path)

            # OBSERVABILITY: Log failure with context
            logger.error(
                "pdf_generation_failed", output_path=str(output_path), error=str(e), error_type=type(e).__name__
            )
            # Re-raise with more context
            raise RuntimeError(f"PDF generation failed: {e!s}") from e
