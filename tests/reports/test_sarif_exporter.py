"""
Tests for SARIF Exporter.

Tests SARIF 2.1.0 format generation, schema compliance, and GitHub Security integration.
"""

import json
from pathlib import Path
from unittest.mock import Mock, patch
import pytest

from warden.reports.sarif_exporter import SARIFExporter
from warden.issues.domain.models import WardenIssue
from warden.issues.domain.enums import IssueSeverity
from warden.pipeline.domain.models import PipelineResult


class TestSARIFExporterInitialization:
    """Test SARIF exporter initialization."""

    def test_default_initialization(self):
        """Test default initialization."""
        exporter = SARIFExporter()

        assert exporter.tool_name == "Warden"
        assert exporter.tool_version == "1.0.0"
        assert exporter.tool_uri == "https://github.com/ibrahimcaglar/warden-core"

    def test_custom_initialization(self):
        """Test custom tool configuration."""
        exporter = SARIFExporter(
            tool_name="Custom Warden",
            tool_version="2.0.0",
            tool_uri="https://example.com/warden",
        )

        assert exporter.tool_name == "Custom Warden"
        assert exporter.tool_version == "2.0.0"
        assert exporter.tool_uri == "https://example.com/warden"


class TestSARIFDocumentStructure:
    """Test SARIF document structure and schema compliance."""

    def test_document_schema_version(self):
        """Test SARIF schema version."""
        exporter = SARIFExporter()

        result = Mock(spec=PipelineResult)
        result.pipeline_id = "test-pipeline"
        result.all_issues = []

        sarif = exporter.export_to_sarif(result)

        assert sarif["$schema"] == "https://json.schemastore.org/sarif-2.1.0.json"
        assert sarif["version"] == "2.1.0"

    def test_document_has_runs(self):
        """Test SARIF document has runs array."""
        exporter = SARIFExporter()

        result = Mock(spec=PipelineResult)
        result.pipeline_id = "test-pipeline"
        result.all_issues = []

        sarif = exporter.export_to_sarif(result)

        assert "runs" in sarif
        assert isinstance(sarif["runs"], list)
        assert len(sarif["runs"]) == 1

    def test_run_structure(self):
        """Test SARIF run structure."""
        exporter = SARIFExporter()

        result = Mock(spec=PipelineResult)
        result.pipeline_id = "test-pipeline"
        result.all_issues = []

        sarif = exporter.export_to_sarif(result)
        run = sarif["runs"][0]

        assert "tool" in run
        assert "results" in run
        assert "columnKind" in run
        assert run["columnKind"] == "utf16CodeUnits"


class TestSARIFToolMetadata:
    """Test SARIF tool metadata."""

    def test_tool_driver_metadata(self):
        """Test tool driver metadata."""
        exporter = SARIFExporter()

        result = Mock(spec=PipelineResult)
        result.pipeline_id = "test"
        result.all_issues = []

        sarif = exporter.export_to_sarif(result)
        driver = sarif["runs"][0]["tool"]["driver"]

        assert driver["name"] == "Warden"
        assert driver["version"] == "1.0.0"
        assert driver["informationUri"] == "https://github.com/ibrahimcaglar/warden-core"
        assert driver["organization"] == "Warden Security"

    def test_tool_rules_defined(self):
        """Test that tool rules are defined."""
        exporter = SARIFExporter()

        result = Mock(spec=PipelineResult)
        result.pipeline_id = "test"
        result.all_issues = []

        sarif = exporter.export_to_sarif(result)
        rules = sarif["runs"][0]["tool"]["driver"]["rules"]

        assert isinstance(rules, list)
        assert len(rules) > 0

        # Check for expected rule IDs
        rule_ids = [rule["id"] for rule in rules]
        assert "warden/security/sql-injection" in rule_ids
        assert "warden/security/xss" in rule_ids
        assert "warden/security/secrets" in rule_ids


