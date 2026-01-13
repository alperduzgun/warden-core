"""
Panel conversion utilities.

Provides helpers to convert Core domain models to Panel-compatible formats.
CRITICAL: Panel TypeScript types are SOURCE OF TRUTH - match them EXACTLY.
"""

from warden.pipeline.domain.enums import PipelineStatus
from warden.validation.domain.enums import FramePriority


def pipeline_status_to_panel(status: PipelineStatus) -> str:
    """
    Convert Core PipelineStatus enum to Panel string.

    Panel expects: 'running' | 'success' | 'failed'
    Core uses: PENDING=0, RUNNING=1, COMPLETED=2, FAILED=3, CANCELLED=4

    CRITICAL MAPPING:
    - PipelineStatus.COMPLETED → 'success' (NOT 'completed'!)
    - PipelineStatus.CANCELLED → 'failed' (Panel has no 'cancelled' status)

    Args:
        status: Core PipelineStatus enum

    Returns:
        Panel-compatible status string

    Examples:
        >>> pipeline_status_to_panel(PipelineStatus.RUNNING)
        'running'
        >>> pipeline_status_to_panel(PipelineStatus.COMPLETED)
        'success'
        >>> pipeline_status_to_panel(PipelineStatus.FAILED)
        'failed'
    """
    mapping = {
        PipelineStatus.PENDING: "pending",
        PipelineStatus.RUNNING: "running",
        PipelineStatus.COMPLETED: "success",  # CRITICAL: COMPLETED → success
        PipelineStatus.FAILED: "failed",
        PipelineStatus.CANCELLED: "failed",  # Map cancelled to failed
    }
    return mapping.get(status, "failed")


def frame_priority_to_panel(priority: FramePriority) -> str:
    """
    Convert Core FramePriority enum to Panel string.

    Panel expects: 'critical' | 'high' | 'medium' | 'low'
    Core uses: CRITICAL=0, HIGH=1, MEDIUM=2, LOW=3

    Args:
        priority: Core FramePriority enum

    Returns:
        Panel-compatible priority string

    Examples:
        >>> frame_priority_to_panel(FramePriority.CRITICAL)
        'critical'
        >>> frame_priority_to_panel(FramePriority.HIGH)
        'high'
    """
    mapping = {
        FramePriority.CRITICAL: "critical",
        FramePriority.HIGH: "high",
        FramePriority.MEDIUM: "medium",
        FramePriority.LOW: "low",
    }
    return mapping.get(priority, "low")


def panel_status_to_pipeline(status: str) -> PipelineStatus:
    """
    Convert Panel status string to Core PipelineStatus enum.

    Reverse mapping for panel_status_to_pipeline.

    Args:
        status: Panel status string ('running' | 'success' | 'failed')

    Returns:
        Core PipelineStatus enum

    Examples:
        >>> panel_status_to_pipeline('success')
        PipelineStatus.COMPLETED
        >>> panel_status_to_pipeline('running')
        PipelineStatus.RUNNING
    """
    mapping = {
        "pending": PipelineStatus.PENDING,
        "running": PipelineStatus.RUNNING,
        "success": PipelineStatus.COMPLETED,  # CRITICAL: success → COMPLETED
        "failed": PipelineStatus.FAILED,
    }
    return mapping.get(status, PipelineStatus.FAILED)


def panel_priority_to_frame(priority: str) -> FramePriority:
    """
    Convert Panel priority string to Core FramePriority enum.

    Reverse mapping for frame_priority_to_panel.

    Args:
        priority: Panel priority string ('critical' | 'high' | 'medium' | 'low')

    Returns:
        Core FramePriority enum

    Examples:
        >>> panel_priority_to_frame('critical')
        FramePriority.CRITICAL
        >>> panel_priority_to_frame('high')
        FramePriority.HIGH
    """
    mapping = {
        "critical": FramePriority.CRITICAL,
        "high": FramePriority.HIGH,
        "medium": FramePriority.MEDIUM,
        "low": FramePriority.LOW,
    }
    return mapping.get(priority, FramePriority.LOW)
