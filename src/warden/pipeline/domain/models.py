"""
Pipeline domain models.

Core entities for validation pipeline orchestration.
"""

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import Field

from warden.pipeline.domain.enums import AnalysisLevel, ExecutionStrategy, PipelineStatus
from warden.rules.domain.models import CustomRule, FrameRules
from warden.shared.domain.base_model import BaseDomainModel
from warden.validation.domain.frame import FrameResult


class FrameExecution(BaseDomainModel):
    """
    Individual frame execution record.

    Tracks execution of a single frame within a pipeline.
    """

    frame_id: str
    frame_name: str
    status: str  # "pending", "running", "completed", "failed", "skipped"
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration: float = 0.0
    result: FrameResult | None = None
    error: str | None = None

    def to_json(self) -> dict[str, Any]:
        """Convert to Panel-compatible JSON."""
        data = super().to_json()

        # Convert FrameResult if present
        if self.result:
            data["result"] = self.result.to_json()

        return data


class PipelineConfig(BaseDomainModel):
    """
    Pipeline configuration.

    Defines how frames should be executed.
    """

    strategy: ExecutionStrategy = (
        ExecutionStrategy.PARALLEL
    )  # PARALLEL by default: independent frames run concurrently (semaphore = parallel_limit).
    # asyncio cooperative scheduling means no race conditions on context.frame_results dict writes.
    fail_fast: bool = True
    timeout: int = 300  # Total pipeline timeout in seconds
    frame_timeout: int = 120  # Per-frame timeout in seconds
    parallel_limit: int = 4  # Max concurrent frames in parallel mode
    skip_non_blockers: bool = False  # Skip non-blocker frames if blocker fails
    use_gitignore: bool = True  # NEW: Respect .gitignore patterns (global)
    analysis_level: AnalysisLevel = AnalysisLevel.STANDARD  # NEW: Scannig depth level
    use_llm: bool = True  # NEW: Global LLM control flag
    ci_mode: bool = False  # CI mode: use pre-computed intelligence, skip LLM for P3 files
    force_scan: bool = False  # If True, bypass the memory cache and force a full re-analysis

    # Optional pre-processing phases
    enable_discovery: bool = True  # Run file discovery before validation
    enable_build_context: bool = True  # Load build context at pipeline start
    enable_pre_analysis: bool = True  # Run PRE-ANALYSIS phase for context detection (NEW!)
    enable_lsp_audit: bool = True  # Run LSP chain validation (Phase 0.8)

    # Main pipeline phases (6-phase system)
    enable_analysis: bool = True  # Run ANALYSIS phase for quality metrics
    enable_classification: bool = True  # ALWAYS ENABLED - Run CLASSIFICATION phase for intelligent frame selection
    enable_validation: bool = True  # Run VALIDATION phase (frames)
    enable_fortification: bool = False  # Run FORTIFICATION phase for security fixes
    enable_cleaning: bool = False  # Run CLEANING phase for code improvements

    # Optional post-processing phases
    enable_suppression: bool = True  # Apply suppression filtering after validation
    enable_issue_validation: bool = True  # Apply confidence-based false positive detection

    # Phase-specific configurations
    discovery_config: dict[str, Any] | None = None  # Discovery configuration options
    suppression_config_path: str | None = None  # Path to suppression config file
    issue_validation_config: dict[str, Any] | None = None  # Issue validator configuration (min_confidence, rules)

    # PRE-ANALYSIS configuration (NEW!)
    pre_analysis_config: dict[str, Any] | None = None  # PRE-ANALYSIS phase config (use_llm, llm_threshold, etc.)

    # Custom Rules (NEW)
    global_rules: list[CustomRule] = Field(default_factory=list)  # Rules applied to all frames
    frame_rules: dict[str, FrameRules] = Field(default_factory=dict)  # Frame-specific rules (key: frame_id)

    # Semantic Search configuration (NEW!)
    semantic_search_config: dict[str, Any] | None = None  # Configuration for semantic search service
    llm_config: dict[str, Any] | None = None  # LLM configuration (tpm, rpm, etc.)

    # LSP Integration (NEW!)
    lsp_config: dict[str, Any] | None = None  # LSP integration configuration (enabled, servers)

    def to_json(self) -> dict[str, Any]:
        """Convert to Panel-compatible JSON."""
        data = super().to_json()
        # Convert enum to string value
        data["strategy"] = self.strategy.value
        data["analysisLevel"] = self.analysis_level.value

        # Convert custom rules
        data["globalRules"] = [rule.to_json() for rule in self.global_rules]
        data["frameRules"] = {frame_id: frame_rules.to_json() for frame_id, frame_rules in self.frame_rules.items()}

        return data


