"""
Panel compatibility tests for pipeline models.

Tests that pipeline models serialize/deserialize correctly for Panel integration.
CRITICAL: Panel TypeScript types are SOURCE OF TRUTH.
"""

import pytest
from datetime import datetime
from warden.pipeline.domain.models import (
    SubStep,
    PipelineStep,
    PipelineSummary,
    PipelineRun,
    FrameExecution,
)
from warden.pipeline.domain.enums import (
    StepType,
    SubStepType,
    StepStatus,
    PipelineStatus,
)
from warden.shared.utils.panel_converter import (
    pipeline_status_to_panel,
    frame_priority_to_panel,
    panel_status_to_pipeline,
)


class TestSubStepModel:
    """Test SubStep model Panel compatibility."""

    def test_substep_to_json_camelcase(self):
        """Test SubStep serializes to camelCase JSON."""
        substep = SubStep(
            id="security-001",
            name="SQL Injection Tests",
            type="security",
            status="completed",
            duration="0.8s",
        )

        json_data = substep.to_json()

        # Check all fields are camelCase
        assert "id" in json_data
        assert "name" in json_data
        assert "type" in json_data
        assert "status" in json_data
        assert "duration" in json_data

        # Check values
        assert json_data["id"] == "security-001"
        assert json_data["name"] == "SQL Injection Tests"
        assert json_data["type"] == "security"
        assert json_data["status"] == "completed"
        assert json_data["duration"] == "0.8s"

    def test_substep_from_json_parsing(self):
        """Test SubStep deserializes from Panel JSON."""
        panel_json = {
            "id": "chaos-001",
            "name": "Random Input Tests",
            "type": "chaos",
            "status": "running",
            "duration": "1.2s",
        }

        substep = SubStep.from_json(panel_json)

        assert substep.id == "chaos-001"
        assert substep.name == "Random Input Tests"
        assert substep.type == "chaos"
        assert substep.status == "running"
        assert substep.duration == "1.2s"

    def test_substep_from_frame_execution(self):
        """Test converting FrameExecution to SubStep."""
        frame_exec = FrameExecution(
            frame_id="security",
            frame_name="Security Frame",
            status="completed",
            duration=45.5,  # seconds
        )

        substep = SubStep.from_frame_execution(frame_exec)

        assert substep.id == "security"
        assert substep.name == "Security Frame"
        assert substep.type == "security"
        assert substep.status == "completed"
        assert substep.duration == "45.5s"

    def test_substep_duration_formatting_minutes(self):
        """Test SubStep duration formatting for minutes."""
        frame_exec = FrameExecution(
            frame_id="stress",
            frame_name="Stress Tests",
            status="completed",
            duration=125.0,  # 2 minutes 5 seconds
        )

        substep = SubStep.from_frame_execution(frame_exec)

        assert substep.duration == "2m 5s"


class TestPipelineStepModel:
    """Test PipelineStep model Panel compatibility."""

    def test_step_to_json_camelcase(self):
        """Test PipelineStep serializes to camelCase JSON."""
        substep = SubStep(
            id="security-001", name="Security Tests", type="security", status="completed"
        )

        step = PipelineStep(
            id="validation-step",
            name="Validation",
            type="validation",
            status="running",
            duration="2m 15s",
            score="4/6",
            sub_steps=[substep],
        )

        json_data = step.to_json()

        # Check all fields are camelCase
        assert "id" in json_data
        assert "name" in json_data
        assert "type" in json_data
        assert "status" in json_data
        assert "duration" in json_data
        assert "score" in json_data
        assert "subSteps" in json_data  # CRITICAL: camelCase!

        # Check substeps are serialized
        assert len(json_data["subSteps"]) == 1
        assert json_data["subSteps"][0]["id"] == "security-001"

    def test_step_from_json_parsing(self):
        """Test PipelineStep deserializes from Panel JSON."""
        panel_json = {
            "id": "analysis-step",
            "name": "Analysis",
            "type": "analysis",
            "status": "completed",
            "duration": "1m 30s",
            "score": "10/10",
            "subSteps": [],
        }

        step = PipelineStep.from_json(panel_json)

        assert step.id == "analysis-step"
        assert step.name == "Analysis"
        assert step.type == "analysis"
        assert step.status == "completed"
        assert step.duration == "1m 30s"
        assert step.score == "10/10"
        assert step.sub_steps == []


