"""
Tests for SpecFrame Configuration Validator.

Tests validation of platform configurations with comprehensive checks.
"""

from pathlib import Path

import pytest

from warden.validation.frames.spec.validation import (
    SpecConfigValidator,
    ValidationResult,
    ValidationIssue,
    IssueSeverity,
)
from warden.validation.frames.spec.models import PlatformType, PlatformRole


@pytest.fixture
def validator(tmp_path):
    """Create a validator with temporary project root."""
    warden_dir = tmp_path / ".warden"
    warden_dir.mkdir()
    return SpecConfigValidator(project_root=tmp_path)


@pytest.fixture
def valid_platforms(tmp_path):
    """Create valid platform configurations."""
    # Create actual directories
    mobile_dir = tmp_path / "mobile"
    mobile_dir.mkdir()
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()

    return [
        {
            "name": "mobile",
            "path": "mobile",
            "type": "flutter",
            "role": "consumer",
        },
        {
            "name": "backend",
            "path": "backend",
            "type": "spring-boot",
            "role": "provider",
        },
    ]


def test_valid_configuration(validator, valid_platforms):
    """Test validation of valid configuration."""
    result = validator.validate_platforms(valid_platforms)

    assert result.is_valid
    assert result.error_count == 0
    assert result.warning_count == 0
    assert result.metadata["consumer_count"] == 1
    assert result.metadata["provider_count"] == 1


def test_minimum_platforms_requirement(validator, tmp_path):
    """Test that at least 2 platforms are required."""
    mobile_dir = tmp_path / "mobile"
    mobile_dir.mkdir()

    platforms = [
        {
            "name": "mobile",
            "path": "mobile",
            "type": "flutter",
            "role": "consumer",
        }
    ]

    result = validator.validate_platforms(platforms)

    assert not result.is_valid
    assert result.error_count >= 1
    assert any("At least 2 platforms" in i.message for i in result.issues)


def test_missing_required_fields(validator, tmp_path):
    """Test validation fails for missing required fields."""
    platforms = [
        {
            "name": "mobile",
            # Missing path, type, role
        },
        {
            "name": "backend",
            "path": "backend",
            "type": "spring",
            "role": "provider",
        },
    ]

    result = validator.validate_platforms(platforms)

    assert not result.is_valid
    assert result.error_count >= 3  # Missing path, type, role

    # Check error messages
    error_messages = [i.message for i in result.issues]
    assert any("Missing required field: path" in m for m in error_messages)
    assert any("Missing required field: type" in m for m in error_messages)
    assert any("Missing required field: role" in m for m in error_messages)


def test_invalid_platform_type(validator, tmp_path):
    """Test validation fails for invalid platform type."""
    mobile_dir = tmp_path / "mobile"
    mobile_dir.mkdir()

    platforms = [
        {
            "name": "mobile",
            "path": "mobile",
            "type": "invalid_platform",
            "role": "consumer",
        },
        {
            "name": "backend",
            "path": "backend",
            "type": "spring",
            "role": "provider",
        },
    ]

    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()

    result = validator.validate_platforms(platforms)

    assert not result.is_valid
    assert any("Invalid platform type" in i.message for i in result.issues)


def test_invalid_platform_role(validator, tmp_path):
    """Test validation fails for invalid platform role."""
    mobile_dir = tmp_path / "mobile"
    mobile_dir.mkdir()
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()

    platforms = [
        {
            "name": "mobile",
            "path": "mobile",
            "type": "flutter",
            "role": "invalid_role",
        },
        {
            "name": "backend",
            "path": "backend",
            "type": "spring",
            "role": "provider",
        },
    ]

    result = validator.validate_platforms(platforms)

    assert not result.is_valid
    assert any("Invalid platform role" in i.message for i in result.issues)


def test_nonexistent_path(validator, tmp_path):
    """Test validation fails for nonexistent paths."""
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()

    platforms = [
        {
            "name": "mobile",
            "path": "nonexistent_mobile",
            "type": "flutter",
            "role": "consumer",
        },
        {
            "name": "backend",
            "path": "backend",
            "type": "spring",
            "role": "provider",
        },
    ]

    result = validator.validate_platforms(platforms)

    assert not result.is_valid
    assert any("path does not exist" in i.message for i in result.issues)


