"""
Test Project domain models for Panel JSON compatibility.

Tests:
- Project models: to_json/from_json roundtrip
- ProjectSummary nested objects (meta, last_run, findings)
- RunHistory JSON compatibility
- All camelCase conversions
- Date serialization (ISO 8601)
- Nested object serialization
"""

import pytest
from datetime import datetime

from warden.projects.domain.models import (
    ProjectMeta,
    FindingsSummary,
    LastRunInfo,
    Project,
    ProjectSummary,
    RunHistory,
    ProjectDetail,
)
from warden.projects.domain.enums import ProjectStatus, QualityTrend


class TestProjectMeta:
    """Test ProjectMeta model."""

    def test_to_json(self):
        """Test ProjectMeta serialization to camelCase."""
        meta = ProjectMeta(branch="main", commit="abc123")

        json_data = meta.to_json()

        assert json_data == {"branch": "main", "commit": "abc123"}

    def test_from_json(self):
        """Test ProjectMeta deserialization from camelCase."""
        json_data = {"branch": "develop", "commit": "def456"}

        meta = ProjectMeta.from_json(json_data)

        assert meta.branch == "develop"
        assert meta.commit == "def456"

    def test_roundtrip(self):
        """Test ProjectMeta roundtrip serialization."""
        original = ProjectMeta(branch="feature/test", commit="xyz789")

        json_data = original.to_json()
        parsed = ProjectMeta.from_json(json_data)

        assert parsed.branch == original.branch
        assert parsed.commit == original.commit


class TestFindingsSummary:
    """Test FindingsSummary model."""

    def test_to_json(self):
        """Test FindingsSummary serialization."""
        findings = FindingsSummary(critical=2, high=5, medium=8, low=12)

        json_data = findings.to_json()

        assert json_data == {"critical": 2, "high": 5, "medium": 8, "low": 12}

    def test_from_json(self):
        """Test FindingsSummary deserialization."""
        json_data = {"critical": 1, "high": 3, "medium": 5, "low": 7}

        findings = FindingsSummary.from_json(json_data)

        assert findings.critical == 1
        assert findings.high == 3
        assert findings.medium == 5
        assert findings.low == 7

    def test_defaults(self):
        """Test FindingsSummary with default values."""
        findings = FindingsSummary()

        assert findings.critical == 0
        assert findings.high == 0
        assert findings.medium == 0
        assert findings.low == 0

    def test_total_property(self):
        """Test FindingsSummary total property."""
        findings = FindingsSummary(critical=2, high=5, medium=8, low=12)

        assert findings.total == 27


class TestLastRunInfo:
    """Test LastRunInfo model."""

    def test_to_json(self):
        """Test LastRunInfo serialization with datetime."""
        timestamp = datetime(2025, 12, 21, 10, 30, 0)
        last_run = LastRunInfo(
            status="success", timestamp=timestamp, duration="1m 43s"
        )

        json_data = last_run.to_json()

        assert json_data["status"] == "success"
        assert json_data["timestamp"] == "2025-12-21T10:30:00"
        assert json_data["duration"] == "1m 43s"

    def test_from_json(self):
        """Test LastRunInfo deserialization with ISO datetime."""
        json_data = {
            "status": "running",
            "timestamp": "2025-12-21T15:45:30",
            "duration": "2m 15s",
        }

        last_run = LastRunInfo.from_json(json_data)

        assert last_run.status == "running"
        assert last_run.timestamp == datetime(2025, 12, 21, 15, 45, 30)
        assert last_run.duration == "2m 15s"

    def test_all_status_values(self):
        """Test LastRunInfo with all valid status values."""
        timestamp = datetime.now()
        statuses = ["success", "running", "failed", "idle"]

        for status in statuses:
            last_run = LastRunInfo(
                status=status, timestamp=timestamp, duration="1m"
            )
            json_data = last_run.to_json()
            assert json_data["status"] == status