class TestSARIFResultGeneration:
    """Test SARIF result generation from Warden issues."""

    def test_generate_result_for_critical_issue(self):
        """Test SARIF result for critical issue."""
        exporter = SARIFExporter()

        issue = Mock(spec=WardenIssue)
        issue.id = "W001"
        issue.severity = IssueSeverity.CRITICAL
        issue.message = "SQL injection vulnerability"
        issue.file_path = "src/api.py"
        issue.line = 42
        issue.rule_id = "warden/security/sql-injection"

        result = Mock(spec=PipelineResult)
        result.pipeline_id = "test"
        result.all_issues = [issue]

        sarif = exporter.export_to_sarif(result)
        results = sarif["runs"][0]["results"]

        assert len(results) == 1
        assert results[0]["ruleId"] == "warden/security/sql-injection"
        assert results[0]["level"] == "error"
        assert results[0]["message"]["text"] == "SQL injection vulnerability"

    def test_severity_mapping(self):
        """Test severity to SARIF level mapping."""
        exporter = SARIFExporter()

        test_cases = [
            (IssueSeverity.CRITICAL, "error"),
            (IssueSeverity.HIGH, "error"),
            (IssueSeverity.MEDIUM, "warning"),
            (IssueSeverity.LOW, "note"),
        ]

        for severity, expected_level in test_cases:
            issue = Mock(spec=WardenIssue)
            issue.severity = severity
            issue.message = "Test issue"
            issue.file_path = "test.py"
            issue.line = 1

            result = Mock(spec=PipelineResult)
            result.pipeline_id = "test"
            result.all_issues = [issue]

            sarif = exporter.export_to_sarif(result)
            sarif_result = sarif["runs"][0]["results"][0]

            assert sarif_result["level"] == expected_level


