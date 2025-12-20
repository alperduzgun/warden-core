"""
Pipeline execution result models.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any


@dataclass
class PipelineResult:
    """
    Result of pipeline execution.

    Contains results from all pipeline stages:
    - Analysis
    - Classification
    - Validation
    - Fortification (optional)
    - Cleaning (optional)
    """

    # Execution metadata
    success: bool
    correlation_id: str
    started_at: datetime
    completed_at: datetime
    duration_ms: float

    # Stage results
    analysis_result: Optional[Dict[str, Any]] = None
    classification_result: Optional[Dict[str, Any]] = None
    validation_summary: Optional[Dict[str, Any]] = None
    fortification_result: Optional[Dict[str, Any]] = None
    cleaning_result: Optional[Dict[str, Any]] = None

    # Status
    message: str = ""
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    # Failure tracking
    failed_stage: Optional[str] = None
    blocker_failures: List[str] = field(default_factory=list)

    def to_json(self) -> dict:
        """Convert to Panel-compatible JSON (camelCase)."""
        return {
            'success': self.success,
            'correlationId': self.correlation_id,
            'startedAt': self.started_at.isoformat(),
            'completedAt': self.completed_at.isoformat(),
            'durationMs': self.duration_ms,
            'analysisResult': self.analysis_result,
            'classificationResult': self.classification_result,
            'validationSummary': self.validation_summary,
            'fortificationResult': self.fortification_result,
            'cleaningResult': self.cleaning_result,
            'message': self.message,
            'errors': self.errors,
            'warnings': self.warnings,
            'failedStage': self.failed_stage,
            'blockerFailures': self.blocker_failures
        }

    @property
    def has_blocker_failures(self) -> bool:
        """Check if pipeline has blocker failures."""
        return len(self.blocker_failures) > 0

    @property
    def stage_count(self) -> int:
        """Count completed stages."""
        count = 0
        if self.analysis_result:
            count += 1
        if self.classification_result:
            count += 1
        if self.validation_summary:
            count += 1
        if self.fortification_result:
            count += 1
        if self.cleaning_result:
            count += 1
        return count