class TestPipelineSummaryModel:
    """Test PipelineSummary model Panel compatibility."""

    def test_summary_to_json_nested_structure(self):
        """Test PipelineSummary serializes to Panel's nested structure."""
        summary = PipelineSummary(
            score_before=45.5,
            score_after=78.3,
            lines_before=1500,
            lines_after=1420,
            duration="5m 23s",
            current_step=3,
            total_steps=5,
            findings_critical=2,
            findings_high=5,
            findings_medium=8,
            findings_low=12,
            ai_source="warden",
        )

        json_data = summary.to_json()

        # Check nested structure
        assert "score" in json_data
        assert json_data["score"]["before"] == 45.5
        assert json_data["score"]["after"] == 78.3

        assert "lines" in json_data
        assert json_data["lines"]["before"] == 1500
        assert json_data["lines"]["after"] == 1420

        assert "progress" in json_data
        assert json_data["progress"]["current"] == 3
        assert json_data["progress"]["total"] == 5

        assert "findings" in json_data
        assert json_data["findings"]["critical"] == 2
        assert json_data["findings"]["high"] == 5
        assert json_data["findings"]["medium"] == 8
        assert json_data["findings"]["low"] == 12

        assert json_data["aiSource"] == "warden"
        assert json_data["duration"] == "5m 23s"

    def test_summary_default_values(self):
        """Test PipelineSummary default values."""
        summary = PipelineSummary()

        json_data = summary.to_json()

        assert json_data["score"]["before"] == 0.0
        assert json_data["score"]["after"] == 0.0
        assert json_data["lines"]["before"] == 0
        assert json_data["lines"]["after"] == 0
        assert json_data["duration"] == "0s"
        assert json_data["progress"]["current"] == 0
        assert json_data["progress"]["total"] == 5
        assert json_data["aiSource"] == "warden"


class TestPipelineRunModel:
    """Test PipelineRun model Panel compatibility."""

    def test_pipeline_run_to_json_full(self):
        """Test PipelineRun full serialization."""
        summary = PipelineSummary(
            score_before=50.0,
            score_after=75.0,
            duration="3m 45s",
            current_step=2,
        )

        step1 = PipelineStep(
            id="analysis", name="Analysis", type="analysis", status="completed"
        )
        step2 = PipelineStep(
            id="validation", name="Validation", type="validation", status="running"
        )

        pipeline_run = PipelineRun(
            id="run-123",
            run_number=5,
            status="running",  # CRITICAL: String, not enum!
            trigger="manual",
            start_time=datetime(2025, 12, 21, 10, 30, 0),
            steps=[step1, step2],
            summary=summary,
            active_step_id="validation",
            active_tab_id="logs",
        )

        json_data = pipeline_run.to_json()

        # Check all fields are camelCase
        assert json_data["id"] == "run-123"
        assert json_data["runNumber"] == 5
        assert json_data["status"] == "running"  # String, not int!
        assert json_data["trigger"] == "manual"
        assert json_data["startTime"] == "2025-12-21T10:30:00"
        assert len(json_data["steps"]) == 2
        assert "summary" in json_data
        assert json_data["activeStepId"] == "validation"
        assert json_data["activeTabId"] == "logs"

    def test_pipeline_run_from_json(self):
        """Test PipelineRun deserialization from Panel JSON."""
        panel_json = {
            "id": "run-456",
            "runNumber": 10,
            "status": "success",
            "trigger": "git-push",
            "startTime": "2025-12-21T11:00:00",
            "steps": [],
            "summary": {
                "score": {"before": 0, "after": 0},
                "lines": {"before": 0, "after": 0},
                "duration": "0s",
                "progress": {"current": 0, "total": 5},
                "findings": {"critical": 0, "high": 0, "medium": 0, "low": 0},
                "aiSource": "warden",
            },
            "activeTabId": "issues",
        }

        pipeline_run = PipelineRun.from_json(panel_json)

        assert pipeline_run.id == "run-456"
        assert pipeline_run.run_number == 10
        assert pipeline_run.status == "success"
        assert pipeline_run.trigger == "git-push"
        assert pipeline_run.active_tab_id == "issues"

    def test_pipeline_run_status_is_string(self):
        """CRITICAL: Test that PipelineRun status is string, not enum."""
        pipeline_run = PipelineRun(
            id="run-001",
            run_number=1,
            status="success",  # String!
            trigger="manual",
            start_time=datetime.now(),
            steps=[],
            summary=PipelineSummary(),
        )

        json_data = pipeline_run.to_json()

        # Status MUST be string
        assert isinstance(json_data["status"], str)
        assert json_data["status"] == "success"


