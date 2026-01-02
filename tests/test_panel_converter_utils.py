"""
Tests for panel_converter utility functions.

Verifies Core to Panel conversion helpers work correctly.
"""

import pytest
from datetime import datetime

from warden.pipeline.domain.enums import PipelineStatus, FramePriority
from warden.shared.utils.panel_converter import (
    pipeline_status_to_panel,
    frame_priority_to_panel,
    panel_status_to_pipeline,
    panel_priority_to_frame,
)


class TestPipelineStatusMapping:
    """Test PipelineStatus enum to Panel string conversion."""

    def test_pending_status(self):
        """Test PENDING maps to 'pending'."""
        result = pipeline_status_to_panel(PipelineStatus.PENDING)
        assert result == "pending"

    def test_running_status(self):
        """Test RUNNING maps to 'running'."""
        result = pipeline_status_to_panel(PipelineStatus.RUNNING)
        assert result == "running"

    def test_completed_status_maps_to_success(self):
        """Test COMPLETED maps to 'success' (CRITICAL!)."""
        result = pipeline_status_to_panel(PipelineStatus.COMPLETED)
        assert result == "success"  # NOT 'completed'!

    def test_failed_status(self):
        """Test FAILED maps to 'failed'."""
        result = pipeline_status_to_panel(PipelineStatus.FAILED)
        assert result == "failed"

    def test_cancelled_status_maps_to_failed(self):
        """Test CANCELLED maps to 'failed'."""
        result = pipeline_status_to_panel(PipelineStatus.CANCELLED)
        assert result == "failed"  # Panel has no 'cancelled'

    def test_all_statuses_are_lowercase(self):
        """Test all status strings are lowercase."""
        for status in PipelineStatus:
            result = pipeline_status_to_panel(status)
            assert result.islower()

    def test_all_statuses_return_valid_panel_values(self):
        """Test all statuses return Panel-valid values."""
        valid_panel_statuses = {"pending", "running", "success", "failed"}
        for status in PipelineStatus:
            result = pipeline_status_to_panel(status)
            assert result in valid_panel_statuses


class TestPanelStatusToPipelineMapping:
    """Test Panel status string to PipelineStatus enum conversion."""

    def test_pending_string(self):
        """Test 'pending' maps to PENDING."""
        result = panel_status_to_pipeline("pending")
        assert result == PipelineStatus.PENDING

    def test_running_string(self):
        """Test 'running' maps to RUNNING."""
        result = panel_status_to_pipeline("running")
        assert result == PipelineStatus.RUNNING

    def test_success_string_maps_to_completed(self):
        """Test 'success' maps to COMPLETED (CRITICAL!)."""
        result = panel_status_to_pipeline("success")
        assert result == PipelineStatus.COMPLETED

    def test_failed_string(self):
        """Test 'failed' maps to FAILED."""
        result = panel_status_to_pipeline("failed")
        assert result == PipelineStatus.FAILED

    def test_invalid_status_defaults_to_failed(self):
        """Test invalid status defaults to FAILED."""
        result = panel_status_to_pipeline("invalid")
        assert result == PipelineStatus.FAILED


class TestFramePriorityMapping:
    """Test FramePriority enum to Panel string conversion."""

    def test_critical_priority(self):
        """Test CRITICAL maps to 'critical'."""
        result = frame_priority_to_panel(FramePriority.CRITICAL)
        assert result == "critical"

    def test_high_priority(self):
        """Test HIGH maps to 'high'."""
        result = frame_priority_to_panel(FramePriority.HIGH)
        assert result == "high"

    def test_medium_priority(self):
        """Test MEDIUM maps to 'medium'."""
        result = frame_priority_to_panel(FramePriority.MEDIUM)
        assert result == "medium"

    def test_low_priority(self):
        """Test LOW maps to 'low'."""
        result = frame_priority_to_panel(FramePriority.LOW)
        assert result == "low"

    def test_all_priorities_are_lowercase(self):
        """Test all priority strings are lowercase."""
        for priority in FramePriority:
            result = frame_priority_to_panel(priority)
            assert result.islower()

    def test_all_priorities_return_valid_panel_values(self):
        """Test all priorities return Panel-valid values."""
        valid_panel_priorities = {"critical", "high", "medium", "low"}
        for priority in FramePriority:
            result = frame_priority_to_panel(priority)
            assert result in valid_panel_priorities


