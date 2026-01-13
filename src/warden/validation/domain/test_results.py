"""
Test results domain models.

These models represent detailed test execution results for validation frames.
Matches Panel TypeScript pipeline.ts types for JSON compatibility.

NOTE: These are placeholder models. Actual test execution logic is not yet implemented.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

from warden.shared.domain.base_model import BaseDomainModel


@dataclass
class TestAssertion(BaseDomainModel):
    """
    A single test assertion within a test.

    Attributes:
        id: Unique identifier for this assertion
        description: Human-readable description of what is being asserted
        passed: Whether the assertion passed
        error: Error message if assertion failed
        stack_trace: Stack trace if assertion failed
        duration: Time taken to execute this assertion (e.g., "0.1s")
    """

    id: str
    description: str
    passed: bool
    error: Optional[str] = None
    stack_trace: Optional[str] = None
    duration: Optional[str] = None

    def to_json(self) -> Dict[str, Any]:
        """
        Serialize to Panel-compatible JSON.

        Panel expects: {id, description, passed, error?, stackTrace?, duration?}
        """
        result = {
            "id": self.id,
            "description": self.description,
            "passed": self.passed,
        }

        if self.error is not None:
            result["error"] = self.error

        if self.stack_trace is not None:
            result["stackTrace"] = self.stack_trace

        if self.duration is not None:
            result["duration"] = self.duration

        return result


@dataclass
class TestResult(BaseDomainModel):
    """
    Result of a single test execution.

    Attributes:
        id: Unique identifier for this test
        name: Human-readable test name
        status: Test status ('passed' | 'failed' | 'skipped')
        duration: Time taken to execute this test (e.g., "1.2s")
        assertions: List of assertions within this test
    """

    id: str
    name: str
    status: str  # 'passed' | 'failed' | 'skipped'
    duration: str
    assertions: List[TestAssertion] = field(default_factory=list)

    def to_json(self) -> Dict[str, Any]:
        """
        Serialize to Panel-compatible JSON.

        Panel expects: {id, name, status, duration, assertions}
        """
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "duration": self.duration,
            "assertions": [a.to_json() for a in self.assertions]
        }


@dataclass
class SecurityTestDetails(BaseDomainModel):
    """
    Detailed results for security testing.

    Security frame executes multiple types of security tests.
    Panel displays these grouped by test type.

    Attributes:
        sql_injection_tests: SQL injection vulnerability tests
        xss_tests: Cross-site scripting vulnerability tests
        secrets_scan: Hardcoded secrets detection tests
        auth_tests: Authentication/authorization tests
    """

    sql_injection_tests: List[TestResult] = field(default_factory=list)
    xss_tests: List[TestResult] = field(default_factory=list)
    secrets_scan: List[TestResult] = field(default_factory=list)
    auth_tests: List[TestResult] = field(default_factory=list)

    def to_json(self) -> Dict[str, Any]:
        """
        Serialize to Panel-compatible JSON.

        Panel expects: {sqlInjectionTests, xssTests, secretsScan, authTests}
        """
        return {
            "sqlInjectionTests": [t.to_json() for t in self.sql_injection_tests],
            "xssTests": [t.to_json() for t in self.xss_tests],
            "secretsScan": [t.to_json() for t in self.secrets_scan],
            "authTests": [t.to_json() for t in self.auth_tests]
        }


@dataclass
class ChaosTestDetails(BaseDomainModel):
    """
    Detailed results for chaos engineering tests.

    Chaos frame tests system resilience under failure conditions.

    Attributes:
        network_failures: Network failure scenario tests
        resource_exhaustion: Resource exhaustion scenario tests
        error_recovery: Error recovery mechanism tests
    """

    network_failures: List[TestResult] = field(default_factory=list)
    resource_exhaustion: List[TestResult] = field(default_factory=list)
    error_recovery: List[TestResult] = field(default_factory=list)

    def to_json(self) -> Dict[str, Any]:
        """
        Serialize to Panel-compatible JSON.

        Panel expects: {networkFailures, resourceExhaustion, errorRecovery}
        """
        return {
            "networkFailures": [t.to_json() for t in self.network_failures],
            "resourceExhaustion": [t.to_json() for t in self.resource_exhaustion],
            "errorRecovery": [t.to_json() for t in self.error_recovery]
        }


@dataclass
class FuzzTestDetails(BaseDomainModel):
    """
    Detailed results for fuzz testing.

    Fuzz frame tests with randomized/malformed inputs.

    Attributes:
        input_validation: Input validation tests
        edge_cases: Edge case tests
        boundary_tests: Boundary value tests
    """

    input_validation: List[TestResult] = field(default_factory=list)
    edge_cases: List[TestResult] = field(default_factory=list)
    boundary_tests: List[TestResult] = field(default_factory=list)

    def to_json(self) -> Dict[str, Any]:
        """
        Serialize to Panel-compatible JSON.

        Panel expects: {inputValidation, edgeCases, boundaryTests}
        """
        return {
            "inputValidation": [t.to_json() for t in self.input_validation],
            "edgeCases": [t.to_json() for t in self.edge_cases],
            "boundaryTests": [t.to_json() for t in self.boundary_tests]
        }


@dataclass
class PropertyTestDetails(BaseDomainModel):
    """
    Detailed results for property-based testing.

    Property frame tests invariants and system properties.

    Attributes:
        invariants: System invariant tests
        idempotency: Idempotency property tests
        consistency: Consistency property tests
    """

    invariants: List[TestResult] = field(default_factory=list)
    idempotency: List[TestResult] = field(default_factory=list)
    consistency: List[TestResult] = field(default_factory=list)

    def to_json(self) -> Dict[str, Any]:
        """
        Serialize to Panel-compatible JSON.

        Panel expects: {invariants, idempotency, consistency}
        """
        return {
            "invariants": [t.to_json() for t in self.invariants],
            "idempotency": [t.to_json() for t in self.idempotency],
            "consistency": [t.to_json() for t in self.consistency]
        }


@dataclass
class StressTestMetrics(BaseDomainModel):
    """
    Performance metrics from stress testing.

    Attributes:
        requests_per_second: Request throughput
        latency_p50: 50th percentile latency (ms)
        latency_p95: 95th percentile latency (ms)
        latency_p99: 99th percentile latency (ms)
        max_concurrent_users: Maximum concurrent users sustained
        error_rate: Error rate (percentage)
    """

    requests_per_second: float
    latency_p50: float
    latency_p95: float
    latency_p99: float
    max_concurrent_users: int
    error_rate: float

    def to_json(self) -> Dict[str, Any]:
        """
        Serialize to Panel-compatible JSON.

        Panel expects: {requestsPerSecond, latencyP50, latencyP95, latencyP99,
                       maxConcurrentUsers, errorRate}
        """
        return {
            "requestsPerSecond": self.requests_per_second,
            "latencyP50": self.latency_p50,
            "latencyP95": self.latency_p95,
            "latencyP99": self.latency_p99,
            "maxConcurrentUsers": self.max_concurrent_users,
            "errorRate": self.error_rate
        }


@dataclass
class StressTestDetails(BaseDomainModel):
    """
    Detailed results for stress/load testing.

    Stress frame tests system behavior under high load.

    Attributes:
        load_tests: Load test results
        metrics: Performance metrics collected during testing
    """

    load_tests: List[TestResult] = field(default_factory=list)
    metrics: Optional[StressTestMetrics] = None

    def to_json(self) -> Dict[str, Any]:
        """
        Serialize to Panel-compatible JSON.

        Panel expects: {loadTests, metrics}
        """
        result = {
            "loadTests": [t.to_json() for t in self.load_tests]
        }

        if self.metrics is not None:
            result["metrics"] = self.metrics.to_json()

        return result


@dataclass
class ValidationTestDetails(BaseDomainModel):
    """
    Complete test details for all validation frames.

    Aggregates detailed test results from all validation frames.
    Panel displays this in the "Test Results" tab.

    Attributes:
        security: Security test details
        chaos: Chaos engineering test details
        fuzz: Fuzz testing details
        property: Property-based testing details
        stress: Stress testing details
    """

    security: Optional[SecurityTestDetails] = None
    chaos: Optional[ChaosTestDetails] = None
    fuzz: Optional[FuzzTestDetails] = None
    property: Optional[PropertyTestDetails] = None
    stress: Optional[StressTestDetails] = None

    def to_json(self) -> Dict[str, Any]:
        """
        Serialize to Panel-compatible JSON.

        Panel expects: {security?, chaos?, fuzz?, property?, stress?}
        Only includes non-None test details.
        """
        result: Dict[str, Any] = {}

        if self.security is not None:
            result["security"] = self.security.to_json()

        if self.chaos is not None:
            result["chaos"] = self.chaos.to_json()

        if self.fuzz is not None:
            result["fuzz"] = self.fuzz.to_json()

        if self.property is not None:
            result["property"] = self.property.to_json()

        if self.stress is not None:
            result["stress"] = self.stress.to_json()

        return result
