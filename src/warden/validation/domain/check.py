"""
Validation Check base class - Granular validation rules.

A Check is a specific validation rule within a Frame.
Both Frames and Checks are pluggable and modular.

Hierarchy:
    Frame (Strategy)
      └── Check (Specific Rule)
          ├── Built-in checks (shipped with frame)
          ├── Official checks (Warden team)
          └── Community checks (pluggable!)

Example:
    SecurityFrame
      ├── SQLInjectionCheck (built-in)
      ├── XSSCheck (built-in)
      ├── SecretsCheck (built-in)
      └── MyCompanyAPIKeyCheck (community - pluggable!)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, Any, List
from enum import Enum


class CheckSeverity(str, Enum):
    """
    Check severity level.

    Determines how critical a check failure is.
    """

    CRITICAL = "critical"  # Block PR, must fix
    HIGH = "high"  # Strongly recommend fix
    MEDIUM = "medium"  # Recommend fix
    LOW = "low"  # Nice to fix
    INFO = "info"  # Informational only


@dataclass
class CheckFinding:
    """
    A single finding from a check.

    More granular than Frame-level Finding.
    """

    check_id: str
    check_name: str
    severity: CheckSeverity
    message: str
    location: str  # file:line or file:line:column
    code_snippet: str | None = None
    suggestion: str | None = None  # How to fix
    documentation_url: str | None = None  # Link to docs
    is_blocker: bool = False  # ⚠️ NEW: Individual blocker status

    def to_json(self) -> Dict[str, Any]:
        """Serialize to Panel JSON."""
        return {
            "checkId": self.check_id,
            "checkName": self.check_name,
            "severity": self.severity.value,
            "message": self.message,
            "location": self.location,
            "codeSnippet": self.code_snippet,
            "suggestion": self.suggestion,
            "documentationUrl": self.documentation_url,
            "isBlocker": self.is_blocker,
        }


@dataclass
class CheckResult:
    """
    Result from a single check execution.

    A Frame aggregates multiple CheckResults.
    """

    check_id: str
    check_name: str
    passed: bool
    findings: List[CheckFinding]
    duration: float = 0.0  # in seconds
    metadata: Dict[str, Any] | None = None

    @property
    def critical_count(self) -> int:
        """Count of critical findings."""
        return sum(1 for f in self.findings if f.severity == CheckSeverity.CRITICAL)

    @property
    def high_count(self) -> int:
        """Count of high severity findings."""
        return sum(1 for f in self.findings if f.severity == CheckSeverity.HIGH)

    def to_json(self) -> Dict[str, Any]:
        """Serialize to Panel JSON."""
        return {
            "checkId": self.check_id,
            "checkName": self.check_name,
            "passed": self.passed,
            "findings": [f.to_json() for f in self.findings],
            "duration": self.duration,
            "metadata": self.metadata,
        }


class ValidationCheck(ABC):
    """
    Base class for validation checks (pluggable rules).

    A Check is a specific validation rule within a Frame.
    Community can create custom checks and plug them into existing frames.

    Example (Built-in Check):
        class SQLInjectionCheck(ValidationCheck):
            id = "sql-injection"
            name = "SQL Injection Detection"
            severity = CheckSeverity.CRITICAL

            async def execute(self, code_file: CodeFile) -> CheckResult:
                # Check for SQL injection patterns
                pass

    Example (Community Check):
        class MyCompanyAPIKeyCheck(ValidationCheck):
            id = "mycompany-api-key"
            name = "MyCompany API Key Detection"
            severity = CheckSeverity.CRITICAL

            async def execute(self, code_file: CodeFile) -> CheckResult:
                # Check for company-specific API key patterns
                pass

    Check Discovery:
        - Entry points: [tool.poetry.plugins."warden.checks.security"]
        - Directory-based: ~/.warden/checks/security/
        - Registered programmatically: frame.register_check(MyCheck())
    """

    # Required metadata
    id: str = "unnamed-check"
    name: str = "Unnamed Check"
    description: str = "No description provided"
    severity: CheckSeverity = CheckSeverity.MEDIUM

    # Optional metadata
    version: str = "0.0.0"
    author: str = "Unknown"
    enabled_by_default: bool = True

    # Configuration
    config: Dict[str, Any]

    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        """
        Initialize check with optional configuration.

        Args:
            config: Check-specific configuration
        """
        self.config = config or {}
        self._validate_metadata()

    def _validate_metadata(self) -> None:
        """Validate required metadata is present."""
        if self.id == "unnamed-check":
            raise ValueError(f"{self.__class__.__name__} must define 'id' attribute")

        if self.name == "Unnamed Check":
            raise ValueError(f"{self.__class__.__name__} must define 'name' attribute")

    @abstractmethod
    async def execute(self, code_file: "CodeFile") -> CheckResult:  # type: ignore[name-defined]
        """
        Execute validation check on code file.

        Args:
            code_file: Code file to validate

        Returns:
            CheckResult with findings

        Implementation Guidelines:
            - Execute quickly (< 5 seconds for single check)
            - Return CheckResult even on partial failure
            - Use CheckFinding for each issue found
            - Provide actionable suggestions
        """
        pass

    def is_enabled(self, frame_config: Dict[str, Any] | None = None) -> bool:
        """
        Check if this check is enabled.

        Args:
            frame_config: Frame-level configuration

        Returns:
            True if check should run
        """
        if frame_config is None:
            return self.enabled_by_default

        # Check if explicitly enabled/disabled in config
        check_config = frame_config.get("checks", {})
        
        # Handle list format (list of enabled check IDs)
        if isinstance(check_config, list):
            return self.id in check_config

        # Handle dict format (map of check ID to config)
        if self.id in check_config:
            return check_config[self.id].get("enabled", self.enabled_by_default)

        return self.enabled_by_default

    def __repr__(self) -> str:
        """String representation for logging."""
        return (
            f"{self.__class__.__name__}("
            f"id={self.id}, "
            f"name={self.name}, "
            f"severity={self.severity.value})"
        )


class CheckRegistry:
    """
    Registry for validation checks.

    Manages check discovery, registration, and retrieval.
    Each frame has its own CheckRegistry.
    """

    def __init__(self) -> None:
        """Initialize check registry."""
        self._checks: Dict[str, ValidationCheck] = {}

    def register(self, check: ValidationCheck) -> None:
        """
        Register a check.

        Args:
            check: ValidationCheck instance

        Raises:
            ValueError: If check with same ID already registered
        """
        if check.id in self._checks:
            raise ValueError(f"Check {check.id} already registered")

        self._checks[check.id] = check

    def unregister(self, check_id: str) -> None:
        """
        Unregister a check.

        Args:
            check_id: Check ID to unregister
        """
        if check_id in self._checks:
            del self._checks[check_id]

    def get(self, check_id: str) -> ValidationCheck | None:
        """
        Get check by ID.

        Args:
            check_id: Check ID

        Returns:
            ValidationCheck instance or None
        """
        return self._checks.get(check_id)

    def get_all(self) -> List[ValidationCheck]:
        """
        Get all registered checks.

        Returns:
            List of ValidationCheck instances
        """
        return list(self._checks.values())

    def get_enabled(self, frame_config: Dict[str, Any] | None = None) -> List[ValidationCheck]:
        """
        Get all enabled checks.

        Args:
            frame_config: Frame-level configuration

        Returns:
            List of enabled ValidationCheck instances
        """
        return [check for check in self._checks.values() if check.is_enabled(frame_config)]

    def __len__(self) -> int:
        """Number of registered checks."""
        return len(self._checks)

    def __contains__(self, check_id: str) -> bool:
        """Check if check is registered."""
        return check_id in self._checks


# ============================================================================
# CodeFile (temporary import - will be moved to shared/domain)
# ============================================================================

from warden.validation.domain.frame import CodeFile  # noqa: E402