class TestPanelPriorityToFrameMapping:
    """Test Panel priority string to FramePriority enum conversion."""

    def test_critical_string(self):
        """Test 'critical' maps to CRITICAL."""
        result = panel_priority_to_frame("critical")
        assert result == FramePriority.CRITICAL

    def test_high_string(self):
        """Test 'high' maps to HIGH."""
        result = panel_priority_to_frame("high")
        assert result == FramePriority.HIGH

    def test_medium_string(self):
        """Test 'medium' maps to MEDIUM."""
        result = panel_priority_to_frame("medium")
        assert result == FramePriority.MEDIUM

    def test_low_string(self):
        """Test 'low' maps to LOW."""
        result = panel_priority_to_frame("low")
        assert result == FramePriority.LOW

    def test_invalid_priority_defaults_to_low(self):
        """Test invalid priority defaults to LOW."""
        result = panel_priority_to_frame("invalid")
        assert result == FramePriority.LOW


class TestRoundtripConversions:
    """Test bidirectional conversion consistency."""

    def test_pipeline_status_roundtrip(self):
        """Test PipelineStatus → Panel → PipelineStatus roundtrip."""
        # Test statuses that have 1:1 mapping
        statuses_to_test = [
            PipelineStatus.PENDING,
            PipelineStatus.RUNNING,
            PipelineStatus.COMPLETED,
            PipelineStatus.FAILED,
        ]

        for original_status in statuses_to_test:
            # Core → Panel
            panel_string = pipeline_status_to_panel(original_status)
            # Panel → Core
            core_status = panel_status_to_pipeline(panel_string)

            assert core_status == original_status

    def test_frame_priority_roundtrip(self):
        """Test FramePriority → Panel → FramePriority roundtrip."""
        priorities_to_test = [
            FramePriority.CRITICAL,
            FramePriority.HIGH,
            FramePriority.MEDIUM,
            FramePriority.LOW,
        ]

        for original_priority in priorities_to_test:
            # Core → Panel
            panel_string = frame_priority_to_panel(original_priority)
            # Panel → Core
            core_priority = panel_priority_to_frame(panel_string)

            assert core_priority == original_priority


class TestValidationFramePriorityMethod:
    """Test FramePriority.to_panel_string() method."""

    def test_validation_frame_priority_to_panel_string(self):
        """Test FramePriority has to_panel_string() method."""
        from warden.validation.domain.enums import (
            FramePriority as ValidationFramePriority,
        )

        # Test method exists
        assert hasattr(ValidationFramePriority.CRITICAL, "to_panel_string")

        # Test it returns correct values
        assert ValidationFramePriority.CRITICAL.to_panel_string() == "critical"
        assert ValidationFramePriority.HIGH.to_panel_string() == "high"
        assert ValidationFramePriority.MEDIUM.to_panel_string() == "medium"
        assert ValidationFramePriority.LOW.to_panel_string() == "low"

    def test_validation_frame_priority_informational_maps_to_low(self):
        """Test INFORMATIONAL priority maps to 'low'."""
        from warden.validation.domain.enums import (
            FramePriority as ValidationFramePriority,
        )

        assert ValidationFramePriority.INFORMATIONAL.to_panel_string() == "low"

    def test_validation_frame_priority_from_panel_string(self):
        """Test FramePriority.from_panel_string() method."""
        from warden.validation.domain.enums import (
            FramePriority as ValidationFramePriority,
        )

        # Test method exists
        assert hasattr(ValidationFramePriority, "from_panel_string")

        # Test parsing
        assert (
            ValidationFramePriority.from_panel_string("critical")
            == ValidationFramePriority.CRITICAL
        )
        assert (
            ValidationFramePriority.from_panel_string("high")
            == ValidationFramePriority.HIGH
        )
        assert (
            ValidationFramePriority.from_panel_string("medium")
            == ValidationFramePriority.MEDIUM
        )
        assert (
            ValidationFramePriority.from_panel_string("low")
            == ValidationFramePriority.LOW
        )

    def test_validation_frame_priority_from_panel_string_invalid(self):
        """Test from_panel_string raises error for invalid value."""
        from warden.validation.domain.enums import (
            FramePriority as ValidationFramePriority,
        )

        with pytest.raises(ValueError, match="Invalid panel priority string"):
            ValidationFramePriority.from_panel_string("invalid")
