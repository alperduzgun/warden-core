"""
Tests for ValidationTestDetails and related models Panel JSON compatibility.

Validates that test result models correctly serialize to Panel-compatible
JSON format (camelCase) and match Panel TypeScript interface structure.
"""

import pytest

from warden.validation.domain.test_results import (
    TestAssertion,
    TestResult,
    SecurityTestDetails,
    ChaosTestDetails,
    FuzzTestDetails,
    PropertyTestDetails,
    StressTestMetrics,
    StressTestDetails,
    ValidationTestDetails,
)


class TestTestAssertionModel:
    """Test TestAssertion model."""

    def test_assertion_creation_minimal(self):
        """Should create TestAssertion with minimal required fields."""
        assertion = TestAssertion(
            id="assert-1",
            description="User ID should not be null",
            passed=True
        )

        assert assertion.id == "assert-1"
        assert assertion.description == "User ID should not be null"
        assert assertion.passed is True
        assert assertion.error is None
        assert assertion.stack_trace is None
        assert assertion.duration is None

    def test_assertion_creation_with_error(self):
        """Should create TestAssertion with error details."""
        assertion = TestAssertion(
            id="assert-2",
            description="Should handle null input",
            passed=False,
            error="NullPointerException: user_id is null",
            stack_trace="File test.py, line 10",
            duration="0.1s"
        )

        assert assertion.passed is False
        assert assertion.error == "NullPointerException: user_id is null"
        assert assertion.stack_trace == "File test.py, line 10"

    def test_assertion_to_json_minimal(self):
        """Should serialize minimal assertion to Panel JSON."""
        assertion = TestAssertion(
            id="assert-1",
            description="Test description",
            passed=True
        )

        json_data = assertion.to_json()

        assert json_data == {
            "id": "assert-1",
            "description": "Test description",
            "passed": True
        }

    def test_assertion_to_json_with_error(self):
        """Should serialize assertion with error to Panel JSON."""
        assertion = TestAssertion(
            id="assert-1",
            description="Test",
            passed=False,
            error="Error message",
            stack_trace="Stack trace",
            duration="0.1s"
        )

        json_data = assertion.to_json()

        assert "stackTrace" in json_data  # camelCase!
        assert json_data["stackTrace"] == "Stack trace"
        assert json_data["error"] == "Error message"
        assert json_data["duration"] == "0.1s"


class TestTestResultModel:
    """Test TestResult model."""

    def test_test_result_creation(self):
        """Should create TestResult with assertions."""
        assertions = [
            TestAssertion(id="a1", description="Check 1", passed=True),
            TestAssertion(id="a2", description="Check 2", passed=True)
        ]

        result = TestResult(
            id="test-1",
            name="SQL Injection Test",
            status="passed",
            duration="1.2s",
            assertions=assertions
        )

        assert result.id == "test-1"
        assert result.name == "SQL Injection Test"
        assert result.status == "passed"
        assert len(result.assertions) == 2

    def test_test_result_to_json(self):
        """Should serialize to Panel-compatible JSON."""
        assertions = [
            TestAssertion(id="a1", description="Check 1", passed=True)
        ]

        result = TestResult(
            id="test-1",
            name="Test Name",
            status="passed",
            duration="1.0s",
            assertions=assertions
        )

        json_data = result.to_json()

        assert json_data["id"] == "test-1"
        assert json_data["name"] == "Test Name"
        assert json_data["status"] == "passed"
        assert json_data["duration"] == "1.0s"
        assert len(json_data["assertions"]) == 1

    def test_test_result_status_values(self):
        """Test status should be 'passed' | 'failed' | 'skipped'."""
        for status in ["passed", "failed", "skipped"]:
            result = TestResult(
                id="test-1",
                name="Test",
                status=status,
                duration="1.0s"
            )
            assert result.status == status