# Alias for backwards compatibility
PipelineOrchestratorConfig = PipelineConfig


class FrameChain(BaseDomainModel):
    """
    Defines a frame chain for PIPELINE execution strategy.

    Frames execute based on dependency ordering with skip conditions.
    """

    frame: str  # Frame ID to execute
    on_complete: list[str] = Field(default_factory=list)  # Frame IDs to trigger after completion
    skip_if: str | None = None  # Condition name to skip (e.g., "no_sql_sinks")
    priority: int = 1  # Execution priority (lower = sooner)

    def to_json(self) -> dict[str, Any]:
        data = super().to_json()
        return data


class ValidationPipeline(BaseDomainModel):
    """
    Validation pipeline entity.

    Orchestrates execution of multiple validation frames.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str = "Validation Pipeline"
    description: str = ""
    status: PipelineStatus = PipelineStatus.PENDING
    config: PipelineConfig = Field(default_factory=PipelineConfig)

    # Execution tracking
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration: float = 0.0

    # Frame executions
    frame_executions: list[FrameExecution] = Field(default_factory=list)

    # Summary
    total_frames: int = 0
    frames_completed: int = 0
    frames_failed: int = 0
    frames_executed: int = 0  # Total frames executed (including failed)
    frames_passed: int = 0  # Frames that passed validation
    total_issues: int = 0
    blocker_issues: int = 0

    def to_json(self) -> dict[str, Any]:
        """Convert to Panel-compatible JSON."""
        data = super().to_json()

        # Convert enum to int value for Panel
        data["status"] = self.status.value

        # Convert config
        data["config"] = self.config.to_json()

        # Convert frame executions
        data["frameExecutions"] = [fe.to_json() for fe in self.frame_executions]

        return data

    # Valid state transitions to enforce idempotency and prevent invalid states.
    _VALID_TRANSITIONS = {
        PipelineStatus.PENDING: {PipelineStatus.RUNNING, PipelineStatus.CANCELLED},
        PipelineStatus.RUNNING: {PipelineStatus.COMPLETED, PipelineStatus.FAILED, PipelineStatus.CANCELLED},
        PipelineStatus.COMPLETED: set(),
        PipelineStatus.FAILED: set(),
        PipelineStatus.CANCELLED: set(),
    }

    def _transition_to(self, target: "PipelineStatus") -> bool:
        """Attempt state transition. Returns False if transition is invalid."""
        allowed = self._VALID_TRANSITIONS.get(self.status, set())
        if target not in allowed:
            return False
        self.status = target
        return True

    def start(self) -> None:
        """Mark pipeline as started."""
        if not self._transition_to(PipelineStatus.RUNNING):
            return
        self.started_at = datetime.now(timezone.utc)

    def complete(self) -> None:
        """Mark pipeline as completed."""
        if not self._transition_to(PipelineStatus.COMPLETED):
            return
        self.completed_at = datetime.now(timezone.utc)
        if self.started_at:
            self.duration = (self.completed_at - self.started_at).total_seconds()

    def fail(self) -> None:
        """Mark pipeline as failed."""
        if not self._transition_to(PipelineStatus.FAILED):
            return
        self.completed_at = datetime.now(timezone.utc)
        if self.started_at:
            self.duration = (self.completed_at - self.started_at).total_seconds()

    def cancel(self) -> None:
        """Mark pipeline as cancelled."""
        if not self._transition_to(PipelineStatus.CANCELLED):
            return
        self.completed_at = datetime.now(timezone.utc)
        if self.started_at:
            self.duration = (self.completed_at - self.started_at).total_seconds()


class PipelineResult(BaseDomainModel):
    """
    Aggregated pipeline execution result.

    Combines results from all frame executions.
    """

    pipeline_id: str
    pipeline_name: str
    status: PipelineStatus
    duration: float

    # Aggregated statistics
    total_frames: int
    frames_passed: int
    frames_failed: int
    frames_skipped: int

    total_findings: int
    critical_findings: int
    high_findings: int
    medium_findings: int
    low_findings: int
    manual_review_findings: int = 0

    # Findings List (for CLI retrieval)
    findings: list[dict[str, Any]] = Field(default_factory=list)

    # Frame results
    frame_results: list[FrameResult] = Field(default_factory=list)

    # Metadata
    executed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)

    # New fields for Dashboard alignment
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    quality_score: float = 0.0

    # LLM Usage
    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0

    def to_json(self) -> dict[str, Any]:
        """Convert to Panel-compatible JSON."""
        data = super().to_json()

        # Convert enum to int value for Panel
        data["status"] = self.status.value

        # Convert frame results
        data["frameResults"] = [fr.to_json() for fr in self.frame_results]

        # Explicitly map fields to ensure camelCase (Panel expectation)
        data["totalFindings"] = self.total_findings
        data["criticalFindings"] = self.critical_findings
        data["highFindings"] = self.high_findings
        data["mediumFindings"] = self.medium_findings
        data["lowFindings"] = self.low_findings

        # Include findings list
        data["findings"] = self.findings

        # Add token usage
        data["llmUsage"] = {
            "totalTokens": self.total_tokens,
            "promptTokens": self.prompt_tokens,
            "completionTokens": self.completion_tokens,
        }

        # Add LLM performance metrics
        try:
            from warden.llm.factory import get_global_metrics_collector

            metrics_collector = get_global_metrics_collector()
            data["llmMetrics"] = metrics_collector.get_summary()
        except Exception:
            # Gracefully handle if metrics not available
            pass

        data["qualityScore"] = self.quality_score
        data["artifacts"] = self.artifacts

        # IMPORTANT: Add snake_case keys for CLI compatibility (types.ts expects snake_case)
        data["status"] = self.status.value
        data["total_frames"] = self.total_frames
        data["frames_passed"] = self.frames_passed
        data["frames_failed"] = self.frames_failed
        data["frames_skipped"] = self.frames_skipped
        data["total_findings"] = self.total_findings
        data["critical_findings"] = self.critical_findings
        data["high_findings"] = self.high_findings
        data["medium_findings"] = self.medium_findings
        data["low_findings"] = self.low_findings
        data["manual_review_findings"] = self.manual_review_findings
        data["quality_score"] = self.quality_score

        return data

    @property
    def passed(self) -> bool:
        """Check if pipeline passed (no blocker failures)."""
        return self.status == PipelineStatus.COMPLETED and self.frames_failed == 0

    @property
    def has_blockers(self) -> bool:
        """Check if pipeline has blocker issues."""
        return any(fr.is_blocker and not fr.passed for fr in self.frame_results)


class SubStep(BaseDomainModel):
    """
    Pipeline substep (validation frame within validation step).

    Maps to Panel's SubStep interface.
    Panel expects: {id, name, type, status, duration?}
    """

    id: str
    name: str
    type: str  # SubStepType value: 'security' | 'chaos' | 'fuzz' | 'property' | 'stress' | 'architectural'
    status: str  # StepStatus value: 'pending' | 'running' | 'completed' | 'failed' | 'skipped'
    duration: str | None = None  # Format: "0.8s", "1m 43s"

    @classmethod
    def from_frame_execution(cls, frame_exec: FrameExecution) -> "SubStep":
        """
        Convert FrameExecution to SubStep.

        Maps internal frame status to Panel-compatible SubStep status.
        Panel expects: 'pending'|'running'|'completed'|'failed'|'skipped'

        Args:
            frame_exec: FrameExecution instance to convert

        Returns:
            SubStep instance compatible with Panel expectations
        """
        # Calculate duration string
        duration_str = None
        if frame_exec.duration > 0:
            if frame_exec.duration < 60:
                duration_str = f"{frame_exec.duration:.1f}s"
            else:
                minutes = int(frame_exec.duration // 60)
                seconds = int(frame_exec.duration % 60)
                duration_str = f"{minutes}m {seconds}s"

        # Map status to Panel-compatible value
        # frame_exec.status is execution status ('pending', 'running', 'completed', 'skipped')
        # If frame completed, check result for actual validation status
        panel_status = frame_exec.status
        if frame_exec.status == "completed" and frame_exec.result:
            # Map result.status to Panel status
            # 'failed' → 'failed', 'passed' → 'completed', 'warning' → 'completed'
            result_status = frame_exec.result.status
            if result_status == "failed":
                panel_status = "failed"
            elif result_status in ("passed", "warning"):
                panel_status = "completed"

        return cls(
            id=frame_exec.frame_id,
            name=frame_exec.frame_name,
            type=frame_exec.frame_id,  # Use frame_id as type (e.g., 'security', 'chaos')
            status=panel_status,
            duration=duration_str,
        )


class PipelineStep(BaseDomainModel):
    """
    Pipeline step (one of 5 stages).

    Maps to Panel's Step interface.
    Panel expects: {id, name, type, status, duration?, score?, subSteps?}
    """

    id: str
    name: str
    type: str  # StepType value: 'analysis' | 'classification' | 'validation' | 'fortification' | 'cleaning'
    status: str  # StepStatus value: 'pending' | 'running' | 'completed' | 'failed' | 'skipped'
    duration: str | None = None  # Format: "0.8s", "1m 43s"
    score: str | None = None  # Format: "4/10", "8/12"
    sub_steps: list[SubStep] = Field(default_factory=list)  # Only for validation step

    def to_json(self) -> dict[str, Any]:
        """Convert to Panel-compatible JSON with subSteps (camelCase)."""
        data = super().to_json()
        # Ensure subSteps is included (base class handles conversion)
        return data


class PipelineSummary(BaseDomainModel):
    """
    Pipeline execution summary.

    Maps to Panel's PipelineSummary interface.
    Panel expects: {score: {before, after}, lines: {before, after}, duration, progress: {current, total}, findings: {critical, high, medium, low}, aiSource}
    """

    score_before: float = 0.0
    score_after: float = 0.0
    lines_before: int = 0
    lines_after: int = 0
    duration: str = "0s"
    current_step: int = 0
    total_steps: int = 5  # Always 5 steps in Panel's pipeline
    findings_critical: int = 0
    findings_high: int = 0
    findings_medium: int = 0
    findings_low: int = 0
    ai_source: str = "warden-cli"

    def to_json(self) -> dict[str, Any]:
        """
        Convert to Panel-compatible JSON with nested structure.

        Panel expects:
        {
            "score": {"before": 0, "after": 0},
            "lines": {"before": 0, "after": 0},
            "duration": "1m 43s",
            "progress": {"current": 2, "total": 5},
            "findings": {"critical": 0, "high": 0, "medium": 0, "low": 0},
            "aiSource": "warden-cli"
        }
        """
        return {
            "score": {
                "before": self.score_before,
                "after": self.score_after,
            },
            "lines": {
                "before": self.lines_before,
                "after": self.lines_after,
            },
            "duration": self.duration,
            "progress": {
                "current": self.current_step,
                "total": self.total_steps,
            },
            "findings": {
                "critical": self.findings_critical,
                "high": self.findings_high,
                "medium": self.findings_medium,
                "low": self.findings_low,
            },
            "aiSource": self.ai_source,
        }


class PipelineRun(BaseDomainModel):
    """
    Complete pipeline run (Panel's 5-stage pipeline).

    Maps to Panel's PipelineRun interface.
    Panel expects: {id, runNumber, status, trigger, startTime, steps, summary, activeStepId?, activeSubStepId?, activeTabId, testResults?}

    NOTE: This is the NEW model that Panel expects. ValidationPipeline is kept for backwards compatibility.
    """

    id: str
    run_number: int
    status: str  # CRITICAL: Panel expects string: 'running' | 'success' | 'failed'
    trigger: str  # "manual", "git-push", "schedule", etc.
    start_time: datetime
    steps: list[PipelineStep]  # Always 5 steps: analysis, classification, validation, fortification, cleaning
    summary: PipelineSummary
    active_step_id: str | None = None
    active_sub_step_id: str | None = None
    active_tab_id: str = "logs"  # Default tab: "logs" | "console" | "tests" | "issues"
    test_results: dict[str, Any] | None = None  # ValidationTestDetails (complex nested structure)

    def to_json(self) -> dict[str, Any]:
        """
        Convert to Panel-compatible JSON.

        IMPORTANT: Status is already a string ('running' | 'success' | 'failed'),
        so we don't need to convert it like ValidationPipeline does.
        """
        data = super().to_json()
        # Status is already a string, no conversion needed
        # summary.to_json() is called automatically by BaseDomainModel
        return data