class TestSARIFLocationInformation:
    """Test SARIF location information."""

    def test_physical_location_with_file(self):
        """Test physical location with file path."""
        exporter = SARIFExporter()

        issue = Mock(spec=WardenIssue)
        issue.severity = IssueSeverity.HIGH
        issue.message = "Test"
        issue.file_path = "src/module/file.py"
        issue.line = 10

        result = Mock(spec=PipelineResult)
        result.pipeline_id = "test"
        result.all_issues = [issue]

        sarif = exporter.export_to_sarif(result)
        location = sarif["runs"][0]["results"][0]["locations"][0]

        assert "physicalLocation" in location
        assert location["physicalLocation"]["artifactLocation"]["uri"] == "src/module/file.py"
        assert location["physicalLocation"]["artifactLocation"]["uriBaseId"] == "%SRCROOT%"

    def test_region_with_line_number(self):
        """Test region with line number."""
        exporter = SARIFExporter()

        issue = Mock(spec=WardenIssue)
        issue.severity = IssueSeverity.MEDIUM
        issue.message = "Test"
        issue.file_path = "test.py"
        issue.line = 42
        issue.end_line = 45

        result = Mock(spec=PipelineResult)
        result.pipeline_id = "test"
        result.all_issues = [issue]

        sarif = exporter.export_to_sarif(result)
        region = sarif["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["region"]

        assert region["startLine"] == 42
        assert region["endLine"] == 45

    def test_region_with_columns(self):
        """Test region with column information."""
        exporter = SARIFExporter()

        issue = Mock(spec=WardenIssue)
        issue.severity = IssueSeverity.HIGH
        issue.message = "Test"
        issue.file_path = "test.py"
        issue.line = 10
        issue.column = 5
        issue.end_column = 15

        result = Mock(spec=PipelineResult)
        result.pipeline_id = "test"
        result.all_issues = [issue]

        sarif = exporter.export_to_sarif(result)
        region = sarif["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["region"]

        assert region["startColumn"] == 5
        assert region["endColumn"] == 15

    def test_code_snippet_in_region(self):
        """Test code snippet inclusion."""
        exporter = SARIFExporter()

        issue = Mock(spec=WardenIssue)
        issue.severity = IssueSeverity.CRITICAL
        issue.message = "Test"
        issue.file_path = "test.py"
        issue.line = 1
        issue.code_snippet = "def unsafe_query(user_input):"

        result = Mock(spec=PipelineResult)
        result.pipeline_id = "test"
        result.all_issues = [issue]

        sarif = exporter.export_to_sarif(result)
        region = sarif["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["region"]

        assert "snippet" in region
        assert region["snippet"]["text"] == "def unsafe_query(user_input):"


class TestSARIFFingerprinting:
    """Test SARIF fingerprinting for deduplication."""

    def test_fingerprint_generation(self):
        """Test fingerprint generation."""
        exporter = SARIFExporter()

        issue = Mock(spec=WardenIssue)
        issue.severity = IssueSeverity.CRITICAL
        issue.message = "Test issue"
        issue.file_path = "test.py"
        issue.line = 42

        result = Mock(spec=PipelineResult)
        result.pipeline_id = "test"
        result.all_issues = [issue]

        sarif = exporter.export_to_sarif(result)
        sarif_result = sarif["runs"][0]["results"][0]

        assert "partialFingerprints" in sarif_result
        assert "primaryLocationLineHash" in sarif_result["partialFingerprints"]
        assert len(sarif_result["partialFingerprints"]["primaryLocationLineHash"]) == 16

    def test_consistent_fingerprints(self):
        """Test that same issue generates same fingerprint."""
        exporter = SARIFExporter()

        # Create two identical issues
        issue1 = Mock(spec=WardenIssue)
        issue1.severity = IssueSeverity.HIGH
        issue1.message = "Duplicate issue"
        issue1.file_path = "test.py"
        issue1.line = 10

        issue2 = Mock(spec=WardenIssue)
        issue2.severity = IssueSeverity.HIGH
        issue2.message = "Duplicate issue"
        issue2.file_path = "test.py"
        issue2.line = 10

        result1 = Mock(spec=PipelineResult)
        result1.pipeline_id = "test"
        result1.all_issues = [issue1]

        result2 = Mock(spec=PipelineResult)
        result2.pipeline_id = "test"
        result2.all_issues = [issue2]

        sarif1 = exporter.export_to_sarif(result1)
        sarif2 = exporter.export_to_sarif(result2)

        fingerprint1 = sarif1["runs"][0]["results"][0]["partialFingerprints"]["primaryLocationLineHash"]
        fingerprint2 = sarif2["runs"][0]["results"][0]["partialFingerprints"]["primaryLocationLineHash"]

        assert fingerprint1 == fingerprint2


class TestSARIFFileOutput:
    """Test SARIF file output."""

    @patch("pathlib.Path.write_text")
    @patch("pathlib.Path.mkdir")
    def test_export_to_file(self, mock_mkdir, mock_write):
        """Test exporting SARIF to file."""
        exporter = SARIFExporter()

        result = Mock(spec=PipelineResult)
        result.pipeline_id = "test"
        result.all_issues = []

        output_path = Path("/tmp/warden-sarif.json")
        exporter.export_to_sarif(result, output_path=output_path)

        # Verify directory creation
        mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)

        # Verify file write
        mock_write.assert_called_once()
        written_content = mock_write.call_args[0][0]

        # Verify it's valid JSON
        sarif_data = json.loads(written_content)
        assert sarif_data["version"] == "2.1.0"

    def test_sarif_json_serializable(self):
        """Test that SARIF output is JSON serializable."""
        exporter = SARIFExporter()

        issue = Mock(spec=WardenIssue)
        issue.severity = IssueSeverity.CRITICAL
        issue.message = "Test"
        issue.file_path = "test.py"
        issue.line = 1

        result = Mock(spec=PipelineResult)
        result.pipeline_id = "test"
        result.all_issues = [issue]

        sarif = exporter.export_to_sarif(result)

        # Should not raise exception
        json_string = json.dumps(sarif, indent=2)
        assert isinstance(json_string, str)

        # Should be deserializable
        parsed = json.loads(json_string)
        assert parsed["version"] == "2.1.0"


class TestSARIFRuleDefinitions:
    """Test SARIF rule definitions."""

    def test_sql_injection_rule(self):
        """Test SQL injection rule definition."""
        exporter = SARIFExporter()
        rules = exporter._create_rules()

        sql_rule = next((r for r in rules if r["id"] == "warden/security/sql-injection"), None)

        assert sql_rule is not None
        assert sql_rule["name"] == "SQLInjectionDetection"
        assert "SQL injection" in sql_rule["shortDescription"]["text"]
        assert sql_rule["defaultConfiguration"]["level"] == "error"

    def test_xss_rule(self):
        """Test XSS rule definition."""
        exporter = SARIFExporter()
        rules = exporter._create_rules()

        xss_rule = next((r for r in rules if r["id"] == "warden/security/xss"), None)

        assert xss_rule is not None
        assert "XSS" in xss_rule["shortDescription"]["text"] or "cross-site" in xss_rule["shortDescription"]["text"].lower()

    def test_secrets_rule(self):
        """Test hardcoded secrets rule definition."""
        exporter = SARIFExporter()
        rules = exporter._create_rules()

        secrets_rule = next((r for r in rules if r["id"] == "warden/security/secrets"), None)

        assert secrets_rule is not None
        assert "secrets" in secrets_rule["shortDescription"]["text"].lower() or "credentials" in secrets_rule["shortDescription"]["text"].lower()


class TestSARIFWithMultipleIssues:
    """Test SARIF generation with multiple issues."""

    def test_multiple_issues_export(self):
        """Test exporting multiple issues."""
        exporter = SARIFExporter()

        issues = [
            Mock(
                spec=WardenIssue,
                severity=IssueSeverity.CRITICAL,
                message="SQL injection",
                file_path="api.py",
                line=10,
            ),
            Mock(
                spec=WardenIssue,
                severity=IssueSeverity.HIGH,
                message="XSS vulnerability",
                file_path="views.py",
                line=50,
            ),
            Mock(
                spec=WardenIssue,
                severity=IssueSeverity.MEDIUM,
                message="Missing validation",
                file_path="utils.py",
                line=100,
            ),
        ]

        result = Mock(spec=PipelineResult)
        result.pipeline_id = "test"
        result.all_issues = issues

        sarif = exporter.export_to_sarif(result)
        results = sarif["runs"][0]["results"]

        assert len(results) == 3
        assert results[0]["level"] == "error"  # Critical
        assert results[1]["level"] == "error"  # High
        assert results[2]["level"] == "warning"  # Medium


class TestSARIFEdgeCases:
    """Test SARIF generation edge cases."""

    def test_issue_without_file_path(self):
        """Test issue without file path."""
        exporter = SARIFExporter()

        issue = Mock(spec=WardenIssue)
        issue.severity = IssueSeverity.MEDIUM
        issue.message = "General warning"
        # No file_path attribute

        result = Mock(spec=PipelineResult)
        result.pipeline_id = "test"
        result.all_issues = [issue]

        sarif = exporter.export_to_sarif(result)
        sarif_result = sarif["runs"][0]["results"][0]

        # Should still generate result
        assert sarif_result is not None
        assert sarif_result["message"]["text"] == "General warning"

    def test_issue_without_rule_id(self):
        """Test issue without rule ID."""
        exporter = SARIFExporter()

        issue = Mock(spec=WardenIssue)
        issue.severity = IssueSeverity.CRITICAL
        issue.message = "Security issue"
        issue.file_path = "test.py"
        issue.line = 1
        # No rule_id attribute

        result = Mock(spec=PipelineResult)
        result.pipeline_id = "test"
        result.all_issues = [issue]

        sarif = exporter.export_to_sarif(result)
        sarif_result = sarif["runs"][0]["results"][0]

        # Should use default rule based on severity
        assert "warden/" in sarif_result["ruleId"]

    def test_empty_issue_list(self):
        """Test with empty issue list."""
        exporter = SARIFExporter()

        result = Mock(spec=PipelineResult)
        result.pipeline_id = "test"
        result.all_issues = []

        sarif = exporter.export_to_sarif(result)
        results = sarif["runs"][0]["results"]

        assert results == []

    def test_issue_with_special_characters_in_message(self):
        """Test issue with special characters in message."""
        exporter = SARIFExporter()

        issue = Mock(spec=WardenIssue)
        issue.severity = IssueSeverity.HIGH
        issue.message = 'Error: "quoted" value with <tags> & symbols'
        issue.file_path = "test.py"
        issue.line = 1

        result = Mock(spec=PipelineResult)
        result.pipeline_id = "test"
        result.all_issues = [issue]

        sarif = exporter.export_to_sarif(result)

        # Should be valid JSON (no exception)
        json.dumps(sarif)