class TestProject:
    """Test Project base model."""

    def test_to_json_camelcase(self):
        """Test Project serialization converts to camelCase."""
        meta = ProjectMeta(branch="main", commit="abc123")
        project = Project(
            id="proj-1",
            name="my-project",
            display_name="My Project",
            meta=meta,
            provider="github",
        )

        json_data = project.to_json()

        # Check camelCase conversion
        assert "displayName" in json_data
        assert "display_name" not in json_data
        assert json_data["displayName"] == "My Project"

        # Check nested meta
        assert "meta" in json_data
        assert json_data["meta"]["branch"] == "main"

    def test_from_json_camelcase(self):
        """Test Project deserialization from camelCase."""
        json_data = {
            "id": "proj-2",
            "name": "test-project",
            "displayName": "Test Project",
            "meta": {"branch": "develop", "commit": "def456"},
            "provider": "gitlab",
        }

        project = Project.from_json(json_data)

        assert project.id == "proj-2"
        assert project.name == "test-project"
        assert project.display_name == "Test Project"
        assert project.meta.branch == "develop"
        assert project.provider == "gitlab"

    def test_optional_provider(self):
        """Test Project with optional provider field."""
        meta = ProjectMeta(branch="main", commit="abc123")
        project = Project(
            id="proj-3", name="local-project", display_name="Local", meta=meta
        )

        json_data = project.to_json()
        parsed = Project.from_json(json_data)

        assert parsed.provider is None


class TestProjectSummary:
    """Test ProjectSummary model."""

    def test_to_json_nested_objects(self):
        """Test ProjectSummary with all nested objects."""
        meta = ProjectMeta(branch="main", commit="abc123")
        last_run = LastRunInfo(
            status="success",
            timestamp=datetime(2025, 12, 21, 10, 0, 0),
            duration="1m 43s",
        )
        findings = FindingsSummary(critical=1, high=3, medium=5, low=10)

        summary = ProjectSummary(
            id="proj-1",
            name="my-project",
            display_name="My Project",
            meta=meta,
            provider="github",
            quality_score=7.5,
            trend="improving",
            last_run=last_run,
            findings=findings,
            repository_path="/path/to/repo",
            repository_url="https://github.com/user/repo",
        )

        json_data = summary.to_json()

        # Check camelCase
        assert "qualityScore" in json_data
        assert "lastRun" in json_data
        assert "repositoryPath" in json_data

        # Check nested structures
        assert json_data["qualityScore"] == 7.5
        assert json_data["trend"] == "improving"
        assert json_data["lastRun"]["status"] == "success"
        assert json_data["findings"]["critical"] == 1

    def test_from_json_complete(self):
        """Test ProjectSummary deserialization with all fields."""
        json_data = {
            "id": "proj-1",
            "name": "test",
            "displayName": "Test",
            "meta": {"branch": "main", "commit": "abc123"},
            "provider": "github",
            "qualityScore": 8.2,
            "trend": "stable",
            "lastRun": {
                "status": "success",
                "timestamp": "2025-12-21T10:00:00",
                "duration": "2m",
            },
            "findings": {"critical": 0, "high": 2, "medium": 4, "low": 8},
            "repositoryPath": "/path",
            "repositoryUrl": "https://example.com",
        }

        summary = ProjectSummary.from_json(json_data)

        assert summary.quality_score == 8.2
        assert summary.trend == "stable"
        assert summary.last_run.status == "success"
        assert summary.findings.high == 2

    def test_roundtrip_preserves_data(self):
        """Test ProjectSummary roundtrip preserves all data."""
        meta = ProjectMeta(branch="dev", commit="xyz")
        last_run = LastRunInfo(
            status="failed", timestamp=datetime.now(), duration="30s"
        )
        findings = FindingsSummary(critical=5, high=10, medium=15, low=20)

        original = ProjectSummary(
            id="proj-roundtrip",
            name="roundtrip",
            display_name="Roundtrip Test",
            meta=meta,
            quality_score=5.5,
            trend="degrading",
            last_run=last_run,
            findings=findings,
        )

        json_data = original.to_json()
        parsed = ProjectSummary.from_json(json_data)

        assert parsed.id == original.id
        assert parsed.quality_score == original.quality_score
        assert parsed.trend == original.trend
        assert parsed.findings.critical == original.findings.critical


class TestRunHistory:
    """Test RunHistory model."""

    def test_to_json_camelcase_conversion(self):
        """Test RunHistory camelCase conversion."""
        findings = FindingsSummary(critical=1, high=2, medium=3, low=4)
        run = RunHistory(
            id="run-1",
            project_id="proj-1",
            status="success",
