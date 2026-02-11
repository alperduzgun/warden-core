"""
Anti-Pattern Detection Types

Data types for anti-pattern detection results.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class AntiPatternSeverity(Enum):
    """Severity levels for anti-patterns."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class AntiPatternViolation:
    """Represents a detected anti-pattern."""

    pattern_id: str
    pattern_name: str
    severity: AntiPatternSeverity
    message: str
    file_path: str
    line: int
    column: int = 0
    code_snippet: str | None = None
    suggestion: str | None = None
    is_blocker: bool = False
