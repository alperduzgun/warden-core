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


class TestStatus(str, Enum):
    """
    Test execution status.

    Matches Panel TypeScript TestStatus type.
    """

    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


class FindingSeverity(str, Enum):
    """
    Finding severity levels.

    Matches Panel TypeScript FindingSeverity type.
    """

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class StepType(str, Enum):
    """
    Pipeline step type.

    Maps to Panel's 5-stage pipeline architecture.
    Panel expects string values: 'analysis' | 'classification' | 'validation' | 'fortification' | 'cleaning'
    """

    ANALYSIS = "analysis"
    CLASSIFICATION = "classification"
    VALIDATION = "validation"
    FORTIFICATION = "fortification"
    CLEANING = "cleaning"


class SubStepType(str, Enum):
    """
    Pipeline substep type.

    Maps to Panel's validation frame types.
    Panel expects string values: 'security' | 'chaos' | 'fuzz' | 'property' | 'stress' | 'architectural'
    """

    SECURITY = "security"
    CHAOS = "chaos"
    FUZZ = "fuzz"
    PROPERTY = "property"
    STRESS = "stress"
    ARCHITECTURAL = "architectural"


class StepStatus(str, Enum):
    """
    Pipeline step/substep status.

    Maps to Panel's step status expectations.
    Panel expects string values: 'pending' | 'running' | 'completed' | 'failed' | 'skipped'
    """

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
