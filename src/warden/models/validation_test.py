"""
Validation test details models for Panel compatibility.

These models represent test execution results for each validation frame:
- TestAssertion: Individual assertion result
- TestResult: Test with multiple assertions
- ValidationTestDetails: Results for all 6 frames (security, chaos, fuzz, property, stress, architectural)

Panel JSON format: camelCase
Python internal format: snake_case
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Literal

from warden.shared.domain.base_model import BaseDomainModel


# Type aliases for Panel compatibility
TestStatus = Literal['passed', 'failed', 'skipped']


@dataclass
class TestAssertion(BaseDomainModel):
    """
    Individual test assertion result.

    Panel TypeScript equivalent:
    ```typescript
    export interface TestAssertion {
      id: string
      description: string
      passed: bool
      error?: string
      stackTrace?: string
      duration?: string
    }
    ```

    Represents a single assertion within a test.
    """

    id: str
    description: str
    passed: bool
    error: Optional[str] = None
    stack_trace: Optional[str] = None
    duration: Optional[str] = None  # e.g., "0.002s"

    def to_json(self) -> Dict[str, Any]:
        """Convert to Panel-compatible JSON (camelCase)."""
        data = super().to_json()
        # Ensure stackTrace is camelCase
        if self.stack_trace is not None:
            data['stackTrace'] = self.stack_trace
            # Remove snake_case version if present
            data.pop('stack_trace', None)
        return data


@dataclass
class TestResult(BaseDomainModel):
    """
    Test result with multiple assertions.

    Panel TypeScript equivalent:
    ```typescript
    export interface TestResult {
      id: string
      name: string
      status: 'passed' | 'failed' | 'skipped'
      duration: string
      assertions: TestAssertion[]
    }
    ```

    Represents a test with one or more assertions.
    """

    id: str
    name: str
    status: TestStatus
    duration: str  # e.g., "0.15s"
    assertions: List[TestAssertion] = field(default_factory=list)

    def to_json(self) -> Dict[str, Any]:
        """Convert to Panel-compatible JSON (camelCase)."""
        data = super().to_json()
        # Convert assertions
        data['assertions'] = [assertion.to_json() for assertion in self.assertions]
        return data

    @property
    def passed(self) -> bool:
        """Check if all assertions passed."""
        return self.status == 'passed' and all(a.passed for a in self.assertions)

    @property
    def failed_assertions(self) -> List[TestAssertion]:
        """Get failed assertions."""
        return [a for a in self.assertions if not a.passed]


@dataclass
class SecurityTestDetails(BaseDomainModel):
    """
    Security frame test results.

    Checks for:
    - SQL injection patterns
    - XSS vulnerabilities
    - Hardcoded secrets
    - Command injection
    - Path traversal
    """

    tests: List[TestResult] = field(default_factory=list)
    total_tests: int = 0
    passed_tests: int = 0
    failed_tests: int = 0
    skipped_tests: int = 0
    duration: str = "0s"

    def to_json(self) -> Dict[str, Any]:
        """Convert to Panel-compatible JSON."""
        return {
            'tests': [test.to_json() for test in self.tests],
            'totalTests': self.total_tests,
            'passedTests': self.passed_tests,
            'failedTests': self.failed_tests,
            'skippedTests': self.skipped_tests,
            'duration': self.duration
        }


@dataclass
class ChaosTestDetails(BaseDomainModel):
    """
    Chaos engineering test results.

    Checks for:
    - Network failure handling
    - Timeout resilience
    - Error recovery
    - Circuit breaker patterns
    - Retry mechanisms
    """

    tests: List[TestResult] = field(default_factory=list)
    total_tests: int = 0
    passed_tests: int = 0
    failed_tests: int = 0
    skipped_tests: int = 0
    duration: str = "0s"

    def to_json(self) -> Dict[str, Any]:
        """Convert to Panel-compatible JSON."""
        return {
            'tests': [test.to_json() for test in self.tests],
            'totalTests': self.total_tests,
            'passedTests': self.passed_tests,
            'failedTests': self.failed_tests,
            'skippedTests': self.skipped_tests,
            'duration': self.duration
        }


@dataclass
class FuzzTestDetails(BaseDomainModel):
    """
    Fuzz testing results.

    Checks for:
    - Malformed input handling
    - Edge cases (null, empty, max length)
    - Unicode edge cases
    - Special characters
    - Type safety
    """

    tests: List[TestResult] = field(default_factory=list)
    total_tests: int = 0
    passed_tests: int = 0
    failed_tests: int = 0
    skipped_tests: int = 0
    duration: str = "0s"

    def to_json(self) -> Dict[str, Any]:
        """Convert to Panel-compatible JSON."""
        return {
            'tests': [test.to_json() for test in self.tests],
            'totalTests': self.total_tests,
            'passedTests': self.passed_tests,
            'failedTests': self.failed_tests,
            'skippedTests': self.skipped_tests,
            'duration': self.duration
        }


@dataclass
class PropertyTestDetails(BaseDomainModel):
    """
    Property-based testing results.

    Checks for:
    - Idempotency: f(f(x)) == f(x)
    - Commutativity: f(a,b) == f(b,a)
    - Associativity
    - Invariant preservation
    - Round-trip: decode(encode(x)) == x
    """

    tests: List[TestResult] = field(default_factory=list)
    total_tests: int = 0
    passed_tests: int = 0
    failed_tests: int = 0
    skipped_tests: int = 0
    duration: str = "0s"

    def to_json(self) -> Dict[str, Any]:
        """Convert to Panel-compatible JSON."""
        return {
            'tests': [test.to_json() for test in self.tests],
            'totalTests': self.total_tests,
            'passedTests': self.passed_tests,
            'failedTests': self.failed_tests,
            'skippedTests': self.skipped_tests,
            'duration': self.duration
        }


@dataclass
class StressTestDetails(BaseDomainModel):
    """
    Stress testing results.

    Checks for:
    - Memory leaks
    - Performance under load
    - Concurrent access
    - Resource cleanup
    - GC pressure
    """

    tests: List[TestResult] = field(default_factory=list)
    total_tests: int = 0
    passed_tests: int = 0
    failed_tests: int = 0
    skipped_tests: int = 0
    duration: str = "0s"
    metrics: Dict[str, Any] = field(default_factory=dict)  # latency, memory, etc.

    def to_json(self) -> Dict[str, Any]:
        """Convert to Panel-compatible JSON."""
        return {
            'tests': [test.to_json() for test in self.tests],
            'totalTests': self.total_tests,
            'passedTests': self.passed_tests,
            'failedTests': self.failed_tests,
            'skippedTests': self.skipped_tests,
            'duration': self.duration,
            'metrics': self.metrics
        }


@dataclass
class ArchitecturalTestDetails(BaseDomainModel):
    """
    Architectural validation results.

    Checks for:
    - Design pattern adherence
    - Dependency rules
    - Layer boundaries
    - SOLID principles
    - Code organization
    """

    tests: List[TestResult] = field(default_factory=list)
    total_tests: int = 0
    passed_tests: int = 0
    failed_tests: int = 0
    skipped_tests: int = 0
    duration: str = "0s"

    def to_json(self) -> Dict[str, Any]:
        """Convert to Panel-compatible JSON."""
        return {
            'tests': [test.to_json() for test in self.tests],
            'totalTests': self.total_tests,
            'passedTests': self.passed_tests,
            'failedTests': self.failed_tests,
            'skippedTests': self.skipped_tests,
            'duration': self.duration
        }


@dataclass
class ValidationTestDetails(BaseDomainModel):
    """
    Complete validation test results for all 6 frames.

    Panel TypeScript equivalent:
    ```typescript
    export interface ValidationTestDetails {
      security: SecurityTestDetails
      chaos: ChaosTestDetails
      fuzz: FuzzTestDetails
      property: PropertyTestDetails
      stress: StressTestDetails
      architectural?: ArchitecturalTestDetails
    }
    ```

    Used in PipelineRun.testResults field.
    """

    security: SecurityTestDetails = field(default_factory=SecurityTestDetails)
    chaos: ChaosTestDetails = field(default_factory=ChaosTestDetails)
    fuzz: FuzzTestDetails = field(default_factory=FuzzTestDetails)
    property: PropertyTestDetails = field(default_factory=PropertyTestDetails)
    stress: StressTestDetails = field(default_factory=StressTestDetails)
    architectural: Optional[ArchitecturalTestDetails] = None

    def to_json(self) -> Dict[str, Any]:
        """Convert to Panel-compatible JSON."""
        data: Dict[str, Any] = {
            'security': self.security.to_json(),
            'chaos': self.chaos.to_json(),
            'fuzz': self.fuzz.to_json(),
            'property': self.property.to_json(),
            'stress': self.stress.to_json(),
        }

        if self.architectural:
            data['architectural'] = self.architectural.to_json()

        return data

    @property
    def total_tests(self) -> int:
        """Total number of tests across all frames."""
        total = (
            self.security.total_tests +
            self.chaos.total_tests +
            self.fuzz.total_tests +
            self.property.total_tests +
            self.stress.total_tests
        )
        if self.architectural:
            total += self.architectural.total_tests
        return total

    @property
    def total_passed(self) -> int:
        """Total passed tests across all frames."""
        total = (
            self.security.passed_tests +
            self.chaos.passed_tests +
            self.fuzz.passed_tests +
            self.property.passed_tests +
            self.stress.passed_tests
        )
        if self.architectural:
            total += self.architectural.passed_tests
        return total

    @property
    def total_failed(self) -> int:
        """Total failed tests across all frames."""
        total = (
            self.security.failed_tests +
            self.chaos.failed_tests +
            self.fuzz.failed_tests +
            self.property.failed_tests +
            self.stress.failed_tests
        )
        if self.architectural:
            total += self.architectural.failed_tests
        return total

    @property
    def all_passed(self) -> bool:
        """Check if all tests passed."""
        return self.total_failed == 0 and self.total_tests > 0
