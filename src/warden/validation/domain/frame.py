"""
Validation Frame base class - Frame System Foundation.

All validation frames (built-in and external) must inherit from ValidationFrame.

Panel Source: /warden-panel-development/src/lib/types/frame.ts
Frame Docs: /docs/FRAME_SYSTEM.md

IMPORTANT: Optional capabilities have been extracted into mixins.
Use these mixins for optional functionality:
- BatchExecutable: For custom batch execution logic
- ProjectContextAware: For project-level context access
- Cleanable: For resource cleanup after execution

See: warden.validation.domain.mixins
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List

if TYPE_CHECKING:
    from warden.pipeline.domain.pipeline_context import PipelineContext

from warden.rules.domain.models import CustomRule, CustomRuleViolation
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)
from warden.validation.domain.enums import (
    FrameApplicability,
    FrameCategory,
    FramePriority,
    FrameScope,
)


@dataclass
class Remediation:
    """
    Suggested fix for a finding.
    """

    description: str
    code: str  # The replacement code
    unified_diff: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {"description": self.description, "code": self.code, "unified_diff": self.unified_diff}


@dataclass
class MachineContext:
    """
    Structured machine-readable context for automated consumption.

    Provides structured vulnerability metadata for Fortification phase
    and SARIF report enrichment. Replaces text-parsing of finding descriptions.
    """

    vulnerability_class: str  # "sql-injection", "xss-reflected", "cmd-injection"
    source: str | None = None  # "request.args['id']"
    sink: str | None = None  # "cursor.execute()"
    sink_type: str | None = None  # "SQL-value", "CMD-argument", "HTML-content"
    data_flow_path: list[str] = field(default_factory=list)
    sanitizers_applied: list[str] = field(default_factory=list)
    suggested_fix_type: str | None = None  # "parameterized_query", "input_validation"
    related_files: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        result: dict[str, Any] = {"vulnerability_class": self.vulnerability_class}
        if self.source is not None:
            result["source"] = self.source
        if self.sink is not None:
            result["sink"] = self.sink
        if self.sink_type is not None:
            result["sink_type"] = self.sink_type
        if self.data_flow_path:
            result["data_flow_path"] = self.data_flow_path
        if self.sanitizers_applied:
            result["sanitizers_applied"] = self.sanitizers_applied
        if self.suggested_fix_type is not None:
            result["suggested_fix_type"] = self.suggested_fix_type
        if self.related_files:
            result["related_files"] = self.related_files
        return result


@dataclass
class ExploitEvidence:
    """
    Witness payload and exploit evidence for a finding.

    Contains proof-of-concept data showing HOW a vulnerability can be exploited.
    WARNING: Witness payloads are for advisory purposes only -- never execute them.
    """

    witness_payload: str  # "' OR 1=1 --"
    attack_vector: str  # "URL parameter 'id'"
    data_flow_path: list[str] = field(default_factory=list)
    sink_type: str | None = None  # "SQL-value"
    why_exploitable: str = ""
    confidence: float = 0.0

    def to_json(self) -> dict[str, Any]:
        import html as html_module

        return {
            "witness_payload": html_module.escape(self.witness_payload),
            "attack_vector": html_module.escape(self.attack_vector),
            "data_flow_path": self.data_flow_path,
            "sink_type": self.sink_type,
            "why_exploitable": self.why_exploitable,
            "confidence": self.confidence,
        }


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
    is_blocker: bool = False  # Individual blocker status
    remediation: Remediation | None = None  # Suggested fix
    machine_context: MachineContext | None = None  # Structured vulnerability context
    exploit_evidence: ExploitEvidence | None = None  # Witness payload evidence

    def to_json(self) -> dict[str, Any]:
        """Serialize to Panel JSON."""
        result = {
            "id": self.id,
            "severity": self.severity,
            "message": self.message,
            "location": self.location,
            "detail": self.detail,
            "code": self.code,
            "line": self.line,
            "column": self.column,
            "isBlocker": self.is_blocker,
            "remediation": self.remediation.to_json() if self.remediation else None,
        }
        if self.machine_context:
            result["machineContext"] = self.machine_context.to_json()
        if self.exploit_evidence:
            result["exploitEvidence"] = self.exploit_evidence.to_json()
        return result

    def to_dict(self) -> dict[str, Any]:
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
    findings: list[Finding]
    metadata: dict[str, Any] | None = None

    # Pre/Post Rules Support
    pre_rules: list[CustomRule] | None = None
    post_rules: list[CustomRule] | None = None
    pre_rule_violations: list[CustomRuleViolation] | None = None
    post_rule_violations: list[CustomRuleViolation] | None = None

    @property
    def passed(self) -> bool:
        """Check if frame passed (no issues)."""
        return self.status == "passed"

    def to_json(self) -> dict[str, Any]:
        """Serialize to Panel JSON (camelCase)."""
        result = {
            "frameId": self.frame_id,
            "frameName": self.frame_name,
            "status": self.status,
            "duration": self.duration,
            "issuesFound": self.issues_found,
            "isBlocker": self.is_blocker,
            "findings": [f.to_json() for f in self.findings],
            "metadata": self.metadata or {},
            "is_degraded": self.metadata.get("is_degraded", False) if self.metadata else False,
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

            async def execute_async(self, code_file: CodeFile) -> FrameResult:
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
    applicability: list[FrameApplicability] = [FrameApplicability.ALL]

    # Frame compatibility (for community frames)
    min_warden_version: str | None = None
    max_warden_version: str | None = None

    # Frame dependencies (for conditional execution)
    # Frame will be skipped if dependencies are not met
    requires_frames: list[str] = []  # Frame IDs that must run before this frame
    requires_config: list[str] = []  # Config paths that must be set (e.g., "spec.platforms")
    requires_context: list[str] = []  # Context attributes that must exist (e.g., "project_context")

    # Frame state (set at runtime)
    enabled: bool = True  # Can be disabled via config or runtime

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """
        Initialize frame with optional configuration.

        Args:
            config: Frame-specific configuration from .warden/config.yaml
                    or programmatic setup
        """
        # Ensure mutable class-level defaults are copied to instance level
        # to prevent shared-state mutation across instances.
        self.applicability = list(self.__class__.applicability)
        self.requires_frames = list(self.__class__.requires_frames)
        self.requires_config = list(self.__class__.requires_config)
        self.requires_context = list(self.__class__.requires_context)

        self.config = config or {}
        self._validate_metadata()

        # Injectable services (only for frames that need them)
        self.semantic_search_service: Any | None = None

    def _validate_metadata(self) -> None:
        """Validate required metadata is present."""
        if self.name == "Unnamed Frame":
            raise ValueError(f"{self.__class__.__name__} must define 'name' attribute")

        if self.description == "No description provided":
            raise ValueError(f"{self.__class__.__name__} must define 'description' attribute")

    @abstractmethod
    async def execute_async(self, code_file: CodeFile, context: "PipelineContext | None" = None) -> FrameResult:  # type: ignore[name-defined]
        """
        Execute validation frame on code file.

        Args:
            code_file: Code file to validate (contains path, content, language, etc.)
            context: Optional pipeline context for cross-frame awareness (Tier 2: Context-Awareness).
                     Frames can opt-in to use context for:
                     - Accessing prior findings from other frames
                     - Reading project intelligence (entry points, auth patterns, etc.)
                     - Checking quality metrics and hotspots
                     - Viewing suppression rules and false positives
                     Default: None (backwards compatible)

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
            - Context parameter is optional - check if not None before using
        """
        pass

    @property
    def frame_id(self) -> str:
        """
        Unique frame identifier.

        Default: snake_case class name
        Override for custom ID (e.g., external frames)
        """
        return self.__class__.__name__.lower().replace("frame", "").replace("_", "-")

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
    hash: str | None = None
    metadata: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        """Calculate size and line count if not provided."""
        if self.metadata is None:
            self.metadata = {}
        if self.size_bytes == 0 and self.content:
            self.size_bytes = len(self.content.encode("utf-8"))
        if self.line_count == 0 and self.content:
            self.line_count = self.content.count("\n") + 1
