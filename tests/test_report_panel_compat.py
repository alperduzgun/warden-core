"""
Test Report and Pipeline models for Panel JSON compatibility.

Tests:
- GuardianReport with improvement_percentage calculation
- PipelineSummary nested structure (score, lines, progress, findings)
- All camelCase conversions
- Date serialization (ISO 8601)
- Computed properties
"""

import pytest
from datetime import datetime

from warden.reports.domain.models import GuardianReport, DashboardMetrics
from warden.pipeline.domain.models import PipelineSummary, SubStep, PipelineStep


class TestGuardianReport:
    """Test GuardianReport model."""

    def test_to_json_includes_improvement_percentage(self):
        """Test GuardianReport serialization includes computed property."""
        report = GuardianReport(
            file_path="test.py",
            score_before=50.0,
            score_after=75.0,
            lines_before=100,
            lines_after=120,
            files_modified=["test.py", "utils.py"],
            files_created=["new.py"],
            timestamp=datetime(2025, 12, 21, 10, 0, 0),
            issues_by_severity={"critical": 2, "high": 3},
            issues_by_category={"security": 5},
        )

        json_data = report.to_json()

        # Check camelCase conversion
        assert "filePath" in json_data
        assert "scoreBefore" in json_data
        assert "scoreAfter" in json_data
        assert "linesBefore" in json_data
        assert "linesAfter" in json_data
        assert "filesModified" in json_data
        assert "filesCreated" in json_data
        assert "issuesBySeverity" in json_data
        assert "issuesByCategory" in json_data

        # Check computed property is included
        assert "improvementPercentage" in json_data
        assert json_data["improvementPercentage"] == 50.0  # (75-50)/50 * 100

    def test_improvement_percentage_positive(self):
        """Test improvement_percentage calculation for improvement."""
        report = GuardianReport(
            file_path="test.py",
            score_before=60.0,
            score_after=90.0,
            lines_before=100,
            lines_after=100,
            files_modified=[],
            files_created=[],
            timestamp=datetime.now(),
            issues_by_severity={},
            issues_by_category={},
        )

        # (90-60)/60 * 100 = 50%
        assert report.improvement_percentage == 50.0

    def test_improvement_percentage_negative(self):
        """Test improvement_percentage calculation for degradation."""
        report = GuardianReport(
            file_path="test.py",
            score_before=80.0,
            score_after=60.0,
            lines_before=100,
            lines_after=110,
            files_modified=[],
            files_created=[],
            timestamp=datetime.now(),
            issues_by_severity={},
            issues_by_category={},
        )

        # (60-80)/80 * 100 = -25%
        assert report.improvement_percentage == -25.0

    def test_improvement_percentage_zero_before(self):
        """Test improvement_percentage when score_before is 0."""
        report = GuardianReport(
            file_path="test.py",
            score_before=0.0,
            score_after=50.0,
            lines_before=100,
            lines_after=120,
            files_modified=[],
            files_created=[],
            timestamp=datetime.now(),
            issues_by_severity={},
            issues_by_category={},
        )

        # Avoid division by zero
        assert report.improvement_percentage == 0.0

    def test_from_json_ignores_improvement_percentage(self):
        """Test from_json ignores improvementPercentage (computed field)."""
        json_data = {
            "filePath": "test.py",
            "scoreBefore": 40.0,
            "scoreAfter": 80.0,
            "linesBefore": 100,
            "linesAfter": 150,
            "filesModified": ["file1.py"],
            "filesCreated": ["file2.py"],
            "timestamp": "2025-12-21T12:00:00",
            "issuesBySeverity": {"critical": 1},
            "issuesByCategory": {"performance": 2},
            "improvementPercentage": 999.0,  # Should be ignored
        }

        report = GuardianReport.from_json(json_data)

        # improvementPercentage is recomputed, not taken from JSON
        assert report.improvement_percentage == 100.0  # (80-40)/40 * 100
        assert report.improvement_percentage != 999.0

    def test_optional_fields(self):
        """Test GuardianReport with optional fields."""
        report = GuardianReport(
            file_path="test.py",
            score_before=50.0,
            score_after=60.0,
            lines_before=100,
            lines_after=110,
            files_modified=[],
            files_created=[],
            timestamp=datetime.now(),
            issues_by_severity={},
            issues_by_category={},
            project_id="proj-123",
            tenant_id="tenant-456",
            generated_by="warden-cli",
        )

        json_data = report.to_json()

        assert json_data["projectId"] == "proj-123"
        assert json_data["tenantId"] == "tenant-456"
        assert json_data["generatedBy"] == "warden-cli"

    def test_roundtrip_preserves_data(self):
        """Test GuardianReport roundtrip preserves all data."""
        original = GuardianReport(
            file_path="app.py",
            score_before=70.0,
            score_after=85.0,
            lines_before=200,
            lines_after=220,
            files_modified=["app.py", "utils.py"],
            files_created=["new_module.py"],
            timestamp=datetime(2025, 12, 21, 15, 30, 0),
            issues_by_severity={"critical": 1, "high": 3, "medium": 5},
            issues_by_category={"security": 4, "performance": 5},
            project_id="proj-1",
        )

        json_data = original.to_json()
        parsed = GuardianReport.from_json(json_data)

        assert parsed.file_path == original.file_path
        assert parsed.score_before == original.score_before
        assert parsed.score_after == original.score_after
        assert parsed.files_modified == original.files_modified
        assert parsed.improvement_percentage == original.improvement_percentage


