"""
Tests for FramePriority Panel string conversion.

Validates that FramePriority enum correctly converts between Python IntEnum
and Panel-expected string format ('critical' | 'high' | 'medium' | 'low').
"""

import pytest

from warden.validation.domain.enums import FramePriority


class TestFramePriorityToPanelString:
    """Test FramePriority.to_panel_string() method."""

    def test_critical_to_panel_string(self):
        """CRITICAL should convert to 'critical'."""
        priority = FramePriority.CRITICAL
        assert priority.to_panel_string() == "critical"

    def test_high_to_panel_string(self):
        """HIGH should convert to 'high'."""
        priority = FramePriority.HIGH
        assert priority.to_panel_string() == "high"

    def test_medium_to_panel_string(self):
        """MEDIUM should convert to 'medium'."""
        priority = FramePriority.MEDIUM
        assert priority.to_panel_string() == "medium"

    def test_low_to_panel_string(self):
        """LOW should convert to 'low'."""
        priority = FramePriority.LOW
        assert priority.to_panel_string() == "low"

    def test_informational_maps_to_low(self):
        """INFORMATIONAL should map to 'low' as Panel doesn't have informational."""
        priority = FramePriority.INFORMATIONAL
        assert priority.to_panel_string() == "low"

    def test_all_priorities_have_panel_mapping(self):
        """All FramePriority values should have a Panel string mapping."""
        for priority in FramePriority:
            panel_string = priority.to_panel_string()
            assert panel_string in ["critical", "high", "medium", "low"]


class TestFramePriorityFromPanelString:
    """Test FramePriority.from_panel_string() method."""

    def test_critical_from_panel_string(self):
        """'critical' should convert to CRITICAL."""
        priority = FramePriority.from_panel_string("critical")
        assert priority == FramePriority.CRITICAL

    def test_high_from_panel_string(self):
        """'high' should convert to HIGH."""
        priority = FramePriority.from_panel_string("high")
        assert priority == FramePriority.HIGH

    def test_medium_from_panel_string(self):
        """'medium' should convert to MEDIUM."""
        priority = FramePriority.from_panel_string("medium")
        assert priority == FramePriority.MEDIUM

    def test_low_from_panel_string(self):
        """'low' should convert to LOW."""
        priority = FramePriority.from_panel_string("low")
        assert priority == FramePriority.LOW

    def test_invalid_panel_string_raises_error(self):
        """Invalid panel string should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid panel priority string"):
            FramePriority.from_panel_string("invalid")

    def test_empty_string_raises_error(self):
        """Empty string should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid panel priority string"):
            FramePriority.from_panel_string("")

    def test_case_sensitive(self):
        """Panel strings are case-sensitive."""
        with pytest.raises(ValueError, match="Invalid panel priority string"):
            FramePriority.from_panel_string("CRITICAL")


class TestFramePriorityRoundtrip:
    """Test roundtrip conversion: FramePriority -> Panel -> FramePriority."""

    def test_critical_roundtrip(self):
        """CRITICAL should survive roundtrip conversion."""
        original = FramePriority.CRITICAL
        panel_string = original.to_panel_string()
        restored = FramePriority.from_panel_string(panel_string)
        assert restored == original

    def test_high_roundtrip(self):
        """HIGH should survive roundtrip conversion."""
        original = FramePriority.HIGH
        panel_string = original.to_panel_string()
        restored = FramePriority.from_panel_string(panel_string)
        assert restored == original

    def test_medium_roundtrip(self):
        """MEDIUM should survive roundtrip conversion."""
        original = FramePriority.MEDIUM
        panel_string = original.to_panel_string()
        restored = FramePriority.from_panel_string(panel_string)
        assert restored == original

    def test_low_roundtrip(self):
        """LOW should survive roundtrip conversion."""
        original = FramePriority.LOW
        panel_string = original.to_panel_string()
        restored = FramePriority.from_panel_string(panel_string)
        assert restored == original

    def test_informational_lossy_conversion(self):
        """INFORMATIONAL -> 'low' -> LOW (lossy conversion)."""
        original = FramePriority.INFORMATIONAL
        panel_string = original.to_panel_string()
        restored = FramePriority.from_panel_string(panel_string)
        # INFORMATIONAL maps to 'low', which parses back as LOW
        assert restored == FramePriority.LOW
        assert restored != original


class TestFramePriorityPanelCompatibility:
    """Test Panel JSON compatibility."""

    def test_panel_expected_values(self):
        """Panel expects exactly these string values."""
        expected_values = {"critical", "high", "medium", "low"}
        actual_values = {priority.to_panel_string() for priority in FramePriority}
        assert actual_values == expected_values

    def test_no_informational_in_panel(self):
        """Panel doesn't support 'informational' priority."""
        panel_values = {priority.to_panel_string() for priority in FramePriority}
        assert "informational" not in panel_values

    def test_all_panel_values_parseable(self):
        """All Panel values should be parseable back to FramePriority."""
        panel_values = ["critical", "high", "medium", "low"]
        for panel_value in panel_values:
            priority = FramePriority.from_panel_string(panel_value)
            assert isinstance(priority, FramePriority)


class TestFramePriorityIntEnumBehavior:
    """Test that FramePriority still works as IntEnum."""

    def test_critical_value_is_1(self):
        """CRITICAL should have integer value 1."""
        assert FramePriority.CRITICAL == 1

    def test_high_value_is_2(self):
        """HIGH should have integer value 2."""
        assert FramePriority.HIGH == 2

    def test_medium_value_is_3(self):
        """MEDIUM should have integer value 3."""
        assert FramePriority.MEDIUM == 3

    def test_low_value_is_4(self):
        """LOW should have integer value 4."""
        assert FramePriority.LOW == 4

    def test_informational_value_is_5(self):
        """INFORMATIONAL should have integer value 5."""
        assert FramePriority.INFORMATIONAL == 5

    def test_ordering_preserved(self):
        """IntEnum ordering should be preserved (lower = higher priority)."""
        assert FramePriority.CRITICAL < FramePriority.HIGH
        assert FramePriority.HIGH < FramePriority.MEDIUM
        assert FramePriority.MEDIUM < FramePriority.LOW
        assert FramePriority.LOW < FramePriority.INFORMATIONAL
