"""
Pipeline domain models.

Core entities for validation pipeline orchestration.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Optional
from uuid import uuid4

from warden.shared.domain.base_model import BaseDomainModel
from warden.pipeline.domain.enums import PipelineStatus, ExecutionStrategy
from warden.validation.domain.frame import ValidationFrame, FrameResult


@dataclass
class FrameExecution(BaseDomainModel):
    """
    Individual frame execution record.

    Tracks execution of a single frame within a pipeline.
    """

    frame_id: str
    frame_name: str
    status: str  # "pending", "running", "completed", "failed", "skipped"
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration: float = 0.0
    result: Optional[FrameResult] = None
    error: Optional[str] = None

    def to_json(self) -> Dict[str, Any]:
        """Convert to Panel-compatible JSON."""
        data = super().to_json()

        # Convert FrameResult if present
        if self.result:
            data["result"] = self.result.to_json()

        return data


@dataclass
class PipelineConfig(BaseDomainModel):
    """
    Pipeline configuration.

    Defines how frames should be executed.
    """

    strategy: ExecutionStrategy = ExecutionStrategy.SEQUENTIAL
    fail_fast: bool = True
    timeout: int = 300  # Total pipeline timeout in seconds
    frame_timeout: int = 120  # Per-frame timeout in seconds
    parallel_limit: int = 4  # Max concurrent frames in parallel mode
    skip_non_blockers: bool = False  # Skip non-blocker frames if blocker fails

    # Optional pre-processing phases
    enable_discovery: bool = True  # Run file discovery before validation
    enable_build_context: bool = True  # Load build context at pipeline start

    # Optional post-processing phases
    enable_suppression: bool = True  # Apply suppression filtering after validation

    # Phase-specific configurations
    discovery_config: Optional[Dict[str, Any]] = None  # Discovery configuration options
    suppression_config_path: Optional[str] = None  # Path to suppression config file

    def to_json(self) -> Dict[str, Any]:
        """Convert to Panel-compatible JSON."""
        data = super().to_json()
        # Convert enum to string value
        data["strategy"] = self.strategy.value
        return data


@dataclass
class ValidationPipeline(BaseDomainModel):
    """
    Validation pipeline entity.

    Orchestrates execution of multiple validation frames.
    """

    id: str = field(default_factory=lambda: str(uuid4()))
    name: str = "Validation Pipeline"
    description: str = ""
    status: PipelineStatus = PipelineStatus.PENDING
    config: PipelineConfig = field(default_factory=PipelineConfig)

    # Execution tracking
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration: float = 0.0

    # Frame executions
    frame_executions: List[FrameExecution] = field(default_factory=list)

    # Summary
    total_frames: int = 0
    frames_completed: int = 0
    frames_failed: int = 0
    total_issues: int = 0
    blocker_issues: int = 0

    def to_json(self) -> Dict[str, Any]:
        """Convert to Panel-compatible JSON."""
        data = super().to_json()

        # Convert enum to int value for Panel
        data["status"] = self.status.value

        # Convert config
        data["config"] = self.config.to_json()

        # Convert frame executions
        data["frameExecutions"] = [fe.to_json() for fe in self.frame_executions]

        return data

    def start(self) -> None:
        """Mark pipeline as started."""
        self.status = PipelineStatus.RUNNING
        self.started_at = datetime.utcnow()

    def complete(self) -> None:
        """Mark pipeline as completed."""
        self.status = PipelineStatus.COMPLETED
        self.completed_at = datetime.utcnow()
        if self.started_at:
            self.duration = (self.completed_at - self.started_at).total_seconds()

    def fail(self) -> None:
        """Mark pipeline as failed."""
        self.status = PipelineStatus.FAILED
        self.completed_at = datetime.utcnow()
        if self.started_at:
            self.duration = (self.completed_at - self.started_at).total_seconds()

    def cancel(self) -> None:
        """Mark pipeline as cancelled."""
        self.status = PipelineStatus.CANCELLED
        self.completed_at = datetime.utcnow()
        if self.started_at:
            self.duration = (self.completed_at - self.started_at).total_seconds()


@dataclass
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

    # Frame results
    frame_results: List[FrameResult] = field(default_factory=list)

    # Metadata
    executed_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> Dict[str, Any]:
        """Convert to Panel-compatible JSON."""
        data = super().to_json()

        # Convert enum to int value for Panel
        data["status"] = self.status.value

        # Convert frame results
        data["frameResults"] = [fr.to_json() for fr in self.frame_results]

        return data

    @property
    def passed(self) -> bool:
        """Check if pipeline passed (no blocker failures)."""
        return self.status == PipelineStatus.COMPLETED and self.frames_failed == 0

    @property
    def has_blockers(self) -> bool:
        """Check if pipeline has blocker issues."""
        return any(fr.is_blocker and not fr.passed for fr in self.frame_results)
