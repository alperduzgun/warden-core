"""
Tests for DashboardMetrics model.

Verifies Panel JSON compatibility for dashboard metrics.
"""

import pytest
from datetime import datetime

from warden.reports.domain.models import DashboardMetrics
from tests.helpers.panel_test_utils import (
    assert_no_snake_case,
    json_roundtrip_test,
    assert_panel_compatible_date,
    assert_panel_trend_valid,
)


def test_dashboard_metrics_to_json():
    """Test DashboardMetrics serialization to Panel JSON."""
    metrics = DashboardMetrics(
        total_issues=42,
        critical_issues=3,
        high_issues=8,
        medium_issues=15,
        low_issues=16,
        overall_score=72.5,
        trend="improving",
        last_scan_time=datetime(2025, 12, 21, 10, 30, 0),
        files_scanned=123,
        lines_scanned=5432,
    )

    json_data = metrics.to_json()

    # Check camelCase keys
    assert "totalIssues" in json_data
    assert "criticalIssues" in json_data
    assert "highIssues" in json_data
    assert "mediumIssues" in json_data
    assert "lowIssues" in json_data
    assert "overallScore" in json_data
    assert "trend" in json_data
    assert "lastScanTime" in json_data
    assert "filesScanned" in json_data
    assert "linesScanned" in json_data

    # No snake_case
    assert_no_snake_case(json_data)

    # Check values
    assert json_data["totalIssues"] == 42
    assert json_data["criticalIssues"] == 3
    assert json_data["highIssues"] == 8
    assert json_data["mediumIssues"] == 15
    assert json_data["lowIssues"] == 16
    assert json_data["overallScore"] == 72.5
    assert json_data["trend"] == "improving"
    assert json_data["filesScanned"] == 123
    assert json_data["linesScanned"] == 5432

    # Check date format
    assert_panel_compatible_date(json_data["lastScanTime"])
    assert json_data["lastScanTime"] == "2025-12-21T10:30:00"


def test_dashboard_metrics_from_json():
    """Test DashboardMetrics deserialization from Panel JSON."""
    json_data = {
        "totalIssues": 42,
        "criticalIssues": 3,
        "highIssues": 8,
        "mediumIssues": 15,
        "lowIssues": 16,
        "overallScore": 72.5,
        "trend": "improving",
        "lastScanTime": "2025-12-21T10:30:00",
        "filesScanned": 123,
        "linesScanned": 5432,
    }

    metrics = DashboardMetrics.from_json(json_data)

    # Check snake_case fields
    assert metrics.total_issues == 42
    assert metrics.critical_issues == 3
    assert metrics.high_issues == 8
    assert metrics.medium_issues == 15
    assert metrics.low_issues == 16
    assert metrics.overall_score == 72.5
    assert metrics.trend == "improving"
    assert metrics.files_scanned == 123
    assert metrics.lines_scanned == 5432

    # Check datetime parsing
    assert isinstance(metrics.last_scan_time, datetime)
    assert metrics.last_scan_time == datetime(2025, 12, 21, 10, 30, 0)


def test_dashboard_metrics_roundtrip():
    """Test DashboardMetrics JSON serialization roundtrip."""
    original = DashboardMetrics(
        total_issues=100,
        critical_issues=10,
        high_issues=20,
        medium_issues=30,
        low_issues=40,
        overall_score=65.0,
        trend="stable",
        last_scan_time=datetime(2025, 12, 21, 15, 45, 30),
        files_scanned=250,
        lines_scanned=12000,
    )

    json_data = json_roundtrip_test(original, DashboardMetrics)

    # Additional assertions
    assert json_data["totalIssues"] == 100
    assert json_data["trend"] == "stable"


def test_dashboard_metrics_trend_values():
    """Test all valid Panel trend values."""
    trends = ["improving", "stable", "degrading"]

    for trend in trends:
        metrics = DashboardMetrics(
            total_issues=10,
            critical_issues=1,
            high_issues=2,
            medium_issues=3,
            low_issues=4,
            overall_score=80.0,
            trend=trend,
            last_scan_time=datetime.now(),
            files_scanned=50,
            lines_scanned=1000,
        )

        json_data = metrics.to_json()
        assert_panel_trend_valid(json_data["trend"])


def test_dashboard_metrics_zero_issues():
    """Test DashboardMetrics with zero issues."""
    metrics = DashboardMetrics(
        total_issues=0,
        critical_issues=0,
        high_issues=0,
        medium_issues=0,
        low_issues=0,
        overall_score=100.0,
        trend="stable",
        last_scan_time=datetime.now(),
        files_scanned=0,
        lines_scanned=0,
    )

    json_data = metrics.to_json()

    assert json_data["totalIssues"] == 0
    assert json_data["overallScore"] == 100.0


def test_dashboard_metrics_high_volume():
    """Test DashboardMetrics with high volume numbers."""
    metrics = DashboardMetrics(
        total_issues=10000,
        critical_issues=1000,
        high_issues=2000,
        medium_issues=3000,
        low_issues=4000,
        overall_score=25.5,
        trend="degrading",
        last_scan_time=datetime(2025, 12, 21, 23, 59, 59),
        files_scanned=5000,
        lines_scanned=500000,
    )

    json_data = metrics.to_json()

    assert json_data["totalIssues"] == 10000
    assert json_data["linesScanned"] == 500000
    assert json_data["overallScore"] == 25.5


def test_dashboard_metrics_datetime_with_microseconds():
    """Test DashboardMetrics datetime serialization with microseconds."""
    dt = datetime(2025, 12, 21, 10, 30, 0, 123456)
    metrics = DashboardMetrics(
        total_issues=5,
        critical_issues=1,
        high_issues=1,
        medium_issues=1,
        low_issues=2,
        overall_score=90.0,
        trend="improving",
        last_scan_time=dt,
        files_scanned=10,
        lines_scanned=500,
    )

    json_data = metrics.to_json()

    # Should include microseconds
    assert_panel_compatible_date(json_data["lastScanTime"])
    assert ".123456" in json_data["lastScanTime"]


def test_dashboard_metrics_issue_count_consistency():
    """Test that total_issues matches sum of severity counts."""
    metrics = DashboardMetrics(
        total_issues=30,
        critical_issues=5,
        high_issues=10,
        medium_issues=8,
        low_issues=7,
        overall_score=70.0,
        trend="improving",
        last_scan_time=datetime.now(),
        files_scanned=100,
        lines_scanned=5000,
    )

    # Verify sum
    severity_sum = (
        metrics.critical_issues
        + metrics.high_issues
        + metrics.medium_issues
        + metrics.low_issues
    )
    assert severity_sum == metrics.total_issues
