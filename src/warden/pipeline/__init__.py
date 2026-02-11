"""Pipeline module - Validation pipeline orchestration."""

from warden.pipeline.application.phase_orchestrator import PhaseOrchestrator
from warden.pipeline.domain.enums import ExecutionStrategy, PipelineStatus
from warden.pipeline.domain.models import (
    FrameExecution,
    PipelineConfig,
    PipelineResult,
    ValidationPipeline,
)

# Legacy names for compatibility
PipelineOrchestrator = PhaseOrchestrator
EnhancedPipelineOrchestrator = PhaseOrchestrator

__all__ = [
    "ValidationPipeline",
    "PipelineConfig",
    "PipelineResult",
    "FrameExecution",
    "PipelineStatus",
    "ExecutionStrategy",
    "PipelineOrchestrator",
    "EnhancedPipelineOrchestrator",
]