def test_path_is_file_not_directory(validator, tmp_path):
    """Test validation fails when path is a file, not directory."""
    # Create a file instead of directory
    mobile_file = tmp_path / "mobile.txt"
    mobile_file.write_text("test")

    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()

    platforms = [
        {
            "name": "mobile",
            "path": "mobile.txt",
            "type": "flutter",
            "role": "consumer",
        },
        {
            "name": "backend",
            "path": "backend",
            "type": "spring",
            "role": "provider",
        },
    ]

    result = validator.validate_platforms(platforms)

    assert not result.is_valid
    assert any("not a directory" in i.message for i in result.issues)


def test_no_consumer_platforms(validator, tmp_path):
    """Test validation fails when no consumer platforms configured."""
    backend1 = tmp_path / "backend1"
    backend1.mkdir()
    backend2 = tmp_path / "backend2"
    backend2.mkdir()

    platforms = [
        {
            "name": "backend1",
            "path": "backend1",
            "type": "spring",
            "role": "provider",
        },
        {
            "name": "backend2",
            "path": "backend2",
            "type": "fastapi",
            "role": "provider",
        },
    ]

    result = validator.validate_platforms(platforms)

    assert not result.is_valid
    assert any("No consumer platforms" in i.message for i in result.issues)


def test_no_provider_platforms(validator, tmp_path):
    """Test validation fails when no provider platforms configured."""
    mobile1 = tmp_path / "mobile1"
    mobile1.mkdir()
    mobile2 = tmp_path / "mobile2"
    mobile2.mkdir()

    platforms = [
        {
            "name": "mobile1",
            "path": "mobile1",
            "type": "flutter",
            "role": "consumer",
        },
        {
            "name": "mobile2",
            "path": "mobile2",
            "type": "react",
            "role": "consumer",
        },
    ]

    result = validator.validate_platforms(platforms)

    assert not result.is_valid
    assert any("No provider platforms" in i.message for i in result.issues)


def test_duplicate_platform_names(validator, tmp_path):
    """Test validation fails for duplicate platform names."""
    mobile_dir = tmp_path / "mobile"
    mobile_dir.mkdir()
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()

    platforms = [
        {
            "name": "mobile",
            "path": "mobile",
            "type": "flutter",
            "role": "consumer",
        },
        {
            "name": "mobile",  # Duplicate name
            "path": "backend",
            "type": "spring",
            "role": "provider",
        },
    ]

    result = validator.validate_platforms(platforms)

    assert not result.is_valid
    assert any("Duplicate platform name" in i.message for i in result.issues)


def test_duplicate_platform_paths_warning(validator, tmp_path):
    """Test warning for duplicate platform paths."""
    mobile_dir = tmp_path / "mobile"
    mobile_dir.mkdir()
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()

    platforms = [
        {
            "name": "mobile_flutter",
            "path": "mobile",
            "type": "flutter",
            "role": "consumer",
        },
        {
            "name": "mobile_universal",
            "path": "mobile",  # Same path
            "type": "universal",
            "role": "consumer",
        },
        {
            "name": "backend",
            "path": "backend",
            "type": "spring",
            "role": "provider",
        },
    ]

    result = validator.validate_platforms(platforms)

    # Should have warning, but still valid (intentional multiple extractors)
    assert result.warning_count >= 1
    assert any("Duplicate platform path" in i.message for i in result.issues)


def test_both_role_counts_as_both(validator, tmp_path):
    """Test that 'both' role counts as both consumer and provider."""
    bff_dir = tmp_path / "bff"
    bff_dir.mkdir()
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()

    platforms = [
        {
            "name": "bff",
            "path": "bff",
            "type": "react",
            "role": "both",
        },
        {
            "name": "backend",
            "path": "backend",
            "type": "spring",
            "role": "provider",
        },
    ]

    result = validator.validate_platforms(platforms)

    assert result.is_valid
    # BFF counts as both
    assert result.metadata["consumer_count"] >= 1
    assert result.metadata["provider_count"] >= 1


