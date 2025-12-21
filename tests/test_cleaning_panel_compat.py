"""
Tests for Cleaning model Panel JSON compatibility.

Validates that Cleaning and CleaningResult models correctly
serialize to Panel-compatible JSON format (camelCase).
"""

import pytest

from warden.cleaning.domain.models import Cleaning, CleaningResult


class TestCleaningModel:
    """Test Cleaning model."""

    def test_cleaning_creation(self):
        """Should create Cleaning with required fields."""
        cleaning = Cleaning(
            id="clean-1",
            title="Remove unused imports",
            detail="Delete unused numpy import"
        )

        assert cleaning.id == "clean-1"
        assert cleaning.title == "Remove unused imports"
        assert cleaning.detail == "Delete unused numpy import"

    def test_cleaning_to_json(self):
        """Should serialize to Panel-compatible JSON."""
        cleaning = Cleaning(
            id="clean-1",
            title="Remove dead code",
            detail="Remove function <code>legacy_handler()</code> (unused)"
        )

        json_data = cleaning.to_json()

        assert json_data == {
            "id": "clean-1",
            "title": "Remove dead code",
            "detail": "Remove function <code>legacy_handler()</code> (unused)"
        }

    def test_cleaning_detail_supports_html(self):
        """Detail field should support HTML tags for Panel rendering."""
        cleaning = Cleaning(
            id="clean-1",
            title="Simplify logic",
            detail="Replace <code>if x == True:</code> with <code>if x:</code>"
        )

        json_data = cleaning.to_json()

        assert "<code>" in json_data["detail"]
        assert "</code>" in json_data["detail"]


class TestCleaningResultModel:
    """Test CleaningResult model."""

    def test_cleaning_result_empty(self):
        """Should create empty CleaningResult."""
        result = CleaningResult()

        assert result.cleanings == []
        assert result.files_modified == []
        assert result.duration == 0.0

    def test_cleaning_result_with_data(self):
        """Should create CleaningResult with cleanings."""
        cleanings = [
            Cleaning(id="clean-1", title="Remove imports", detail="Unused imports"),
            Cleaning(id="clean-2", title="Simplify logic", detail="Boolean comparison")
        ]

        result = CleaningResult(
            cleanings=cleanings,
            files_modified=["main.py", "utils.py"],
            duration=0.8
        )

        assert len(result.cleanings) == 2
        assert len(result.files_modified) == 2
        assert result.duration == 0.8

    def test_cleaning_result_to_json(self):
        """Should serialize to Panel-compatible JSON with camelCase."""
        cleanings = [
            Cleaning(id="clean-1", title="Remove imports", detail="Unused imports"),
            Cleaning(id="clean-2", title="Simplify logic", detail="Boolean logic")
        ]

        result = CleaningResult(
            cleanings=cleanings,
            files_modified=["main.py"],
            duration=0.567
        )

        json_data = result.to_json()

        # Check top-level structure
        assert "cleanings" in json_data
        assert "filesModified" in json_data  # camelCase!
        assert "duration" in json_data

        # Check cleanings array
        assert len(json_data["cleanings"]) == 2
        assert json_data["cleanings"][0]["id"] == "clean-1"

        # Check files modified
        assert json_data["filesModified"] == ["main.py"]

        # Check duration format (string with unit)
        assert json_data["duration"] == "0.6s"

    def test_duration_formatting(self):
        """Duration should be formatted as string with 's' suffix."""
        result = CleaningResult(duration=1.234)
        json_data = result.to_json()

        assert json_data["duration"] == "1.2s"  # Rounded to 1 decimal
        assert isinstance(json_data["duration"], str)

    def test_empty_cleaning_result_to_json(self):
        """Empty result should serialize correctly."""
        result = CleaningResult()
        json_data = result.to_json()

        assert json_data["cleanings"] == []
        assert json_data["filesModified"] == []
        assert json_data["duration"] == "0.0s"


class TestCleaningPanelCompatibility:
    """Test Panel JSON compatibility end-to-end."""

    def test_panel_expected_structure(self):
        """JSON should match Panel's expected structure exactly."""
        # Simulate a realistic cleaning
        cleanings = [
            Cleaning(
                id="clean-1",
                title="Removed 3 unused imports from user_service.py",
                detail="Removed <code>numpy</code>, <code>pandas</code>, <code>matplotlib</code>"
            ),
            Cleaning(
                id="clean-2",
                title="Simplified boolean comparisons in auth.py",
                detail="Replaced <code>if is_valid == True:</code> with <code>if is_valid:</code>"
            )
        ]

        result = CleaningResult(
            cleanings=cleanings,
            files_modified=["src/user_service.py", "src/auth.py"],
            duration=0.4
        )

        json_data = result.to_json()

        # Panel expects this exact structure
        assert "cleanings" in json_data
        assert "filesModified" in json_data
        assert "duration" in json_data

        # Verify cleanings structure
        assert len(json_data["cleanings"]) == 2
        first_clean = json_data["cleanings"][0]
        assert "id" in first_clean
        assert "title" in first_clean
        assert "detail" in first_clean

        # Verify camelCase (not snake_case)
        assert "files_modified" not in json_data

    def test_no_snake_case_in_json(self):
        """JSON should not contain snake_case keys (Panel expects camelCase)."""
        result = CleaningResult(
            cleanings=[],
            files_modified=["test.py"],
            duration=0.5
        )

        json_data = result.to_json()

        # Convert to JSON string to check for snake_case
        import json
        json_string = json.dumps(json_data)

        # Should NOT contain snake_case
        assert "files_modified" not in json_string

        # Should contain camelCase
        assert "filesModified" in json_string

    def test_roundtrip_serialization(self):
        """Should be able to serialize and use in Panel."""
        original = CleaningResult(
            cleanings=[
                Cleaning(id="clean-1", title="Test", detail="Detail")
            ],
            files_modified=["test.py"],
            duration=0.8
        )

        json_data = original.to_json()

        # Verify Panel can consume this structure
        assert isinstance(json_data["cleanings"], list)
        assert isinstance(json_data["filesModified"], list)
        assert isinstance(json_data["duration"], str)
        assert json_data["duration"].endswith("s")

    def test_matches_fortification_pattern(self):
        """CleaningResult should follow same pattern as FortificationResult."""
        # Create similar structures
        from warden.fortification.domain.models import Fortification, FortificationResult

        fortification_result = FortificationResult(
            fortifications=[Fortification(id="f1", title="T", detail="D")],
            files_modified=["test.py"],
            duration=1.0
        )

        cleaning_result = CleaningResult(
            cleanings=[Cleaning(id="c1", title="T", detail="D")],
            files_modified=["test.py"],
            duration=1.0
        )

        fort_json = fortification_result.to_json()
        clean_json = cleaning_result.to_json()

        # Both should have same structure (different keys)
        assert set(fort_json.keys()) == {"fortifications", "filesModified", "duration"}
        assert set(clean_json.keys()) == {"cleanings", "filesModified", "duration"}

        # Duration format should be identical
        assert fort_json["duration"] == clean_json["duration"]