class TestPipelineSummary:
    """Test PipelineSummary model."""

    def test_to_json_nested_structure(self):
        """Test PipelineSummary generates nested JSON structure."""
        summary = PipelineSummary(
            score_before=60.0,
            score_after=80.0,
            lines_before=1000,
            lines_after=1200,
            duration="1m 43s",
            current_step=3,
            total_steps=5,
            findings_critical=2,
            findings_high=5,
            findings_medium=10,
            findings_low=15,
            ai_source="claude-code",
        )

        json_data = summary.to_json()

        # Check nested score structure
        assert "score" in json_data
        assert isinstance(json_data["score"], dict)
        assert json_data["score"]["before"] == 60.0
        assert json_data["score"]["after"] == 80.0

        # Check nested lines structure
        assert "lines" in json_data
        assert isinstance(json_data["lines"], dict)
        assert json_data["lines"]["before"] == 1000
        assert json_data["lines"]["after"] == 1200

        # Check nested progress structure
        assert "progress" in json_data
        assert isinstance(json_data["progress"], dict)
        assert json_data["progress"]["current"] == 3
        assert json_data["progress"]["total"] == 5

        # Check nested findings structure
        assert "findings" in json_data
        assert isinstance(json_data["findings"], dict)
        assert json_data["findings"]["critical"] == 2
        assert json_data["findings"]["high"] == 5
        assert json_data["findings"]["medium"] == 10
        assert json_data["findings"]["low"] == 15

        # Check aiSource (camelCase)
        assert "aiSource" in json_data
        assert json_data["aiSource"] == "claude-code"

    def test_panel_expected_format(self):
        """Test PipelineSummary matches Panel's exact expected format."""
        summary = PipelineSummary(
            score_before=50.0,
            score_after=75.0,
            lines_before=800,
            lines_after=900,
            duration="2m 15s",
            current_step=2,
            total_steps=5,
            findings_critical=1,
            findings_high=3,
            findings_medium=5,
            findings_low=8,
            ai_source="warden-cli",
        )

        json_data = summary.to_json()

        # Panel expects this exact structure
        expected_keys = ["score", "lines", "duration", "progress", "findings", "aiSource"]
        for key in expected_keys:
            assert key in json_data

        # No snake_case keys
        assert "score_before" not in json_data
        assert "ai_source" not in json_data
        assert "current_step" not in json_data

    def test_default_values(self):
        """Test PipelineSummary with default values."""
        summary = PipelineSummary()

        json_data = summary.to_json()

        assert json_data["score"]["before"] == 0.0
        assert json_data["score"]["after"] == 0.0
        assert json_data["duration"] == "0s"
        assert json_data["progress"]["total"] == 5  # Always 5 steps
        assert json_data["aiSource"] == "warden-cli"  # Default


class TestSubStep:
    """Test SubStep model."""

    def test_to_json_camelcase(self):
        """Test SubStep serialization to camelCase."""
        substep = SubStep(
            id="security",
            name="Security Frame",
            type="security",
            status="completed",
            duration="0.8s",
        )

        json_data = substep.to_json()

        # All fields should be present
        assert json_data["id"] == "security"
        assert json_data["name"] == "Security Frame"
        assert json_data["type"] == "security"
        assert json_data["status"] == "completed"
        assert json_data["duration"] == "0.8s"

    def test_optional_duration(self):
        """Test SubStep with optional duration field."""
        substep = SubStep(
            id="chaos", name="Chaos Frame", type="chaos", status="pending"
        )

        json_data = substep.to_json()

        assert json_data["duration"] is None


class TestPipelineStep:
    """Test PipelineStep model."""

    def test_to_json_with_substeps(self):
        """Test PipelineStep serialization with substeps."""
        substeps = [
            SubStep(
                id="security",
                name="Security",
                type="security",
                status="completed",
                duration="1.2s",
            ),
            SubStep(
                id="chaos", name="Chaos", type="chaos", status="running", duration="0.5s"
            ),
        ]

        step = PipelineStep(
            id="validation",
            name="Validation",
            type="validation",
            status="running",
            duration="2.5s",
            score="4/6",
            sub_steps=substeps,
        )

        json_data = step.to_json()

        # Check camelCase conversion
        assert "subSteps" in json_data
        assert "sub_steps" not in json_data

        # Check substeps are serialized
        assert len(json_data["subSteps"]) == 2
        assert json_data["subSteps"][0]["id"] == "security"
        assert json_data["subSteps"][1]["id"] == "chaos"

    def test_optional_fields(self):
        """Test PipelineStep with optional fields."""
        step = PipelineStep(
            id="analysis", name="Analysis", type="analysis", status="pending"
        )

        json_data = step.to_json()

        assert json_data["duration"] is None
        assert json_data["score"] is None
        assert json_data["subSteps"] == []


