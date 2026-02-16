"""
Tests for type safety improvements in result aggregation and pipeline.

Validates fixes from BATCH 1: Type Safety Foundation.
"""

from datetime import datetime
from pathlib import Path

import pytest

from warden.pipeline.application.orchestrator.result_aggregator import (
    ResultAggregator,
    normalize_finding_to_dict,
)
from warden.pipeline.domain.models import ValidationPipeline
from warden.pipeline.domain.pipeline_context import PipelineContext
from warden.validation.domain.frame import Finding


def create_test_context() -> PipelineContext:
    """Create a test PipelineContext with required fields."""
    return PipelineContext(
        pipeline_id="test-123",
        started_at=datetime.now(),
        file_path=Path("test.py"),
        source_code="# test code",
    )


class TestNormalizeFindingToDict:
    """Test normalize_finding_to_dict helper function."""

    def test_normalize_none_finding(self):
        """Test that None finding returns safe default."""
        result = normalize_finding_to_dict(None)

        assert result["id"] == "unknown"
        assert result["severity"] == "low"
        assert result["location"] == "unknown:0"
        assert result["message"] == "Malformed finding"

    def test_normalize_dict_finding(self):
        """Test that dict finding is normalized."""
        finding = {
            "id": "F1",
            "severity": "HIGH",  # Case variation
            "location": "test.py:10",
            "message": "Test issue",
        }

        result = normalize_finding_to_dict(finding)

        assert result["id"] == "F1"
        assert result["severity"] == "high"  # Normalized to lowercase
        assert result["location"] == "test.py:10"
        assert result["file_path"] == "test.py"

    def test_normalize_dict_with_empty_location(self):
        """Test that empty location is handled."""
        finding = {
            "id": "F1",
            "severity": "high",
            "location": "",  # Empty location
            "message": "Test issue",
        }

        result = normalize_finding_to_dict(finding)

        assert result["location"] == "unknown:0"  # Normalized
        assert result["file_path"] == "unknown"  # No colon means no split

    def test_normalize_finding_object(self):
        """Test that Finding object is normalized."""
        finding = Finding(
            id="security-sql-001",
            severity="critical",
            location="app.py:42",
            message="SQL injection",
            detail="User input not sanitized",
        )

        result = normalize_finding_to_dict(finding)

        assert result["id"] == "security-sql-001"
        assert result["severity"] == "critical"
        assert result["location"] == "app.py:42"
        assert result["file_path"] == "app.py"
        assert result["message"] == "SQL injection"

    def test_normalize_finding_object_with_empty_severity(self):
        """Test that empty severity is normalized."""
        finding = Finding(
            id="F1",
            severity=None,  # type: ignore
            location="test.py:1",
            message="Test",
        )

        result = normalize_finding_to_dict(finding)

        assert result["severity"] == "low"  # Default


class TestDeduplicationEmptyLocation:
    """Test deduplication with empty locations (CRITICAL BUG FIX)."""

    def test_empty_location_findings_not_deduplicated(self):
        """Test that findings with empty locations are NOT deduplicated."""
        aggregator = ResultAggregator()

        findings = [
            Finding(id="F1", severity="high", location="", message="Issue 1"),
            Finding(id="F2", severity="high", location="", message="Issue 2"),
            Finding(id="F3", severity="high", location="", message="Issue 3"),
        ]

        result = aggregator._deduplicate_findings(findings)

        # All 3 should be preserved (not deduplicated)
        assert len(result) == 3

    def test_unknown_location_findings_not_deduplicated(self):
        """Test that findings with 'unknown:0' location are NOT deduplicated."""
        aggregator = ResultAggregator()

        findings = [
            Finding(id="F1", severity="high", location="unknown:0", message="Issue 1"),
            Finding(id="F2", severity="high", location="unknown:0", message="Issue 2"),
        ]

        result = aggregator._deduplicate_findings(findings)

        # Both should be preserved
        assert len(result) == 2

    def test_valid_location_findings_are_deduplicated(self):
        """Test that findings with same valid location ARE deduplicated."""
        aggregator = ResultAggregator()

        findings = [
            Finding(id="security-sql-001", severity="high", location="app.py:42", message="SQL injection"),
            Finding(id="antipattern-sql-002", severity="medium", location="app.py:42", message="SQL issue"),
        ]

        result = aggregator._deduplicate_findings(findings)

        # Should deduplicate to 1 (same location, same type 'sql')
        assert len(result) == 1
        # Should keep the higher severity one
        assert result[0].severity == "high"