class TestSecurityTestDetails:
    """Test SecurityTestDetails model."""

    def test_security_test_details_creation(self):
        """Should create SecurityTestDetails with test categories."""
        sql_tests = [
            TestResult(id="sql-1", name="SQL Test", status="passed", duration="0.5s")
        ]
        xss_tests = [
            TestResult(id="xss-1", name="XSS Test", status="passed", duration="0.3s")
        ]

        details = SecurityTestDetails(
            sql_injection_tests=sql_tests,
            xss_tests=xss_tests
        )

        assert len(details.sql_injection_tests) == 1
        assert len(details.xss_tests) == 1

    def test_security_test_details_to_json(self):
        """Should serialize with camelCase keys."""
        sql_tests = [
            TestResult(id="sql-1", name="SQL Test", status="passed", duration="0.5s")
        ]

        details = SecurityTestDetails(sql_injection_tests=sql_tests)
        json_data = details.to_json()

        # Check camelCase conversion
        assert "sqlInjectionTests" in json_data
        assert "xssTests" in json_data
        assert "secretsScan" in json_data
        assert "authTests" in json_data

        # Check no snake_case
        assert "sql_injection_tests" not in json_data


class TestStressTestMetrics:
    """Test StressTestMetrics model."""

    def test_stress_test_metrics_creation(self):
        """Should create StressTestMetrics with performance data."""
        metrics = StressTestMetrics(
            requests_per_second=1000.5,
            latency_p50=10.2,
            latency_p95=25.8,
            latency_p99=45.3,
            max_concurrent_users=500,
            error_rate=0.5
        )

        assert metrics.requests_per_second == 1000.5
        assert metrics.max_concurrent_users == 500
        assert metrics.error_rate == 0.5

    def test_stress_test_metrics_to_json(self):
        """Should serialize with camelCase keys."""
        metrics = StressTestMetrics(
            requests_per_second=1000.0,
            latency_p50=10.0,
            latency_p95=20.0,
            latency_p99=30.0,
            max_concurrent_users=100,
            error_rate=1.0
        )

        json_data = metrics.to_json()

        # Check camelCase
        assert "requestsPerSecond" in json_data
        assert "latencyP50" in json_data
        assert "latencyP95" in json_data
        assert "latencyP99" in json_data
        assert "maxConcurrentUsers" in json_data
        assert "errorRate" in json_data

        # Check values
        assert json_data["requestsPerSecond"] == 1000.0
        assert json_data["maxConcurrentUsers"] == 100


class TestStressTestDetails:
    """Test StressTestDetails model."""

    def test_stress_test_details_with_metrics(self):
        """Should create StressTestDetails with metrics."""
        load_tests = [
            TestResult(id="load-1", name="Load Test", status="passed", duration="10.0s")
        ]

        metrics = StressTestMetrics(
            requests_per_second=500.0,
            latency_p50=15.0,
            latency_p95=30.0,
            latency_p99=50.0,
            max_concurrent_users=200,
            error_rate=0.1
        )

        details = StressTestDetails(
            load_tests=load_tests,
            metrics=metrics
        )

        assert len(details.load_tests) == 1
        assert details.metrics is not None

    def test_stress_test_details_to_json(self):
        """Should serialize with nested metrics."""
        metrics = StressTestMetrics(
            requests_per_second=100.0,
            latency_p50=10.0,
            latency_p95=20.0,
            latency_p99=30.0,
            max_concurrent_users=50,
            error_rate=0.0
        )

        details = StressTestDetails(
            load_tests=[],
            metrics=metrics
        )

        json_data = details.to_json()

        assert "loadTests" in json_data
        assert "metrics" in json_data
        assert isinstance(json_data["metrics"], dict)
        assert "requestsPerSecond" in json_data["metrics"]


