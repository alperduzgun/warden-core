"""
SARIF (Static Analysis Results Interchange Format) Exporter for Warden.

Converts Warden analysis results to SARIF 2.1.0 format for:
- GitHub Code Scanning integration
- Security tab visualization
- IDE integration (VS Code, IntelliJ)
- SARIF Viewer tools

Reference: https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html
"""

import json
from typing import Dict, Any, List, Optional
from pathlib import Path
from datetime import datetime

from warden.issues.domain.models import WardenIssue
from warden.issues.domain.enums import IssueSeverity
from warden.pipeline.domain.models import PipelineResult


class SARIFExporter:
    """Export Warden results to SARIF 2.1.0 format."""

    SARIF_VERSION = "2.1.0"
    SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"

    # SARIF severity levels
    SARIF_LEVEL_MAP = {
        IssueSeverity.CRITICAL: "error",
        IssueSeverity.HIGH: "error",
        IssueSeverity.MEDIUM: "warning",
        IssueSeverity.LOW: "note",
    }

    def __init__(
        self,
        tool_name: str = "Warden",
        tool_version: str = "1.0.0",
        tool_uri: str = "https://github.com/ibrahimcaglar/warden-core",
    ):
        """
        Initialize SARIF exporter.

        Args:
            tool_name: Name of the analysis tool
            tool_version: Tool version
            tool_uri: Tool information URI
        """
        self.tool_name = tool_name
        self.tool_version = tool_version
        self.tool_uri = tool_uri

    def export_to_sarif(
        self,
        result: PipelineResult,
        output_path: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """
        Export pipeline result to SARIF format.

        Args:
            result: Pipeline execution result
            output_path: Optional path to save SARIF file

        Returns:
            SARIF document as dictionary
        """
        sarif_document = self._create_sarif_document(result)

        if output_path:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(sarif_document, indent=2))

        return sarif_document

    def _create_sarif_document(self, result: PipelineResult) -> Dict[str, Any]:
        """
        Create complete SARIF document.

        Args:
            result: Pipeline execution result

        Returns:
            SARIF document dictionary
        """
        return {
            "$schema": self.SARIF_SCHEMA,
            "version": self.SARIF_VERSION,
            "runs": [self._create_run(result)],
        }

    def _create_run(self, result: PipelineResult) -> Dict[str, Any]:
        """
        Create SARIF run object.

        Args:
            result: Pipeline execution result

        Returns:
            SARIF run dictionary
        """
        return {
            "tool": self._create_tool(),
            "results": self._create_results(result.all_issues),
            "columnKind": "utf16CodeUnits",
            "properties": {
                "wardenPipelineId": result.pipeline_id,
                "wardenRunId": getattr(result, "run_id", "unknown"),
                "executionTimestamp": datetime.now().isoformat(),
            },
        }

    def _create_tool(self) -> Dict[str, Any]:
        """
        Create SARIF tool object.

        Returns:
            SARIF tool dictionary
        """
        return {
            "driver": {
                "name": self.tool_name,
                "version": self.tool_version,
                "informationUri": self.tool_uri,
                "organization": "Warden Security",
                "semanticVersion": self.tool_version,
                "rules": self._create_rules(),
            }
        }

    def _create_rules(self) -> List[Dict[str, Any]]:
        """
        Create SARIF rule definitions.

        Returns:
            List of SARIF rule dictionaries
        """
        # Define common Warden rules
        return [
            {
                "id": "warden/security/sql-injection",
                "name": "SQLInjectionDetection",
                "shortDescription": {"text": "Potential SQL injection vulnerability"},
                "fullDescription": {
                    "text": "Code may be vulnerable to SQL injection attacks. Use parameterized queries."
                },
                "defaultConfiguration": {"level": "error"},
                "help": {
                    "text": "Use parameterized queries or prepared statements to prevent SQL injection.",
                    "markdown": "Use parameterized queries or prepared statements to prevent SQL injection. See: https://owasp.org/www-community/attacks/SQL_Injection",
                },
            },
            {
                "id": "warden/security/xss",
                "name": "CrossSiteScriptingDetection",
                "shortDescription": {
                    "text": "Potential cross-site scripting vulnerability"
                },
                "fullDescription": {
                    "text": "Code may be vulnerable to XSS attacks. Sanitize user input before rendering."
                },
                "defaultConfiguration": {"level": "error"},
            },
            {
                "id": "warden/security/secrets",
                "name": "HardcodedSecretsDetection",
                "shortDescription": {"text": "Hardcoded secrets or credentials detected"},
                "fullDescription": {
                    "text": "Secrets should not be hardcoded in source code. Use environment variables or secret management."
                },
                "defaultConfiguration": {"level": "error"},
            },
            {
                "id": "warden/chaos/network-failure",
                "name": "NetworkFailureHandling",
                "shortDescription": {"text": "Missing network failure handling"},
                "fullDescription": {
                    "text": "Code should handle network failures gracefully with retries and timeouts."
                },
                "defaultConfiguration": {"level": "warning"},
            },
            {
                "id": "warden/fuzz/input-validation",
                "name": "InputValidation",
                "shortDescription": {"text": "Insufficient input validation"},
                "fullDescription": {
                    "text": "User input must be validated for null, empty, and edge cases."
                },
                "defaultConfiguration": {"level": "warning"},
            },
            {
                "id": "warden/property/idempotency",
                "name": "IdempotencyViolation",
                "shortDescription": {"text": "Operation is not idempotent"},
                "fullDescription": {
                    "text": "Operation should be idempotent for safe retries and consistency."
                },
                "defaultConfiguration": {"level": "note"},
            },
        ]

    def _create_results(self, issues: List[WardenIssue]) -> List[Dict[str, Any]]:
        """
        Create SARIF results from Warden issues.

        Args:
            issues: List of Warden issues

        Returns:
            List of SARIF result dictionaries
        """
        sarif_results = []

        for issue in issues:
            sarif_result = self._create_result(issue)
            if sarif_result:
                sarif_results.append(sarif_result)

        return sarif_results

    def _create_result(self, issue: WardenIssue) -> Optional[Dict[str, Any]]:
        """
        Create SARIF result from a single issue.

        Args:
            issue: Warden issue

        Returns:
            SARIF result dictionary or None
        """
        # Map severity to SARIF level
        level = self.SARIF_LEVEL_MAP.get(issue.severity, "note")

        # Build result object
        result = {
            "ruleId": self._get_rule_id(issue),
            "level": level,
            "message": {"text": issue.message},
            "locations": [self._create_location(issue)],
        }

        # Add optional properties
        if hasattr(issue, "id") and issue.id:
            result["guid"] = issue.id

        if hasattr(issue, "code_snippet") and issue.code_snippet:
            result["codeFlows"] = [self._create_code_flow(issue)]

        # Add fingerprint for deduplication
        result["partialFingerprints"] = {
            "primaryLocationLineHash": self._create_fingerprint(issue)
        }

        return result

    def _get_rule_id(self, issue: WardenIssue) -> str:
        """
        Get SARIF rule ID for an issue.

        Args:
            issue: Warden issue

        Returns:
            Rule ID string
        """
        if hasattr(issue, "rule_id") and issue.rule_id:
            return issue.rule_id

        # Default rule based on severity
        if issue.severity == IssueSeverity.CRITICAL:
            return "warden/security/critical"
        elif issue.severity == IssueSeverity.HIGH:
            return "warden/security/high"
        else:
            return "warden/general/issue"

    def _create_location(self, issue: WardenIssue) -> Dict[str, Any]:
        """
        Create SARIF location object.

        Args:
            issue: Warden issue

        Returns:
            SARIF location dictionary
        """
        location = {"physicalLocation": {}}

        # Artifact location (file)
        if hasattr(issue, "file_path") and issue.file_path:
            location["physicalLocation"]["artifactLocation"] = {
                "uri": issue.file_path,
                "uriBaseId": "%SRCROOT%",
            }

        # Region (line/column)
        region = {}
        if hasattr(issue, "line") and issue.line:
            region["startLine"] = issue.line

        if hasattr(issue, "end_line") and issue.end_line:
            region["endLine"] = issue.end_line

        if hasattr(issue, "column") and issue.column:
            region["startColumn"] = issue.column

        if hasattr(issue, "end_column") and issue.end_column:
            region["endColumn"] = issue.end_column

        # Add code snippet
        if hasattr(issue, "code_snippet") and issue.code_snippet:
            region["snippet"] = {"text": issue.code_snippet}

        if region:
            location["physicalLocation"]["region"] = region

        return location

    def _create_code_flow(self, issue: WardenIssue) -> Dict[str, Any]:
        """
        Create SARIF code flow for an issue.

        Args:
            issue: Warden issue

        Returns:
            SARIF code flow dictionary
        """
        return {
            "threadFlows": [
                {
                    "locations": [
                        {
                            "location": self._create_location(issue),
                            "state": {
                                "severity": issue.severity.name,
                            },
                        }
                    ]
                }
            ]
        }

    def _create_fingerprint(self, issue: WardenIssue) -> str:
        """
        Create fingerprint for issue deduplication.

        Args:
            issue: Warden issue

        Returns:
            Fingerprint string (hash)
        """
        import hashlib

        # Create hash from file path, line, and message
        fingerprint_data = f"{getattr(issue, 'file_path', '')}:{getattr(issue, 'line', 0)}:{issue.message}"
        return hashlib.sha256(fingerprint_data.encode()).hexdigest()[:16]
