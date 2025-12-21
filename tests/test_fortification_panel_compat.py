"""
Tests for Fortification model Panel JSON compatibility.

Validates that Fortification and FortificationResult models correctly
serialize to Panel-compatible JSON format (camelCase).
"""

import pytest

from warden.fortification.domain.models import Fortification, FortificationResult


class TestFortificationModel:
    """Test Fortification model."""

    def test_fortification_creation(self):
        """Should create Fortification with required fields."""
        fortification = Fortification(
            id="fort-1",
            title="Add error handling",
            detail="Wrap payment calls with try-catch"
        )

        assert fortification.id == "fort-1"
        assert fortification.title == "Add error handling"
        assert fortification.detail == "Wrap payment calls with try-catch"

    def test_fortification_to_json(self):
        """Should serialize to Panel-compatible JSON."""
        fortification = Fortification(
            id="fort-1",
            title="Add error handling",
            detail="Wrap <code>ProcessPaymentAsync()</code> with try-catch"
        )

        json_data = fortification.to_json()

        assert json_data == {
            "id": "fort-1",
            "title": "Add error handling",
            "detail": "Wrap <code>ProcessPaymentAsync()</code> with try-catch"
        }

    def test_fortification_detail_supports_html(self):
        """Detail field should support HTML tags for Panel rendering."""
        fortification = Fortification(
            id="fort-1",
            title="Add validation",
            detail="Add <code>if user_id is None: raise ValueError()</code>"
        )

        json_data = fortification.to_json()

        assert "<code>" in json_data["detail"]
        assert "</code>" in json_data["detail"]


class TestFortificationResultModel:
    """Test FortificationResult model."""

    def test_fortification_result_empty(self):
        """Should create empty FortificationResult."""
        result = FortificationResult()

        assert result.fortifications == []
        assert result.files_modified == []
        assert result.duration == 0.0

    def test_fortification_result_with_data(self):
        """Should create FortificationResult with fortifications."""
        fortifications = [
            Fortification(id="fort-1", title="Add try-catch", detail="Error handling"),
            Fortification(id="fort-2", title="Add validation", detail="Input validation")
        ]

        result = FortificationResult(
            fortifications=fortifications,
            files_modified=["user_service.py", "payment_service.py"],
            duration=1.5
        )

        assert len(result.fortifications) == 2
        assert len(result.files_modified) == 2
        assert result.duration == 1.5

    def test_fortification_result_to_json(self):
        """Should serialize to Panel-compatible JSON with camelCase."""
        fortifications = [
            Fortification(id="fort-1", title="Add try-catch", detail="Error handling"),
            Fortification(id="fort-2", title="Add validation", detail="Input validation")
        ]

        result = FortificationResult(
            fortifications=fortifications,
            files_modified=["user_service.py"],
            duration=1.234
        )

        json_data = result.to_json()

        # Check top-level structure
        assert "fortifications" in json_data
        assert "filesModified" in json_data  # camelCase!
        assert "duration" in json_data

        # Check fortifications array
        assert len(json_data["fortifications"]) == 2
        assert json_data["fortifications"][0]["id"] == "fort-1"

        # Check files modified
        assert json_data["filesModified"] == ["user_service.py"]

        # Check duration format (string with unit)
        assert json_data["duration"] == "1.2s"

    def test_duration_formatting(self):
        """Duration should be formatted as string with 's' suffix."""
        result = FortificationResult(duration=2.567)
        json_data = result.to_json()

        assert json_data["duration"] == "2.6s"  # Rounded to 1 decimal
        assert isinstance(json_data["duration"], str)

    def test_empty_fortification_result_to_json(self):
        """Empty result should serialize correctly."""
        result = FortificationResult()
        json_data = result.to_json()

        assert json_data["fortifications"] == []
        assert json_data["filesModified"] == []
        assert json_data["duration"] == "0.0s"


class TestFortificationPanelCompatibility:
    """Test Panel JSON compatibility end-to-end."""

    def test_panel_expected_structure(self):
        """JSON should match Panel's expected structure exactly."""
        # Simulate a realistic fortification
        fortifications = [
            Fortification(
                id="fort-1",
                title="Added try-catch around payment gateway calls",
                detail="Wraps <code>ProcessPaymentAsync()</code> with structured exception handling"
            ),
            Fortification(
                id="fort-2",
                title="Added input validation for user_id parameter",
                detail="Validates <code>user_id</code> is not null/empty before processing"
            )
        ]

        result = FortificationResult(
            fortifications=fortifications,
            files_modified=["src/services/payment_service.py", "src/services/user_service.py"],
            duration=0.8
        )

        json_data = result.to_json()

        # Panel expects this exact structure
        assert "fortifications" in json_data
        assert "filesModified" in json_data
        assert "duration" in json_data

        # Verify fortifications structure
        assert len(json_data["fortifications"]) == 2
        first_fort = json_data["fortifications"][0]
        assert "id" in first_fort
        assert "title" in first_fort
        assert "detail" in first_fort

        # Verify camelCase (not snake_case)
        assert "files_modified" not in json_data

    def test_no_snake_case_in_json(self):
        """JSON should not contain snake_case keys (Panel expects camelCase)."""
        result = FortificationResult(
            fortifications=[],
            files_modified=["test.py"],
            duration=1.0
        )

        json_data = result.to_json()

        # Convert to JSON string to check for snake_case
        import json
        json_string = json.dumps(json_data)

        # Should NOT contain snake_case
        assert "files_modified" not in json_string
        assert "duration_seconds" not in json_string

        # Should contain camelCase
        assert "filesModified" in json_string

    def test_roundtrip_serialization(self):
        """Should be able to serialize and use in Panel."""
        original = FortificationResult(
            fortifications=[
                Fortification(id="fort-1", title="Test", detail="Detail")
            ],
            files_modified=["test.py"],
            duration=1.5
        )

        json_data = original.to_json()

        # Verify Panel can consume this structure
        assert isinstance(json_data["fortifications"], list)
        assert isinstance(json_data["filesModified"], list)
        assert isinstance(json_data["duration"], str)
        assert json_data["duration"].endswith("s")