def test_absolute_path_resolution(tmp_path):
    """Test that absolute paths are handled correctly."""
    mobile_dir = tmp_path / "mobile"
    mobile_dir.mkdir()
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()

    warden_dir = tmp_path / ".warden"
    warden_dir.mkdir()

    validator = SpecConfigValidator(project_root=tmp_path)

    platforms = [
        {
            "name": "mobile",
            "path": str(mobile_dir.absolute()),  # Absolute path
            "type": "flutter",
            "role": "consumer",
        },
        {
            "name": "backend",
            "path": "backend",  # Relative path
            "type": "spring",
            "role": "provider",
        },
    ]

    result = validator.validate_platforms(platforms)

    assert result.is_valid


def test_validation_issue_serialization():
    """Test ValidationIssue serialization."""
    issue = ValidationIssue(
        severity=IssueSeverity.ERROR,
        message="Test error",
        field="test_field",
        suggestion="Fix it",
        platform_name="test_platform",
    )

    data = issue.to_dict()

    assert data["severity"] == "error"
    assert data["message"] == "Test error"
    assert data["field"] == "test_field"
    assert data["suggestion"] == "Fix it"
    assert data["platform_name"] == "test_platform"


def test_validation_result_serialization():
    """Test ValidationResult serialization."""
    result = ValidationResult(
        is_valid=False,
        issues=[
            ValidationIssue(
                severity=IssueSeverity.ERROR,
                message="Error 1",
                field="field1",
            ),
            ValidationIssue(
                severity=IssueSeverity.WARNING,
                message="Warning 1",
                field="field2",
            ),
        ],
        metadata={"test": "data"},
    )

    data = result.to_dict()

    assert data["is_valid"] is False
    assert data["error_count"] == 1
    assert data["warning_count"] == 1
    assert len(data["issues"]) == 2
    assert data["metadata"]["test"] == "data"


def test_has_errors_property():
    """Test ValidationResult.has_errors property."""
    result_with_errors = ValidationResult(
        is_valid=False,
        issues=[
            ValidationIssue(
                severity=IssueSeverity.ERROR,
                message="Error",
                field="field",
            )
        ],
    )

    result_without_errors = ValidationResult(
        is_valid=True,
        issues=[
            ValidationIssue(
                severity=IssueSeverity.WARNING,
                message="Warning",
                field="field",
            )
        ],
    )

    assert result_with_errors.has_errors
    assert not result_without_errors.has_errors


def test_has_warnings_property():
    """Test ValidationResult.has_warnings property."""
    result_with_warnings = ValidationResult(
        is_valid=True,
        issues=[
            ValidationIssue(
                severity=IssueSeverity.WARNING,
                message="Warning",
                field="field",
            )
        ],
    )

    result_without_warnings = ValidationResult(
        is_valid=False,
        issues=[
            ValidationIssue(
                severity=IssueSeverity.ERROR,
                message="Error",
                field="field",
            )
        ],
    )

    assert result_with_warnings.has_warnings
    assert not result_without_warnings.has_warnings


def test_empty_platforms_list(validator):
    """Test validation with empty platforms list."""
    result = validator.validate_platforms([])

    assert not result.is_valid
    assert result.error_count >= 1
    assert any("At least 2 platforms" in i.message for i in result.issues)


def test_all_platform_types_valid(validator, tmp_path):
    """Test that all PlatformType enum values are considered valid."""
    for platform_type in PlatformType:
        mobile_dir = tmp_path / f"mobile_{platform_type.value}"
        mobile_dir.mkdir(exist_ok=True)
        backend_dir = tmp_path / f"backend_{platform_type.value}"
        backend_dir.mkdir(exist_ok=True)

        platforms = [
            {
                "name": "mobile",
                "path": str(mobile_dir),
                "type": platform_type.value,
                "role": "consumer",
            },
            {
                "name": "backend",
                "path": str(backend_dir),
                "type": "spring",
                "role": "provider",
            },
        ]

        result = validator.validate_platforms(platforms)

        # Should not have "Invalid platform type" error
        assert not any(
            "Invalid platform type" in i.message and platform_type.value in i.message
            for i in result.issues
        )


def test_suggestions_are_helpful(validator, tmp_path):
    """Test that validation issues include helpful suggestions."""
    platforms = [
        {
            "name": "mobile",
            "path": "nonexistent",
            "type": "invalid_type",
            "role": "invalid_role",
        }
    ]

    result = validator.validate_platforms(platforms)

    # All errors should have suggestions
    for issue in result.issues:
        if issue.severity == IssueSeverity.ERROR:
            assert issue.suggestion is not None
            assert len(issue.suggestion) > 0
