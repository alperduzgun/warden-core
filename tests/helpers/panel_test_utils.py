"""
Test utilities for Panel JSON compatibility testing.

These utilities help ensure that Core domain models serialize correctly
to Panel-compatible JSON format (camelCase, correct types, etc.).
"""

import json
from typing import Any, Dict, Type, TypeVar

T = TypeVar("T")


def assert_camel_case_keys(data: Dict[str, Any]) -> None:
    """
    Assert all keys in dict are camelCase (not snake_case).

    Recursively checks nested dictionaries and lists.

    Args:
        data: Dictionary to check

    Raises:
        AssertionError: If any snake_case key is found

    Examples:
        >>> assert_camel_case_keys({"filePath": "test.py"})
        # Passes

        >>> assert_camel_case_keys({"file_path": "test.py"})
        AssertionError: Found snake_case key: file_path
    """
    for key in data.keys():
        assert "_" not in key, f"Found snake_case key: {key}"
        if isinstance(data[key], dict):
            assert_camel_case_keys(data[key])
        elif isinstance(data[key], list):
            for item in data[key]:
                if isinstance(item, dict):
                    assert_camel_case_keys(item)


def assert_no_snake_case(data: Dict[str, Any]) -> None:
    """
    Recursively check for snake_case keys.

    Similar to assert_camel_case_keys but with a different error message.

    Args:
        data: Dictionary to check

    Raises:
        AssertionError: If any snake_case key is found
    """
    for key, value in data.items():
        assert "_" not in key, f"snake_case found: {key}"
        if isinstance(value, dict):
            assert_no_snake_case(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    assert_no_snake_case(item)


def json_roundtrip_test(model_instance: Any, model_class: Type[T]) -> Dict[str, Any]:
    """
    Test model serialization/deserialization roundtrip.

    Verifies:
    1. Model serializes to valid JSON
    2. JSON uses camelCase keys (no snake_case)
    3. JSON can be deserialized back to model
    4. Roundtrip preserves data (serialized → deserialized == original)

    Args:
        model_instance: Instance of model to test
        model_class: Model class with from_json() classmethod

    Returns:
        Serialized JSON data (for further assertions)

    Raises:
        AssertionError: If roundtrip fails or snake_case found

    Examples:
        >>> from warden.reports.domain.models import DashboardMetrics
        >>> from datetime import datetime
        >>> metrics = DashboardMetrics(
        ...     total_issues=42,
        ...     critical_issues=3,
        ...     high_issues=8,
        ...     medium_issues=15,
        ...     low_issues=16,
        ...     overall_score=72.5,
        ...     trend="improving",
        ...     last_scan_time=datetime(2025, 12, 21, 10, 30, 0),
        ...     files_scanned=123,
        ...     lines_scanned=5432
        ... )
        >>> json_data = json_roundtrip_test(metrics, DashboardMetrics)
        >>> json_data['totalIssues']
        42
    """
    # Serialize
    json_data = model_instance.to_json()

    # Check camelCase
    assert_no_snake_case(json_data)

    # Check it's valid JSON (can be stringified)
    json_str = json.dumps(json_data)
    assert len(json_str) > 0

    # Deserialize
    parsed = model_class.from_json(json_data)

    # Compare (basic equality check)
    # Note: This may not work for all models if __eq__ isn't implemented
    # For dataclasses with default __eq__, this should work
    assert parsed == model_instance, "Roundtrip failed: deserialized != original"

    return json_data


def assert_panel_compatible_date(date_str: str) -> None:
    """
    Assert date string is in Panel-compatible ISO 8601 format.

    Panel expects: "2025-12-21T10:30:00" or "2025-12-21T10:30:00.123456"

    Args:
        date_str: Date string to validate

    Raises:
        AssertionError: If format is invalid

    Examples:
        >>> assert_panel_compatible_date("2025-12-21T10:30:00")
        # Passes

        >>> assert_panel_compatible_date("2025-12-21T10:30:00.123456")
        # Passes

        >>> assert_panel_compatible_date("2025-12-21")
        AssertionError: Invalid ISO 8601 format
    """
    from datetime import datetime

    # Try to parse as ISO 8601
    try:
        datetime.fromisoformat(date_str)
    except ValueError as e:
        raise AssertionError(f"Invalid ISO 8601 format: {date_str}") from e

    # Check format (should contain 'T')
    assert "T" in date_str, f"Missing 'T' separator in ISO 8601 date: {date_str}"


def assert_panel_status_valid(status: str) -> None:
    """
    Assert status is a valid Panel status value.

    Panel expects: 'running' | 'success' | 'failed' | 'pending'

    Args:
        status: Status string to validate

    Raises:
        AssertionError: If status is invalid

    Examples:
        >>> assert_panel_status_valid("running")
        # Passes

        >>> assert_panel_status_valid("completed")
        AssertionError: Invalid Panel status
    """
    valid_statuses = {"running", "success", "failed", "pending"}
    assert (
        status in valid_statuses
    ), f"Invalid Panel status: {status}. Expected one of {valid_statuses}"


def assert_panel_priority_valid(priority: str) -> None:
    """
    Assert priority is a valid Panel priority value.

    Panel expects: 'critical' | 'high' | 'medium' | 'low'

    Args:
        priority: Priority string to validate

    Raises:
        AssertionError: If priority is invalid

    Examples:
        >>> assert_panel_priority_valid("critical")
        # Passes

        >>> assert_panel_priority_valid("CRITICAL")
        AssertionError: Invalid Panel priority
    """
    valid_priorities = {"critical", "high", "medium", "low"}
    assert (
        priority in valid_priorities
    ), f"Invalid Panel priority: {priority}. Expected one of {valid_priorities}"


def assert_panel_trend_valid(trend: str) -> None:
    """
    Assert trend is a valid Panel trend value.

    Panel expects: 'improving' | 'stable' | 'degrading'

    Args:
        trend: Trend string to validate

    Raises:
        AssertionError: If trend is invalid

    Examples:
        >>> assert_panel_trend_valid("improving")
        # Passes

        >>> assert_panel_trend_valid("IMPROVING")
        AssertionError: Invalid Panel trend
    """
    valid_trends = {"improving", "stable", "degrading"}
    assert (
        trend in valid_trends
    ), f"Invalid Panel trend: {trend}. Expected one of {valid_trends}"