class TestSeverityRanking:
    """Test severity ranking case sensitivity bug fix."""

    def test_severity_case_insensitive(self):
        """Test that severity comparison is case-insensitive."""
        aggregator = ResultAggregator()

        # Use same ID to trigger deduplication
        findings = [
            Finding(id="security-sql-001", severity="CRITICAL", location="test.py:1", message="Issue"),
            Finding(id="antipattern-sql-002", severity="high", location="test.py:1", message="Issue"),
        ]

        result = aggregator._deduplicate_findings(findings)

        # Should keep CRITICAL (highest severity) - both have rule_type "sql"
        assert len(result) == 1
        assert result[0].severity.lower() == "critical"

    def test_invalid_severity_normalized(self):
        """Test that invalid severity is normalized to 'low'."""
        aggregator = ResultAggregator()

        # Use same rule type to trigger deduplication
        findings = [
            Finding(id="security-sql-001", severity="UNKNOWN", location="test.py:1", message="Issue"),
            Finding(id="antipattern-sql-002", severity="high", location="test.py:1", message="Issue"),
        ]

        result = aggregator._deduplicate_findings(findings)

        # Should keep 'high' (valid severity wins over invalid) - both have rule_type "sql"
        assert len(result) == 1
        assert result[0].severity == "high"


class TestMixedFindingTypes:
    """Test handling of mixed Finding objects and dicts."""

    def test_store_validation_results_mixed_types(self):
        """Test that mixed Finding/dict types are normalized."""
        aggregator = ResultAggregator()
        pipeline = ValidationPipeline()
        context = create_test_context()

        # Mock frame_results with mixed types
        context.frame_results = {
            "security": {
                "result": type(
                    "FrameResult",
                    (),
                    {
                        "findings": [
                            Finding(id="F1", severity="high", location="test.py:1", message="Issue 1"),
                            {"id": "F2", "severity": "medium", "location": "test.py:2", "message": "Issue 2"},
                        ]
                    },
                )()
            }
        }

        aggregator.store_validation_results(context, pipeline)

        # Both should be normalized to dicts
        assert len(context.findings) == 2
        # validated_issues should also be populated
        assert len(context.validated_issues) == 2


class TestInputValidation:
    """Test input validation (BATCH 2)."""

    def test_invalid_frame_results_type(self):
        """Test that invalid frame_results type is handled."""
        aggregator = ResultAggregator()
        pipeline = ValidationPipeline()
        context = create_test_context()

        # Invalid type
        context.frame_results = "invalid"  # type: ignore

        aggregator.store_validation_results(context, pipeline)

        # Should reset to empty
        assert context.findings == []
        assert context.validated_issues == []

    def test_findings_list_too_large(self):
        """Test that huge findings lists are truncated."""
        aggregator = ResultAggregator()
        pipeline = ValidationPipeline()
        context = create_test_context()

        # Create 1500 findings (exceeds limit of 1000)
        huge_findings = [
            Finding(id=f"F{i}", severity="low", location=f"test.py:{i}", message=f"Issue {i}")
            for i in range(1500)
        ]

        context.frame_results = {
            "security": {"result": type("FrameResult", (), {"findings": huge_findings})()}
        }

        aggregator.store_validation_results(context, pipeline)

        # Should truncate to 1000
        assert len(context.findings) <= 1000