class TestValidationTestDetails:
    """Test ValidationTestDetails aggregator model."""

    def test_validation_test_details_empty(self):
        """Should create empty ValidationTestDetails."""
        details = ValidationTestDetails()

        assert details.security is None
        assert details.chaos is None
        assert details.fuzz is None
        assert details.property is None
        assert details.stress is None

    def test_validation_test_details_with_security(self):
        """Should create ValidationTestDetails with security tests."""
        security = SecurityTestDetails(
            sql_injection_tests=[
                TestResult(id="sql-1", name="SQL Test", status="passed", duration="0.5s")
            ]
        )

        details = ValidationTestDetails(security=security)

        assert details.security is not None
        assert len(details.security.sql_injection_tests) == 1

    def test_validation_test_details_to_json_empty(self):
        """Empty ValidationTestDetails should serialize to empty object."""
        details = ValidationTestDetails()
        json_data = details.to_json()

        assert json_data == {}

    def test_validation_test_details_to_json_with_data(self):
        """Should serialize only non-None test categories."""
        security = SecurityTestDetails(
            sql_injection_tests=[
                TestResult(id="sql-1", name="SQL Test", status="passed", duration="0.5s")
            ]
        )

        chaos = ChaosTestDetails(
            network_failures=[
                TestResult(id="chaos-1", name="Network Test", status="passed", duration="1.0s")
            ]
        )

        details = ValidationTestDetails(
            security=security,
            chaos=chaos
            # fuzz, property, stress are None
        )

        json_data = details.to_json()

        # Should include only security and chaos
        assert "security" in json_data
        assert "chaos" in json_data
        assert "fuzz" not in json_data
        assert "property" not in json_data
        assert "stress" not in json_data

    def test_validation_test_details_complete(self):
        """Should handle all test categories."""
        details = ValidationTestDetails(
            security=SecurityTestDetails(),
            chaos=ChaosTestDetails(),
            fuzz=FuzzTestDetails(),
            property=PropertyTestDetails(),
            stress=StressTestDetails()
        )

        json_data = details.to_json()

        # All categories should be present
        assert "security" in json_data
        assert "chaos" in json_data
        assert "fuzz" in json_data
        assert "property" in json_data
        assert "stress" in json_data


class TestPanelCompatibilityIntegration:
    """Integration tests for Panel JSON compatibility."""

    def test_complete_test_results_structure(self):
        """Test complete test results structure matches Panel expectations."""
        # Build a complete test results structure
        security = SecurityTestDetails(
            sql_injection_tests=[
                TestResult(
                    id="sql-1",
                    name="SQL Injection - User Login",
                    status="passed",
                    duration="0.5s",
                    assertions=[
                        TestAssertion(
                            id="a1",
                            description="Should reject SQL in username",
                            passed=True
                        )
                    ]
                )
            ]
        )

        stress = StressTestDetails(
            load_tests=[
                TestResult(
                    id="load-1",
                    name="Load Test - 1000 RPS",
                    status="passed",
                    duration="60.0s"
                )
            ],
            metrics=StressTestMetrics(
                requests_per_second=1000.0,
                latency_p50=10.0,
                latency_p95=25.0,
                latency_p99=50.0,
                max_concurrent_users=500,
                error_rate=0.1
            )
        )

        details = ValidationTestDetails(
            security=security,
            stress=stress
        )

        json_data = details.to_json()

        # Verify Panel-compatible structure
        assert isinstance(json_data, dict)
        assert "security" in json_data
        assert "stress" in json_data

        # Verify nested structure (security)
        security_data = json_data["security"]
        assert "sqlInjectionTests" in security_data
        assert len(security_data["sqlInjectionTests"]) == 1

        # Verify test result structure
        test = security_data["sqlInjectionTests"][0]
        assert test["id"] == "sql-1"
        assert test["name"] == "SQL Injection - User Login"
        assert test["status"] == "passed"
        assert "assertions" in test

        # Verify assertion structure
        assertion = test["assertions"][0]
        assert assertion["id"] == "a1"
        assert assertion["passed"] is True

        # Verify stress metrics
        stress_data = json_data["stress"]
        assert "metrics" in stress_data
        assert stress_data["metrics"]["requestsPerSecond"] == 1000.0

    def test_no_snake_case_in_json_output(self):
        """Verify no snake_case keys in JSON output."""
        import json

        details = ValidationTestDetails(
            security=SecurityTestDetails(
                sql_injection_tests=[
                    TestResult(id="t1", name="Test", status="passed", duration="1s")
                ]
            ),
            stress=StressTestDetails(
                load_tests=[],
                metrics=StressTestMetrics(
                    requests_per_second=100.0,
                    latency_p50=10.0,
                    latency_p95=20.0,
                    latency_p99=30.0,
                    max_concurrent_users=50,
                    error_rate=0.0
                )
            )
        )

        json_str = json.dumps(details.to_json())

        # Should NOT contain snake_case
        assert "sql_injection_tests" not in json_str
        assert "load_tests" not in json_str
        assert "requests_per_second" not in json_str
        assert "max_concurrent_users" not in json_str
        assert "stack_trace" not in json_str

        # Should contain camelCase
        assert "sqlInjectionTests" in json_str
        assert "loadTests" in json_str
        assert "requestsPerSecond" in json_str
        assert "maxConcurrentUsers" in json_str
