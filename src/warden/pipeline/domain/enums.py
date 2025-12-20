"""
Pipeline domain enums.

Defines pipeline execution states and strategies.
"""

from enum import Enum


class PipelineStatus(Enum):
    """
    Pipeline execution status.

    Maps to Panel pipeline states.
    Panel expects integer values (0, 1, 2, 3, 4).
    """

    PENDING = 0  # Pipeline created, not started
    RUNNING = 1  # Currently executing frames
    COMPLETED = 2  # All frames completed successfully
    FAILED = 3  # At least one blocker frame failed
    CANCELLED = 4  # Execution cancelled by user


class ExecutionStrategy(Enum):
    """
    Frame execution strategy.

    Determines how frames are executed in the pipeline.
    """

    SEQUENTIAL = "sequential"  # Execute frames one by one
    PARALLEL = "parallel"  # Execute independent frames concurrently
    FAIL_FAST = "fail_fast"  # Stop on first blocker failure


class FramePriority(Enum):
    """
    Frame execution priority.

    Higher priority frames execute first in sequential mode.
    Panel expects integer values.
    """

    CRITICAL = 0  # Must run first (Security)
    HIGH = 1  # Important (Chaos, Performance)
    MEDIUM = 2  # Standard (Code Quality)
    LOW = 3  # Optional (Style, Documentation)