class TestPanelJsonRoundtrip:
    """Test Panel JSON roundtrip compatibility."""

    def test_substep_roundtrip(self):
        """Test SubStep serialize/deserialize roundtrip."""
        original = SubStep(
            id="fuzz-001",
            name="Fuzz Testing",
            type="fuzz",
            status="completed",
            duration="2.5s",
        )

        json_data = original.to_json()
        parsed = SubStep.from_json(json_data)

        assert parsed.id == original.id
        assert parsed.name == original.name
        assert parsed.type == original.type
        assert parsed.status == original.status
        assert parsed.duration == original.duration

    def test_step_roundtrip(self):
        """Test PipelineStep serialize/deserialize roundtrip."""
        original = PipelineStep(
            id="validation",
            name="Validation",
            type="validation",
            status="completed",
            duration="5m 10s",
            score="8/10",
        )

        json_data = original.to_json()
        parsed = PipelineStep.from_json(json_data)

        assert parsed.id == original.id
        assert parsed.name == original.name
        assert parsed.type == original.type
        assert parsed.status == original.status


class TestStatusMapping:
    """Test PipelineStatus mapping helpers."""

    def test_completed_maps_to_success(self):
        """CRITICAL: Test COMPLETED → 'success' mapping."""
        status = pipeline_status_to_panel(PipelineStatus.COMPLETED)
        assert status == "success"

    def test_running_maps_to_running(self):
        """Test RUNNING → 'running' mapping."""
        status = pipeline_status_to_panel(PipelineStatus.RUNNING)
        assert status == "running"

    def test_failed_maps_to_failed(self):
        """Test FAILED → 'failed' mapping."""
        status = pipeline_status_to_panel(PipelineStatus.FAILED)
        assert status == "failed"

    def test_cancelled_maps_to_failed(self):
        """Test CANCELLED → 'failed' mapping (Panel has no 'cancelled')."""
        status = pipeline_status_to_panel(PipelineStatus.CANCELLED)
        assert status == "failed"

    def test_reverse_mapping_success_to_completed(self):
        """Test reverse mapping: 'success' → COMPLETED."""
        status = panel_status_to_pipeline("success")
        assert status == PipelineStatus.COMPLETED

    def test_reverse_mapping_running_to_running(self):
        """Test reverse mapping: 'running' → RUNNING."""
        status = panel_status_to_pipeline("running")
        assert status == PipelineStatus.RUNNING


class TestEnumValues:
    """Test enum values match Panel TypeScript types."""

    def test_step_type_values(self):
        """Test StepType enum values."""
        assert StepType.ANALYSIS.value == "analysis"
        assert StepType.CLASSIFICATION.value == "classification"
        assert StepType.VALIDATION.value == "validation"
        assert StepType.FORTIFICATION.value == "fortification"
        assert StepType.CLEANING.value == "cleaning"

    def test_substep_type_values(self):
        """Test SubStepType enum values."""
        assert SubStepType.SECURITY.value == "security"
        assert SubStepType.CHAOS.value == "chaos"
        assert SubStepType.FUZZ.value == "fuzz"
        assert SubStepType.PROPERTY.value == "property"
        assert SubStepType.STRESS.value == "stress"
        assert SubStepType.ARCHITECTURAL.value == "architectural"

    def test_step_status_values(self):
        """Test StepStatus enum values."""
        assert StepStatus.PENDING.value == "pending"
        assert StepStatus.RUNNING.value == "running"
        assert StepStatus.COMPLETED.value == "completed"
        assert StepStatus.FAILED.value == "failed"
        assert StepStatus.SKIPPED.value == "skipped"
