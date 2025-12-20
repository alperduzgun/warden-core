"""
Tests for Fortification Models

Tests Panel JSON compatibility and data model correctness.
"""

import pytest
from datetime import datetime

from warden.analyzers.fortification.models import (
    FortificationAction,
    FortificationActionType,
    FortificationResult,
    FortifierPriority,
)


class TestFortificationAction:
    """Test FortificationAction model."""

    def test_to_json_camelcase(self):
        """Test JSON serialization uses camelCase."""
        action = FortificationAction(
            type=FortificationActionType.ERROR_HANDLING,
            description="Add try-except block",
            line_number=42,
            severity="High",
        )

        json_data = action.to_json()

        # Panel expects camelCase
        assert "lineNumber" in json_data
        assert "line_number" not in json_data

        assert json_data["lineNumber"] == 42
        assert json_data["description"] == "Add try-except block"
        assert json_data["type"] == "error_handling"
        assert json_data["severity"] == "High"

    def test_from_json_roundtrip(self):
        """Test JSON deserialization roundtrip."""
        original = FortificationAction(
            type=FortificationActionType.LOGGING,
            description="Add logging",
            line_number=10,
            severity="Medium",
        )

        json_data = original.to_json()
        parsed = FortificationAction.from_json(json_data)

        assert parsed.type == original.type
        assert parsed.description == original.description
        assert parsed.line_number == original.line_number
        assert parsed.severity == original.severity


class TestFortificationResult:
    """Test FortificationResult model."""

    def test_to_json_camelcase(self):
        """Test JSON serialization uses camelCase."""
        result = FortificationResult(
            success=True,
            original_code="print('hello')",
            fortified_code="try:\n    print('hello')\nexcept Exception as e:\n    logger.error(e)",
            actions=[
                FortificationAction(
                    type=FortificationActionType.ERROR_HANDLING,
                    description="Added error handling",
                    line_number=1,
                )
            ],
            summary="Added 1 improvement",
            fortifier_name="Error Handling",
        )

        json_data = result.to_json()

        # Panel expects camelCase
        assert "originalCode" in json_data
        assert "fortifiedCode" in json_data
        assert "fortifierName" in json_data
        assert "errorMessage" in json_data

        # NOT snake_case
        assert "original_code" not in json_data
        assert "fortified_code" not in json_data

        assert json_data["success"] is True
        assert json_data["summary"] == "Added 1 improvement"
        assert len(json_data["actions"]) == 1

    def test_from_json_roundtrip(self):
        """Test JSON deserialization roundtrip."""
        original = FortificationResult(
            success=True,
            original_code="code",
            fortified_code="fortified",
            summary="test",
            fortifier_name="Test",
        )

        json_data = original.to_json()
        parsed = FortificationResult.from_json(json_data)

        assert parsed.success == original.success
        assert parsed.original_code == original.original_code
        assert parsed.fortified_code == original.fortified_code
        assert parsed.summary == original.summary

    def test_error_message_none_serialization(self):
        """Test that None error_message is properly serialized."""
        result = FortificationResult(
            success=True,
            original_code="code",
            fortified_code="code",
            error_message=None,
        )

        json_data = result.to_json()

        assert json_data["errorMessage"] is None


class TestFortifierPriority:
    """Test FortifierPriority enum."""

    def test_priority_ordering(self):
        """Test that CRITICAL < HIGH < MEDIUM < LOW."""
        assert FortifierPriority.CRITICAL.value < FortifierPriority.HIGH.value
        assert FortifierPriority.HIGH.value < FortifierPriority.MEDIUM.value
        assert FortifierPriority.MEDIUM.value < FortifierPriority.LOW.value
