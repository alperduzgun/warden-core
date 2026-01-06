"""
Validation Frame base class - Frame System Foundation.

All validation frames (built-in and external) must inherit from ValidationFrame.

Panel Source: /warden-panel-development/src/lib/types/frame.ts
Frame Docs: /docs/FRAME_SYSTEM.md
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, Any, List

from warden.rules.domain.models import CustomRule, CustomRuleViolation
from warden.validation.domain.enums import (
    FramePriority,
    FrameScope,
    FrameCategory,
    FrameApplicability,
)


@dataclass
class Finding:
    """
    A single validation finding (issue/warning).

    Panel TypeScript:
        export interface Finding {
            id: string;
            severity: 'critical' | 'high' | 'medium' | 'low';
            message: string;
            location: string;
            detail?: string;
            code?: string;
        }
    """

    id: str
    severity: str  # 'critical' | 'high' | 'medium' | 'low'
    message: str
    location: str  # e.g., "user_service.py:45"
    detail: str | None = None
    code: str | None = None  # Code snippet
    line: int = 0  # Line number (1-based)
    column: int = 0  # Column number (1-based)
    is_blocker: bool = False  # ⚠️ NEW: Individual blocker status

    def to_json(self) -> Dict[str, Any]:
        """Serialize to Panel JSON."""
        return {
            "id": self.id,
            "severity": self.severity,
            "message": self.message,
            "location": self.location,
            "detail": self.detail,
            "code": self.code,
            "line": self.line,
            "column": self.column,
            "isBlocker": self.is_blocker,  # Exposed to UI/Report
        }

    def to_dict(self) -> Dict[str, Any]:
        """Alias for to_json for compatibility."""
        return self.to_json()


@dataclass
class FrameResult:
    """
    Result from frame execution with pre/post rules support.

    Panel TypeScript:
        export interface FrameExecutionResult {
            frameId: string;
            frameName: string;
            status: 'passed' | 'failed' | 'warning';
            duration: number;
            issuesFound: number;
            isBlocker: boolean;
            preRules?: CustomRule[];
            postRules?: CustomRule[];
            preRuleViolations?: CustomRuleViolation[];
            postRuleViolations?: CustomRuleViolation[];
        }
    """

    frame_id: str
    frame_name: str
    status: str  # 'passed' | 'failed' | 'warning'
    duration: float  # in seconds
    issues_found: int
    is_blocker: bool
    findings: List[Finding]
    metadata: Dict[str, Any] | None = None

    # ⭐ NEW: Pre/Post Rules Support
    pre_rules: List[CustomRule] | None = None
    post_rules: List[CustomRule] | None = None
    pre_rule_violations: List[CustomRuleViolation] | None = None
    post_rule_violations: List[CustomRuleViolation] | None = None

    @property
    def passed(self) -> bool:
        """Check if frame passed (no issues)."""
        return self.status == "passed"

    def to_json(self) -> Dict[str, Any]:
        """Serialize to Panel JSON (camelCase)."""
        result = {
            "frameId": self.frame_id,
            "frameName": self.frame_name,
            "status": self.status,
            "duration": self.duration,
            "issuesFound": self.issues_found,
            "isBlocker": self.is_blocker,
            "findings": [f.to_json() for f in self.findings],
            "metadata": self.metadata,
        }

        # Add pre/post rules if present
        if self.pre_rules:
            result["preRules"] = [r.to_json() for r in self.pre_rules]  # type: ignore
        if self.post_rules:
            result["postRules"] = [r.to_json() for r in self.post_rules]  # type: ignore
        if self.pre_rule_violations:
            result["preRuleViolations"] = [v.to_json() for v in self.pre_rule_violations]  # type: ignore
        if self.post_rule_violations:
            result["postRuleViolations"] = [v.to_json() for v in self.post_rule_violations]  # type: ignore

        return result


class ValidationFrame(ABC):
    """
    Base class for all validation frames (built-in and external).

    Matches C# Warden.Core.Validation.IValidationFrame interface.

    Developers extend this class to create custom frames.

    Example:
        class MyCustomFrame(ValidationFrame):
            name = "My Custom Security Check"
            description = "Company-specific security validation"
            category = FrameCategory.GLOBAL
            priority = FramePriority.HIGH
            scope = FrameScope.FILE_LEVEL
            is_blocker = True

            async def execute(self, code_file: CodeFile) -> FrameResult:
                # Validation logic here
                pass

    Frame Discovery:
        - Built-in frames: Registered in FrameRegistry
        - External frames: ~/.warden/frames/
        - Environment variable: WARDEN_FRAME_PATHS

    See: /docs/FRAME_SYSTEM.md
    """

    # Required metadata (must be overridden by subclasses)
    name: str = "Unnamed Frame"
    description: str = "No description provided"
    category: FrameCategory = FrameCategory.GLOBAL
    priority: FramePriority = FramePriority.MEDIUM
    scope: FrameScope = FrameScope.FILE_LEVEL
    is_blocker: bool = False

    # Optional metadata
    version: str = "0.0.0"
    author: str = "Unknown"
    applicability: List[FrameApplicability] = [FrameApplicability.ALL]

    # Frame compatibility (for community frames)
    min_warden_version: str | None = None
    max_warden_version: str | None = None

    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        """
        Initialize frame with optional configuration.

        Args:
            config: Frame-specific configuration from .warden/config.yaml
                    or programmatic setup
        """
        self.config = config or {}
        self._validate_metadata()
        self.project_context: Any | None = None  # Generic to avoid circular imports
        self.semantic_search_service: Any | None = None  # Injectable semantic search service

    def set_project_context(self, context: Any) -> None:
        """
        Inject project context (architecture, framework info).
        
        Args:
            context: ProjectContext object
        """
        self.project_context = context

    def _validate_metadata(self) -> None:
        """Validate required metadata is present."""
        if self.name == "Unnamed Frame":
            raise ValueError(f"{self.__class__.__name__} must define 'name' attribute")

        if self.description == "No description provided":
            raise ValueError(f"{self.__class__.__name__} must define 'description' attribute")

    @abstractmethod
    async def execute(self, code_file: "CodeFile") -> FrameResult:  # type: ignore[name-defined]
        """
        Execute validation frame on code file.

        Args:
            code_file: Code file to validate (contains path, content, language, etc.)

        Returns:
            FrameResult with findings and metadata

        Raises:
            ValidationFrameError: If validation fails unexpectedly

        Implementation Guidelines:
            - Execute within 30 seconds (timeout enforced by FrameExecutor)
            - Return FrameResult even on partial failure (don't raise exceptions)
            - Use Finding objects to report issues
            - Set status='failed' if frame execution fails
            - Set status='warning' for non-critical findings
            - Set status='passed' if no issues found
        """
        pass

    async def execute_batch(self, code_files: List["CodeFile"]) -> List[FrameResult]:
        """
        Execute validation on multiple files in PARALLEL.

        Default implementation uses asyncio.gather with a semaphore to limit concurrency.
        """
        # Limit concurrency to 50 concurrent frame executions per batch
        concurrency = self.config.get("concurrency_limit", 50) if isinstance(self.config, dict) else 50
        semaphore = asyncio.Semaphore(concurrency)
        
        async def execute_safe(code_file: "CodeFile") -> Any:
            async with semaphore:
                try:
                    return await self.execute(code_file)
                except Exception as e:
                    # Log error but don't crash batch
                    return None

        # Launch all tasks
        tasks = [execute_safe(f) for f in code_files]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter out None results and exceptions
        valid_results = []
        for r in results:
            if isinstance(r, Exception):
                continue
            if r:
                valid_results.append(r)
                
        return valid_results

    @property
    def frame_id(self) -> str:
        """
        Unique frame identifier.

        Default: snake_case class name
        Override for custom ID (e.g., external frames)
        """
        return self.__class__.__name__.lower().replace("frame", "").replace("_", "-")

    def is_applicable(self, language: str, framework: str | None = None) -> bool:
        """
        Check if frame is applicable to given language/framework.

        Args:
            language: Programming language (python, javascript, etc.)
            framework: Optional framework (fastapi, react, etc.)

        Returns:
            True if frame should run for this code
        """
        # Global frames apply to everything
        if FrameApplicability.ALL in self.applicability:
            return True

        # Check language
        lang_match = any(
            app.value.lower() == language.lower() for app in self.applicability
        )

        # Check framework (if provided)
        if framework:
            framework_match = any(
                app.value.lower() == framework.lower() for app in self.applicability
            )
            return lang_match or framework_match

        return lang_match

    def __repr__(self) -> str:
        """String representation for logging."""
        return (
            f"{self.__class__.__name__}("
            f"id={self.frame_id}, "
            f"name={self.name}, "
            f"priority={self.priority.value}, "
            f"scope={self.scope.value}, "
            f"blocker={self.is_blocker})"
        )


class ValidationFrameError(Exception):
    """Raised when frame execution fails unexpectedly."""

    pass


# ============================================================================
# CodeFile Model (temporary - will move to shared/domain later)
# ============================================================================


@dataclass
class CodeFile:
    """
    Represents a code file to be validated.

    This is a simplified version. Full implementation will be in shared/domain.
    """

    path: str
    content: str
    language: str  # python, javascript, typescript, etc.
    framework: str | None = None  # fastapi, react, flutter, etc.
    size_bytes: int = 0
    line_count: int = 0

    def __post_init__(self) -> None:
        """Calculate size and line count if not provided."""
        if self.size_bytes == 0:
            self.size_bytes = len(self.content.encode("utf-8"))
        if self.line_count == 0:
            self.line_count = self.content.count("\n") + 1
