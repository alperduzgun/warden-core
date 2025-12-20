"""
Base validation frame interface.

All validation frames must inherit from BaseValidationFrame.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum


class FrameScope(Enum):
    """Validation scope."""

    FILE_LEVEL = "file"
    REPOSITORY_LEVEL = "repository"


@dataclass
class FrameResult:
    """
    Result from frame execution.

    Contains validation findings, test results, and execution metadata.
    """

    name: str
    passed: bool
    execution_time_ms: float
    priority: str  # critical, high, medium, low
    scope: str  # file, repository

    # Findings
    findings: List[str] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)
    scenarios_executed: List[str] = field(default_factory=list)

    # Error tracking
    error_message: Optional[str] = None
    is_blocker: bool = False

    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict:
        """Convert to Panel-compatible JSON (camelCase)."""
        return {
            'name': self.name,
            'passed': self.passed,
            'executionTimeMs': self.execution_time_ms,
            'priority': self.priority,
            'scope': self.scope,
            'findings': self.findings,
            'issues': self.issues,
            'scenariosExecuted': self.scenarios_executed,
            'errorMessage': self.error_message,
            'isBlocker': self.is_blocker,
            'metadata': self.metadata
        }


class BaseValidationFrame(ABC):
    """
    Abstract base class for all validation frames.

    All frames must implement:
    - Properties: name, description, priority, scope, is_blocker
    - Method: execute(file_path, file_content, language, characteristics)
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Frame name (e.g., 'Security Analysis')."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Frame description."""
        pass

    @property
    @abstractmethod
    def priority(self) -> str:
        """Execution priority: critical, high, medium, low."""
        pass

    @property
    @abstractmethod
    def scope(self) -> FrameScope:
        """Validation scope: file-level or repository-level."""
        pass

    @property
    @abstractmethod
    def is_blocker(self) -> bool:
        """Whether failure blocks entire pipeline."""
        pass

    @abstractmethod
    async def execute(
        self,
        file_path: str,
        file_content: str,
        language: str,
        characteristics: Dict[str, Any],
        correlation_id: str = "",
        timeout: int = 300,
    ) -> FrameResult:
        """
        Execute validation frame.

        Args:
            file_path: Path to code file
            file_content: File content
            language: Programming language
            characteristics: Code characteristics (hasAsync, hasUserInput, etc.)
            correlation_id: Correlation ID for tracking
            timeout: Max execution time in seconds

        Returns:
            FrameResult with validation findings
        """
        pass
