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
            timestamp=datetime(2025, 12, 21, 12, 0, 0),
            duration="1m 30s",
            quality_score=8.0,
            findings=findings,
            commit="abc123",
            branch="main",
        )

        json_data = run.to_json()

        # Check camelCase
        assert "projectId" in json_data
        assert "project_id" not in json_data
        assert "qualityScore" in json_data
        assert "quality_score" not in json_data

        # Check values
        assert json_data["projectId"] == "proj-1"
        assert json_data["qualityScore"] == 8.0

    def test_from_json(self):
        """Test RunHistory deserialization."""
        json_data = {
            "id": "run-2",
            "projectId": "proj-2",
            "status": "failed",
            "timestamp": "2025-12-21T14:30:00",
            "duration": "45s",
            "qualityScore": 6.5,
            "findings": {"critical": 2, "high": 4, "medium": 6, "low": 8},
            "commit": "def456",
            "branch": "develop",
        }

        run = RunHistory.from_json(json_data)

        assert run.id == "run-2"
        assert run.project_id == "proj-2"
        assert run.status == "failed"
        assert run.quality_score == 6.5
        assert run.findings.critical == 2


class TestProjectDetail:
    """Test ProjectDetail model."""

    def test_to_json_with_recent_runs(self):
        """Test ProjectDetail with recent runs list."""
        meta = ProjectMeta(branch="main", commit="abc123")
        last_run = LastRunInfo(
            status="success", timestamp=datetime.now(), duration="1m"
        )
        findings = FindingsSummary(critical=0, high=1, medium=2, low=3)

        # Create recent runs
        run1 = RunHistory(
            id="run-1",
            project_id="proj-1",
            status="success",
            timestamp=datetime.now(),
            duration="1m",
            quality_score=8.0,
            findings=findings,
            commit="abc123",
            branch="main",
        )
        run2 = RunHistory(
            id="run-2",
            project_id="proj-1",
            status="success",
            timestamp=datetime.now(),
            duration="1m 10s",
            quality_score=7.8,
            findings=findings,
            commit="def456",
            branch="main",
        )

        detail = ProjectDetail(
            id="proj-1",
            name="test",
            display_name="Test",
            meta=meta,
            quality_score=8.0,
            trend="improving",
            last_run=last_run,
            findings=findings,
            description="Test project",
            created_at=datetime(2025, 1, 1, 0, 0, 0),
            total_runs=10,
            recent_runs=[run1, run2],
        )

        json_data = detail.to_json()

        # Check camelCase
        assert "recentRuns" in json_data
        assert "recent_runs" not in json_data
        assert "totalRuns" in json_data
        assert "createdAt" in json_data

        # Check recent runs
        assert len(json_data["recentRuns"]) == 2
        assert json_data["recentRuns"][0]["id"] == "run-1"
        assert json_data["recentRuns"][1]["id"] == "run-2"

    def test_from_json_complete(self):
        """Test ProjectDetail deserialization with all fields."""
        json_data = {
            "id": "proj-1",
            "name": "test",
            "displayName": "Test",
            "meta": {"branch": "main", "commit": "abc"},
            "qualityScore": 7.5,
            "trend": "stable",
            "lastRun": {
                "status": "success",
                "timestamp": "2025-12-21T10:00:00",
                "duration": "1m",
            },
            "findings": {"critical": 0, "high": 0, "medium": 1, "low": 2},
            "description": "Test description",
            "createdAt": "2025-01-01T00:00:00",
            "totalRuns": 15,
            "recentRuns": [
                {
                    "id": "run-1",
                    "projectId": "proj-1",
                    "status": "success",
                    "timestamp": "2025-12-21T10:00:00",
                    "duration": "1m",
                    "qualityScore": 7.5,
                    "findings": {"critical": 0, "high": 0, "medium": 1, "low": 2},
                    "commit": "abc",
                    "branch": "main",
                }
            ],
        }

        detail = ProjectDetail.from_json(json_data)

        assert detail.description == "Test description"
        assert detail.total_runs == 15
        assert len(detail.recent_runs) == 1
        assert detail.recent_runs[0].id == "run-1"

    def test_empty_recent_runs(self):
        """Test ProjectDetail with no recent runs."""
        meta = ProjectMeta(branch="main", commit="abc")
        last_run = LastRunInfo(status="idle", timestamp=datetime.now(), duration="0s")
        findings = FindingsSummary()

        detail = ProjectDetail(
            id="proj-new",
            name="new",
            display_name="New",
            meta=meta,
            quality_score=0.0,
            trend="stable",
            last_run=last_run,
            findings=findings,
        )

        json_data = detail.to_json()
        parsed = ProjectDetail.from_json(json_data)

        assert len(parsed.recent_runs) == 0


class TestPanelJsonCompatibility:
    """Test Panel JSON format compatibility."""

    def test_project_summary_panel_format(self):
        """Test ProjectSummary matches Panel's expected format exactly."""
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
        )

        json_data = summary.to_json()

        # Panel expects these exact keys (camelCase)
        assert "id" in json_data
        assert "name" in json_data
        assert "displayName" in json_data
        assert "meta" in json_data
        assert "provider" in json_data
        assert "qualityScore" in json_data
        assert "trend" in json_data
        assert "lastRun" in json_data
        assert "findings" in json_data

        # No snake_case keys
        assert "display_name" not in json_data
        assert "quality_score" not in json_data
        assert "last_run" not in json_data

    def test_date_iso8601_format(self):
        """Test datetime serialization is ISO 8601."""
        timestamp = datetime(2025, 12, 21, 15, 30, 45)
        last_run = LastRunInfo(status="success", timestamp=timestamp, duration="1m")

        json_data = last_run.to_json()

        # Panel expects ISO 8601 format
        assert json_data["timestamp"] == "2025-12-21T15:30:45"
        assert "T" in json_data["timestamp"]  # ISO separator

    def test_nested_object_serialization(self):
        """Test nested objects are properly serialized."""
        meta = ProjectMeta(branch="main", commit="abc")
        project = Project(
            id="p1", name="test", display_name="Test", meta=meta
        )

        json_data = project.to_json()

        # meta should be a dict, not a ProjectMeta object
        assert isinstance(json_data["meta"], dict)
        assert json_data["meta"]["branch"] == "main"
        assert json_data["meta"]["commit"] == "abc"
