"""Pipeline module - Validation pipeline orchestration."""

from warden.pipeline.domain.models import (
    ValidationPipeline,
    PipelineConfig,
    PipelineResult,
    FrameExecution,
)
from warden.pipeline.domain.enums import PipelineStatus, ExecutionStrategy
from warden.pipeline.application.phase_orchestrator import PhaseOrchestrator
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
