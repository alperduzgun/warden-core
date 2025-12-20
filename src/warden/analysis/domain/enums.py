"""
Analysis domain enums.

Defines analysis states and trends.
"""

from enum import Enum


class TrendDirection(Enum):
    """
    Code quality trend direction.

    Panel expects string values.
    """

    IMPROVING = "improving"  # Fewer issues over time
    STABLE = "stable"  # Similar issue count
    DEGRADING = "degrading"  # More issues over time
    UNKNOWN = "unknown"  # Insufficient data


class AnalysisStatus(Enum):
    """
    Analysis execution status.

    Maps to Panel analysis states.
    """

    PENDING = 0
    RUNNING = 1
    COMPLETED = 2
    FAILED = 3
