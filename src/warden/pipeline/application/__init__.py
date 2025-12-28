"""Pipeline application package."""

from warden.pipeline.application.phase_orchestrator import PhaseOrchestrator

# Legacy alias for compatibility
PipelineOrchestrator = PhaseOrchestrator

__all__ = ["PipelineOrchestrator", "PhaseOrchestrator"]