class TestDashboardMetrics:
    """Test DashboardMetrics model."""

    def test_to_json_camelcase(self):
        """Test DashboardMetrics serialization to camelCase."""
        metrics = DashboardMetrics(
            total_issues=42,
            critical_issues=3,
            high_issues=8,
            medium_issues=15,
            low_issues=16,
            overall_score=72.5,
            trend="improving",
            last_scan_time=datetime(2025, 12, 21, 10, 30, 0),
            files_scanned=123,
            lines_scanned=5432,
        )

        json_data = metrics.to_json()

        # Check camelCase
        assert "totalIssues" in json_data
        assert "criticalIssues" in json_data
        assert "overallScore" in json_data
        assert "lastScanTime" in json_data
        assert "filesScanned" in json_data
        assert "linesScanned" in json_data

        # No snake_case
        assert "total_issues" not in json_data
        assert "last_scan_time" not in json_data

    def test_from_json(self):
        """Test DashboardMetrics deserialization."""
        json_data = {
            "totalIssues": 50,
            "criticalIssues": 5,
            "highIssues": 10,
            "mediumIssues": 15,
            "lowIssues": 20,
            "overallScore": 68.0,
            "trend": "degrading",
            "lastScanTime": "2025-12-21T14:00:00",
            "filesScanned": 200,
            "linesScanned": 10000,
        }

        metrics = DashboardMetrics.from_json(json_data)

        assert metrics.total_issues == 50
        assert metrics.critical_issues == 5
        assert metrics.overall_score == 68.0
        assert metrics.trend == "degrading"
        assert metrics.files_scanned == 200


class TestPanelJsonCompatibility:
    """Test Panel JSON format compatibility for reports and pipeline."""

    def test_guardian_report_panel_format(self):
        """Test GuardianReport matches Panel's expected format."""
        report = GuardianReport(
            file_path="test.py",
            score_before=50.0,
            score_after=75.0,
            lines_before=100,
            lines_after=120,
            files_modified=["test.py"],
            files_created=["new.py"],
            timestamp=datetime(2025, 12, 21, 10, 0, 0),
            issues_by_severity={"critical": 2},
            issues_by_category={"security": 3},
        )

        json_data = report.to_json()

        # Panel expects these exact keys
        expected_keys = [
            "filePath",
            "scoreBefore",
            "scoreAfter",
            "linesBefore",
            "linesAfter",
            "filesModified",
            "filesCreated",
            "timestamp",
            "issuesBySeverity",
            "issuesByCategory",
            "improvementPercentage",
        ]

        for key in expected_keys:
            assert key in json_data, f"Missing key: {key}"

        # Verify types
        assert isinstance(json_data["filePath"], str)
        assert isinstance(json_data["scoreBefore"], float)
        assert isinstance(json_data["filesModified"], list)
        assert isinstance(json_data["issuesBySeverity"], dict)
        assert isinstance(json_data["improvementPercentage"], float)

    def test_pipeline_summary_panel_format(self):
        """Test PipelineSummary matches Panel's expected format."""
        summary = PipelineSummary(
            score_before=60.0,
            score_after=80.0,
            lines_before=1000,
            lines_after=1200,
            duration="1m 43s",
            current_step=3,
            total_steps=5,
            findings_critical=2,
            findings_high=5,
            findings_medium=10,
            findings_low=15,
            ai_source="claude-code",
        )

        json_data = summary.to_json()

        # Panel expects these exact keys
        assert "score" in json_data
        assert "lines" in json_data
        assert "duration" in json_data
        assert "progress" in json_data
        assert "findings" in json_data
        assert "aiSource" in json_data

        # Verify nested structures
        assert isinstance(json_data["score"], dict)
        assert "before" in json_data["score"]
        assert "after" in json_data["score"]

        assert isinstance(json_data["findings"], dict)
        assert "critical" in json_data["findings"]
        assert "high" in json_data["findings"]
        assert "medium" in json_data["findings"]
        assert "low" in json_data["findings"]

    def test_datetime_iso8601_format(self):
        """Test datetime fields are ISO 8601 format."""
        report = GuardianReport(
            file_path="test.py",
            score_before=50.0,
            score_after=60.0,
            lines_before=100,
            lines_after=110,
            files_modified=[],
            files_created=[],
            timestamp=datetime(2025, 12, 21, 15, 45, 30),
            issues_by_severity={},
            issues_by_category={},
        )

        json_data = report.to_json()

        # ISO 8601 format
        assert json_data["timestamp"] == "2025-12-21T15:45:30"
        assert "T" in json_data["timestamp"]
